"""Synthetic opt-in login throttling; not MFA or production authorization."""
import concurrent.futures
import os
import subprocess
import sys
import time
from datetime import timedelta
from queue import Queue
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone


class StaffLoginThrottleConfigurationTests(SimpleTestCase):
    def test_exact_opt_in_and_debug_gate(self):
        script = 'from daroobank.settings import STAFF_LOGIN_THROTTLE_ENABLED; print(STAFF_LOGIN_THROTTLE_ENABLED)'
        for debug, value, expected in (('1', None, 'False'), ('1', '0', 'False'), ('1', 'true', 'False'),
                                       ('1', '1', 'True'), ('0', '1', 'False')):
            with self.subTest(debug=debug, value=value):
                env = os.environ.copy()
                env.update(DAROOBANK_DEBUG=debug, DAROOBANK_SECRET_KEY='synthetic-secret',
                           POSTGRES_DB='synthetic', POSTGRES_USER='synthetic',
                           POSTGRES_HOST='synthetic', POSTGRES_PORT='5432')
                env.pop('DAROOBANK_STAFF_LOGIN_THROTTLE', None)
                if value is not None:
                    env['DAROOBANK_STAFF_LOGIN_THROTTLE'] = value
                result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True,
                                        text=True, timeout=5, check=True)
                self.assertEqual(result.stdout.strip(), expected)


