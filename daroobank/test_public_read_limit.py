"""The opt-in limit on public reads: what it refuses, what it stores, and what it never does.

ADR 0223 measured that this application had exactly one rate limit — the opt-in, debug-only
staff-login window — and that 48 sequential anonymous reads of six public routes all answered 200,
wrote nothing and carried no rate header. It also recorded that abuse protection is assigned to the
edge, in `docs/DEPLOYMENT.md`, and that nothing in the application answers 429 on a public path.

This suite measures the mechanism that closes the application-side half of that gap: a fixed window
per keyed client over public reads, off by default, shared between workers through PostgreSQL, and
built on the same shape as the login window in `staff_security/throttle.py`. Three properties matter
more than the count.

* **Off means off.** With the setting unset, reads answer as they always did and no row is written
  anywhere, so every absence ADR 0223 measured still holds and the edge remains the only control a
  default deployment has.
* **On means a refusal a client can act on.** The read after the limit answers 429 with an empty
  body, a `Retry-After` delay inside the window, and the public privacy headers — which the
  middleware sets itself, because a refusal is produced before URL resolution.
* **It stores a window, not a history.** One row per keyed client holds a digest, a start time and a
  counter: no address, path, route, query, user agent or account, and a key scope of its own so a
  read window cannot be joined with a login window.

An unavailable limiter serves the read. That is the opposite of the login path, where an unavailable
limiter fails closed with 503, and the difference is deliberate: refusing authentication protects an
account, while refusing a public read turns one database problem into an outage.

These tests use `TransactionTestCase` wherever they exercise the real window, because the service
returns `unavailable` inside an outer atomic block rather than touch a caller's transaction.
"""
import re
from datetime import timedelta
from unittest import mock

from django.conf import settings
from django.contrib.sessions.models import Session
from django.db import DatabaseError
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from staff_security import read_limit, throttle
from staff_security.models import PublicReadWindow, StaffLoginWindow

from .test_no_abuse_protection import PUBLIC_READS, RATE_HEADERS
from .test_no_read_audit import project_models

ADDRESS = '203.0.113.7'
MAPPED = '::ffff:203.0.113.7'
OTHER = '198.51.100.9'
HEX64 = re.compile(r'^[0-9a-f]{64}$')
STORED_FIELDS = ['client_key', 'started_at', 'reads']
READS_PER_ROUTE = 8


def read(client, name='home', query=None, address=ADDRESS, **extra):
    return client.get(reverse(name), query or {}, REMOTE_ADDR=address, **extra)


def rows_as_text():
    """Every stored value of every window row, as text, for a leak inspection."""
    return [str(value) for row in PublicReadWindow.objects.all()
            for value in (row.client_key, row.started_at.isoformat(), row.reads)]


class LimiterShapeTests(SimpleTestCase):
    def test_the_limiter_is_opt_in_and_its_window_is_declared_in_code(self):
        self.assertFalse(settings.PUBLIC_READ_LIMIT_ENABLED,
                         'the limiter must be off unless the deployment asks for it')
        self.assertEqual(read_limit.READ_LIMIT, 120)
        self.assertEqual(read_limit.WINDOW, timedelta(seconds=60))
        self.assertEqual(read_limit.SCOPE, 'staff_security.public_read.v1')
        self.assertIn('daroobank.middleware.PublicReadLimitMiddleware', settings.MIDDLEWARE)
        # Above the session middleware, so a refused read creates no session row.
        index = settings.MIDDLEWARE.index('daroobank.middleware.PublicReadLimitMiddleware')
        sessions = settings.MIDDLEWARE.index('django.contrib.sessions.middleware.SessionMiddleware')
        self.assertLess(index, sessions)

    def test_the_read_key_is_scoped_apart_from_the_login_key(self):
        read_key = read_limit.client_key(ADDRESS)
        login_key = throttle._client_key(ADDRESS)
        self.assertTrue(HEX64.match(read_key))
        self.assertTrue(HEX64.match(login_key))
        self.assertNotEqual(read_key, login_key, 'the two windows share a key space')
        self.assertNotIn(ADDRESS, read_key)
        self.assertEqual(read_limit.client_key(MAPPED), read_key,
                         'an IPv4-mapped IPv6 address is a different client')
        for unusable in (None, '', 'not-an-address', 'fe80::1%eth0', '203.0.113.7 extra', 'x' * 46):
            with self.subTest(address=unusable):
                self.assertIsNone(read_limit.client_key(unusable))


