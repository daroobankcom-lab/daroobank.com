"""Opt-in, non-diagnostic HTTP probes for the development foundation."""
import os
import subprocess
import sys
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.db import DatabaseError, connection, transaction
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse


class DisabledProbeTests(SimpleTestCase):
    def test_environment_requires_exact_opt_in(self):
        script = 'from daroobank.settings import HEALTH_PROBES_ENABLED; print(HEALTH_PROBES_ENABLED)'
        for value, expected in ((None, 'False'), ('0', 'False'), ('true', 'False'), ('1', 'True')):
            with self.subTest(value=value):
                env = os.environ.copy()
                env.update(DAROOBANK_DEBUG='1', POSTGRES_DB='synthetic', POSTGRES_USER='synthetic',
                           POSTGRES_HOST='synthetic', POSTGRES_PORT='5432')
                env.pop('DAROOBANK_HEALTH_PROBES_ENABLED', None)
                if value is not None:
                    env['DAROOBANK_HEALTH_PROBES_ENABLED'] = value
                result = subprocess.run([sys.executable, '-c', script], env=env, capture_output=True,
                                        text=True, timeout=5, check=True)
                self.assertEqual(result.stdout.strip(), expected)

    @override_settings(HEALTH_PROBES_ENABLED=False)
    def test_disabled_probes_do_not_touch_database_and_do_not_disclose_input(self):
        for name in ('health_live', 'health_ready'):
            for method in ('get', 'post', 'head'):
                with self.subTest(name=name, method=method):
                    response = getattr(self.client, method)(reverse(name), {'canary': 'private-canary'})
                    self.assertEqual(response.status_code, 404)
                    self.assertNotIn(b'private-canary', response.content)
                    self.assertEqual(response['Cache-Control'], 'no-store')
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                    self.assertEqual(response['Referrer-Policy'], 'no-referrer')

    @override_settings(HEALTH_PROBES_ENABLED=True)
    def test_liveness_is_get_head_only_and_never_checks_database(self):
        url = reverse('health_live')
        with patch('daroobank.health.database_ready', side_effect=AssertionError('database used')):
            self.assertEqual(self.client.get(url).content, b'ok\n')
            self.assertEqual(self.client.head(url).status_code, 200)
            self.assertEqual(self.client.head(url).content, b'')
            self.assertEqual(self.client.post(url).status_code, 405)
        for method in ('get', 'head', 'post'):
            response = getattr(self.client, method)(url)
            self.assertEqual(response['Cache-Control'], 'no-store')
            self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    @override_settings(HEALTH_PROBES_ENABLED=True, STAFF_PORTAL_ENABLED=True)
    def test_csrf_rejection_and_method_rejection_have_privacy_headers(self):
        client = Client(enforce_csrf_checks=True)
        url = reverse('health_ready')
        with patch('daroobank.health.database_ready', side_effect=AssertionError('unsafe method queried database')):
            rejected = client.post(url)
            self.assertEqual(rejected.status_code, 403)
            self.assertEqual(rejected['Cache-Control'], 'no-store')
            client.get(reverse('staff_login'))
            rejected = client.post(url, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
            self.assertEqual(rejected.status_code, 405)
            self.assertEqual(rejected['Cache-Control'], 'no-store')
            self.assertEqual(rejected['X-Robots-Tag'], 'noindex, nofollow')

    @override_settings(HEALTH_PROBES_ENABLED=True, DEBUG=False, SECURE_SSL_REDIRECT=True)
    def test_https_redirect_and_unresolved_health_paths_are_not_cached(self):
        response = self.client.get(reverse('health_live'))
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        response = self.client.get('/health/not-a-probe/', secure=True)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response['Cache-Control'], 'no-store')

    @override_settings(HEALTH_PROBES_ENABLED=True)
    def test_unavailable_readiness_is_generic_non_cacheable_and_does_not_echo(self):
        url = reverse('health_ready')
        with patch('daroobank.health.database_ready', return_value=False):
            response = self.client.get(url, {'canary': 'private-canary'})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.content, b'unavailable\n')
            self.assertNotIn(b'private-canary', response.content)
            self.assertEqual(response['Cache-Control'], 'no-store')
            self.assertEqual(response['Referrer-Policy'], 'no-referrer')
            self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
            head = self.client.head(url)
            self.assertEqual(head.status_code, 503)
            self.assertEqual(head.content, b'')
        with patch('daroobank.health.database_ready', side_effect=AssertionError('database used')):
            self.assertEqual(self.client.post(url).status_code, 405)