@override_settings(STAFF_PORTAL_ENABLED=True, STAFF_LOGIN_THROTTLE_ENABLED=True)
class StaffLoginThrottleTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('synthetic-staff', password='synthetic-password', is_staff=True)
        self.url = reverse('staff_login')

    def post(self, client, *, address='192.0.2.42', password='wrong', username='synthetic-staff', **extra):
        return client.post(self.url, {'username': username, 'password': password, 'next': 'https://attacker.example/'},
                           REMOTE_ADDR=address, **extra)

    def test_fixed_window_blocks_before_authentication_without_echo_and_recovers(self):
        from staff_security.models import StaffLoginWindow
        from staff_security.throttle import ATTEMPT_LIMIT
        client = Client()
        for _ in range(ATTEMPT_LIMIT):
            response = self.post(client)
            self.assertEqual(response.status_code, 200)
        with patch('django.contrib.auth.forms.authenticate', side_effect=AssertionError('throttled request authenticated')):
            denied = self.post(client, password='private-password-canary')
        self.assertEqual(denied.status_code, 429)
        self.assertNotIn(b'private-password-canary', denied.content)
        self.assertNotIn(b'attacker.example', denied.content)
        self.assertEqual(denied['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(denied['X-Robots-Tag'], 'noindex, nofollow')
        self.assertNotIn('_auth_user_id', client.session)
        row = StaffLoginWindow.objects.get()
        self.assertNotIn('192.0.2.42', row.client_key)
        self.assertEqual(len(row.client_key), 64)
        self.assertEqual(row.attempts, ATTEMPT_LIMIT + 1)
        StaffLoginWindow.objects.update(started_at=timezone.now() - timedelta(minutes=2))
        response = self.post(client, password='synthetic-password')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_workspace'))
        self.assertIn('_auth_user_id', client.session)
        self.assertEqual(StaffLoginWindow.objects.get().attempts, 1)

    def test_different_ips_are_independent_and_forwarded_header_is_ignored(self):
        from staff_security.models import StaffLoginWindow
        from staff_security.throttle import ATTEMPT_LIMIT
        client = Client()
        for i in range(ATTEMPT_LIMIT):
            self.assertEqual(self.post(client, HTTP_X_FORWARDED_FOR=f'198.51.100.{i+1}').status_code, 200)
        self.assertEqual(self.post(client, HTTP_X_FORWARDED_FOR='203.0.113.9').status_code, 429)
        self.assertEqual(self.post(client, address='192.0.2.43', password='synthetic-password').status_code, 302)
        self.assertEqual(StaffLoginWindow.objects.count(), 2)

    def test_invalid_remote_address_and_database_failure_fail_closed(self):
        from staff_security.models import StaffLoginWindow
        client = Client()
        for address in ('', 'not-an-address', '192.0.2.1, 192.0.2.2', 'fe80::1%eth0', '1' * 1000):
            with self.subTest(address=address):
                response = self.post(client, address=address, password='synthetic-password')
                self.assertEqual(response.status_code, 503)
                self.assertNotIn('_auth_user_id', client.session)
        self.assertFalse(StaffLoginWindow.objects.exists())
        with patch('staff_security.throttle.transaction.atomic', side_effect=DatabaseError('db-secret-canary')):
            response = self.post(client, password='synthetic-password')
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'db-secret-canary', response.content)
        self.assertNotIn('_auth_user_id', client.session)

    def test_ipv4_mapped_ipv6_cannot_bypass_one_address_limit(self):
        from staff_security.throttle import ATTEMPT_LIMIT
        client = Client()
        for _ in range(ATTEMPT_LIMIT):
            self.assertEqual(self.post(client, address='192.0.2.42').status_code, 200)
        self.assertEqual(self.post(client, address='::ffff:192.0.2.42').status_code, 429)

    @override_settings(STAFF_LOGIN_THROTTLE_ENABLED=False)
    def test_disabled_control_does_not_write_and_normal_login_still_works(self):
        from staff_security.models import StaffLoginWindow
        with patch('staff_security.throttle.consume_attempt', side_effect=AssertionError('disabled control used')):
            response = self.post(Client(), password='synthetic-password')
        self.assertEqual(response.status_code, 302)
        self.assertFalse(StaffLoginWindow.objects.exists())

    def test_success_does_not_reset_window_or_revoke_existing_session_when_limited(self):
        from staff_security.throttle import ATTEMPT_LIMIT
        client = Client()
        self.assertEqual(self.post(client, password='synthetic-password').status_code, 302)
        for _ in range(ATTEMPT_LIMIT - 1):
            self.assertEqual(self.post(client).status_code, 200)
        self.assertEqual(self.post(client, password='synthetic-password').status_code, 429)
        self.assertEqual(str(client.session['_auth_user_id']), str(self.user.pk))

    def test_future_window_does_not_reset_on_clock_regression(self):
        from staff_security.throttle import _client_key
        from staff_security.models import StaffLoginWindow
        StaffLoginWindow.objects.create(client_key=_client_key('192.0.2.42'),
                                        started_at=timezone.now() + timedelta(hours=1), attempts=10)
        client = Client()
        self.assertEqual(self.post(client, password='synthetic-password').status_code, 503)
        self.assertNotIn('_auth_user_id', client.session)
        self.assertEqual(StaffLoginWindow.objects.get().attempts, 10)

    def test_safe_get_and_failed_csrf_do_not_consume_attempts(self):
        from staff_security.models import StaffLoginWindow
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.get(self.url).status_code, 200)
        self.assertEqual(self.post(client).status_code, 403)
        self.assertFalse(StaffLoginWindow.objects.exists())
        token = client.cookies['csrftoken'].value
        response = self.post(client, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StaffLoginWindow.objects.get().attempts, 1)

    def test_existing_outer_transaction_is_not_modified_and_fails_closed(self):
        from staff_security.throttle import consume_attempt
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '9s'")
            self.assertEqual(consume_attempt('192.0.2.42'), 'unavailable')
            with connection.cursor() as cursor:
                cursor.execute('SHOW lock_timeout')
                self.assertEqual(cursor.fetchone()[0], '9s')

    def test_lock_timeout_fails_closed_and_connection_is_reusable(self):
        from staff_security.models import StaffLoginWindow
        from staff_security.throttle import _client_key, consume_attempt
        address = '192.0.2.88'
        self.assertEqual(consume_attempt(address), 'allowed')
        announced = Queue()
        def worker():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '10s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    pid = cursor.fetchone()[0]
                seen = False
                def observe(execute, sql, params, many, context):
                    nonlocal seen
                    if not seen and sql.lstrip().upper().startswith('INSERT INTO') and 'staff_security_staffloginwindow' in sql:
                        seen = True
                        announced.put(pid)
                    return execute(sql, params, many, context)
                with connection.execute_wrapper(observe):
                    result = consume_attempt(address)
                with connection.cursor() as cursor:
                    cursor.execute('SELECT 1')
                    healthy = cursor.fetchone()
                return result, healthy
            finally:
                connection.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                StaffLoginWindow.objects.select_for_update().get(pk=_client_key(address))
                future = pool.submit(worker)
                pid = announced.get(timeout=8)
                deadline = time.monotonic() + .8
                blocked = False
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT cardinality(pg_blocking_pids(%s)) > 0', [pid])
                        blocked = cursor.fetchone()[0]
                    if blocked or future.done():
                        break
                    time.sleep(.01)
                self.assertTrue(blocked, 'throttle did not wait for the target row')
                self.assertEqual(future.result(timeout=5), ('unavailable', (1,)))
        self.assertEqual(StaffLoginWindow.objects.get().attempts, 1)

    def test_concurrent_workers_cannot_exceed_fixed_window_limit(self):
        from staff_security.throttle import ATTEMPT_LIMIT, consume_attempt
        def attempt(_):
            close_old_connections()
            try:
                return consume_attempt('192.0.2.90')
            finally:
                connection.close()
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(attempt, range(24)))
        self.assertEqual(results.count('allowed'), ATTEMPT_LIMIT, results)
        self.assertEqual(results.count('limited'), 24 - ATTEMPT_LIMIT, results)