class DisabledLimiterTests(TransactionTestCase):
    def test_public_reads_are_still_never_refused_and_write_nothing(self):
        before = {label: model.objects.count() for label, model in sorted(project_models().items())}
        seen = 0
        for name, query in PUBLIC_READS:
            for _ in range(READS_PER_ROUTE):
                response = read(self.client, name, query)
                seen += 1
                with self.subTest(route=name):
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual([header for header in response.headers
                                      if any(word in header.lower() for word in RATE_HEADERS)], [],
                                     'a disabled limiter still added a rate header')
        self.assertEqual(seen, len(PUBLIC_READS) * READS_PER_ROUTE)
        counts = {label: model.objects.count() for label, model in sorted(project_models().items())}
        self.assertEqual(counts, before, 'a disabled limiter wrote a row')


@override_settings(PUBLIC_READ_LIMIT_ENABLED=True)
class EnabledLimiterTests(TransactionTestCase):
    def test_reads_under_the_limit_are_served_and_counted_in_one_keyed_row(self):
        for _ in range(5):
            self.assertEqual(read(self.client).status_code, 200)
        self.assertEqual(PublicReadWindow.objects.count(), 1)
        row = PublicReadWindow.objects.get()
        self.assertTrue(HEX64.match(row.client_key))
        self.assertEqual(row.reads, 5)
        self.assertEqual([field.name for field in PublicReadWindow._meta.fields], STORED_FIELDS,
                         'the window table gained a column, so it can hold more than a window')
        self.assertEqual(StaffLoginWindow.objects.count(), 0,
                         'a public read touched the login window')
        self.assertEqual(Session.objects.count(), 0)

    def test_a_second_client_gets_a_window_of_its_own(self):
        read(self.client, address=ADDRESS)
        read(self.client, address=OTHER)
        read(self.client, address=MAPPED)
        self.assertEqual(PublicReadWindow.objects.count(), 2,
                         'the mapped address is not the same client as the plain one')
        keys = list(PublicReadWindow.objects.values_list('client_key', flat=True))
        self.assertEqual(len(set(keys)), 2)
        for key in keys:
            self.assertNotIn(ADDRESS, key)
            self.assertNotIn(OTHER, key)

    def test_the_read_after_the_limit_is_refused_with_a_retry_after_delay(self):
        with mock.patch.object(read_limit, 'READ_LIMIT', 3):
            self.assertEqual([read(self.client).status_code for _ in range(3)], [200, 200, 200])
            refused = read(self.client, 'search', {'q': 'synthetic-marker'},
                           HTTP_USER_AGENT='synthetic-agent-marker')
            self.assertEqual(read(self.client).status_code, 429)
        self.assertEqual(refused.status_code, 429)
        self.assertEqual(refused.content, b'', 'a refusal explained itself to the client')
        delay = int(refused.headers['Retry-After'])
        self.assertTrue(1 <= delay <= 60, f'Retry-After {delay} is outside the window')
        self.assertEqual(refused.headers['Cache-Control'], 'no-store')
        self.assertEqual(refused.headers['Referrer-Policy'], 'no-referrer')
        self.assertEqual(refused.headers['X-Robots-Tag'], 'noindex, follow')
        self.assertIn('Content-Security-Policy', refused.headers)
        self.assertEqual(Session.objects.count(), 0, 'a refused read created a session')
        # The window holds a counter, not the request that was refused.
        stored = ' '.join(rows_as_text())
        for marker in ('synthetic-marker', 'synthetic-agent-marker', '/search', ADDRESS, 'q='):
            self.assertNotIn(marker, stored, 'the window stored part of the request')

    def test_the_window_rolls_over_and_a_backwards_clock_does_not_reset_it(self):
        with mock.patch.object(read_limit, 'READ_LIMIT', 1):
            self.assertEqual(read(self.client).status_code, 200)
            self.assertEqual(read(self.client).status_code, 429)
            PublicReadWindow.objects.update(started_at=timezone.now() - timedelta(seconds=61))
            self.assertEqual(read(self.client).status_code, 200,
                             'an expired window did not roll over')
            self.assertEqual(PublicReadWindow.objects.get().reads, 1)
            self.assertEqual(read(self.client).status_code, 429)
            # A clock behind the stored window start must not reset the counter.
            PublicReadWindow.objects.update(started_at=timezone.now() + timedelta(hours=1))
            self.assertEqual(read(self.client).status_code, 200, 'a backwards clock refused a read')
            self.assertEqual(PublicReadWindow.objects.get().reads, 2,
                             'a backwards clock reset or advanced the window')

    def test_staff_paths_and_health_probes_are_not_limited(self):
        with mock.patch.object(read_limit, 'READ_LIMIT', 1):
            for path in ('/staff/', '/staff/products/', '/health', '/health/ready'):
                for _ in range(3):
                    response = self.client.get(path, REMOTE_ADDR=ADDRESS)
                    with self.subTest(path=path):
                        self.assertNotEqual(response.status_code, 429, 'a limited path was refused')
        self.assertEqual(PublicReadWindow.objects.count(), 0, 'an excluded path wrote a window row')

    def test_an_unkeyable_or_failing_client_is_served_rather_than_refused(self):
        for address in ('not-an-address', '', 'fe80::1%eth0'):
            with self.subTest(address=address), mock.patch.object(read_limit, 'READ_LIMIT', 0):
                self.assertEqual(read(self.client, address=address).status_code, 200,
                                 'an unkeyable client was refused')
        self.assertEqual(PublicReadWindow.objects.count(), 0)
        with mock.patch('staff_security.read_limit.transaction.atomic',
                        side_effect=DatabaseError('synthetic failure')):
            self.assertEqual(read_limit.consume_read(ADDRESS), ('unavailable', 0),
                             'a database failure was not reported as unavailable')
        with mock.patch('daroobank.middleware.consume_read', return_value=('unavailable', 0)):
            response = read(self.client)
        self.assertEqual(response.status_code, 200, 'a database failure refused a public read')
        self.assertEqual(PublicReadWindow.objects.count(), 0)

    def test_a_non_get_request_is_not_counted(self):
        with mock.patch.object(read_limit, 'READ_LIMIT', 1):
            self.client.post(reverse('home'), {}, REMOTE_ADDR=ADDRESS)
            self.client.head(reverse('home'), REMOTE_ADDR=ADDRESS)
            self.assertEqual(PublicReadWindow.objects.count(), 0,
                             'a write or a HEAD opened a window')
            self.assertEqual(read(self.client).status_code, 200)


class ModelShapeTests(TestCase):
    def test_the_window_model_holds_no_request_detail(self):
        fields = {field.name: field for field in PublicReadWindow._meta.fields}
        self.assertEqual(sorted(fields), sorted(STORED_FIELDS))
        self.assertTrue(fields['client_key'].primary_key)
        self.assertEqual(fields['client_key'].max_length, 64)
        self.assertTrue(fields['started_at'].db_index)
        self.assertEqual(PublicReadWindow._meta.default_permissions, ())
        for token in ('path', 'route', 'url', 'query', 'agent', 'actor', 'user', 'address', 'ip'):
            self.assertNotIn(token, ' '.join(fields).lower(), 'the window gained a request detail')