@override_settings(HEALTH_PROBES_ENABLED=True)
class DatabaseProbeTests(TransactionTestCase):
    def test_readiness_uses_real_postgresql_without_application_data_or_writes(self):
        self.assertEqual(connection.vendor, 'postgresql')
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('health_ready'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b'ok\n')
        sql = [item['sql'].upper() for item in queries]
        self.assertTrue(any('SET LOCAL STATEMENT_TIMEOUT' in item for item in sql), sql)
        self.assertTrue(any('SELECT 1' in item for item in sql), sql)
        self.assertFalse(any('INSERT ' in item or 'UPDATE ' in item or 'DELETE ' in item for item in sql), sql)
        self.assertEqual(self.client.head(reverse('health_ready')).status_code, 200)

    def test_database_error_is_not_echoed_or_logged_by_probe(self):
        with patch('daroobank.health.transaction.atomic', side_effect=DatabaseError('secret-db-canary')):
            response = self.client.get(reverse('health_ready'))
        self.assertEqual(response.status_code, 503)
        self.assertNotIn(b'secret-db-canary', response.content)
        self.assertEqual(response.content, b'unavailable\n')

    def test_real_disconnected_socket_is_generic_and_connection_can_recover(self):
        with TemporaryDirectory(prefix='synthetic-empty-socket-') as empty_socket:
            original_host = connection.settings_dict['HOST']
            connection.close()
            try:
                connection.settings_dict['HOST'] = empty_socket
                response = self.client.get(reverse('health_ready'))
                self.assertEqual(response.status_code, 503)
                self.assertEqual(response.content, b'unavailable\n')
                self.assertNotIn(empty_socket.encode(), response.content)
            finally:
                connection.close()
                connection.settings_dict['HOST'] = original_host
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                self.assertEqual(cursor.fetchone(), (1,))

    def test_failed_connection_does_not_leak_details_or_return_server_error(self):
        with patch.object(connection, 'get_autocommit', side_effect=DatabaseError('connection-secret-canary')):
            response = self.client.get(reverse('health_ready'))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b'unavailable\n')
        self.assertNotIn(b'connection-secret-canary', response.content)

    def test_probe_refuses_to_change_timeout_inside_outer_transaction(self):
        from .health import database_ready
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '9s'")
            with CaptureQueriesContext(connection) as queries:
                self.assertFalse(database_ready())
            self.assertEqual(len(queries), 0)
            with connection.cursor() as cursor:
                cursor.execute('SHOW statement_timeout')
                self.assertEqual(cursor.fetchone()[0], '9s')

    def test_success_does_not_change_connection_statement_timeout(self):
        with connection.cursor() as cursor:
            cursor.execute('SHOW statement_timeout')
            original = cursor.fetchone()[0]
            cursor.execute("SET statement_timeout = '9s'")
        try:
            self.assertEqual(self.client.get(reverse('health_ready')).status_code, 200)
            with connection.cursor() as cursor:
                cursor.execute('SHOW statement_timeout')
                self.assertEqual(cursor.fetchone()[0], '9s')
        finally:
            with connection.cursor() as cursor:
                cursor.execute('SELECT set_config(%s, %s, false)', ['statement_timeout', original])

    def test_server_statement_timeout_recovers_connection(self):
        def delay(execute, sql, params, many, context):
            if sql == 'SELECT 1':
                return execute('SELECT pg_sleep(2)', None, many, context)
            return execute(sql, params, many, context)
        with connection.execute_wrapper(delay):
            response = self.client.get(reverse('health_ready'))
        self.assertEqual(response.status_code, 503)
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            self.assertEqual(cursor.fetchone(), (1,))
