"""Selected regression checks for the default-closed non-debug staff boundary."""
from unittest.mock import patch

from django.test import Client, SimpleTestCase, override_settings
from django.urls import get_resolver, reverse


@override_settings(DEBUG=False, STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=True)
class DisabledStaffBoundaryTests(SimpleTestCase):
    def test_all_named_staff_routes_are_inside_gated_prefix(self):
        # A new staff URL outside this path would bypass the middleware gate.
        patterns = get_resolver().url_patterns
        staff = [pattern for pattern in patterns if (pattern.name or '').startswith('staff_')]
        self.assertGreater(len(staff), 30)
        for pattern in staff:
            with self.subTest(name=pattern.name):
                self.assertTrue(str(pattern.pattern).startswith('staff/'))
        for pattern in patterns:
            if str(pattern.pattern).startswith('staff/'):
                with self.subTest(pattern=str(pattern.pattern)):
                    self.assertTrue((pattern.name or '').startswith('staff_'))

    def test_all_current_routes_return_private_404_before_session_or_view(self):
        client = Client(enforce_csrf_checks=True)
        for pattern in get_resolver().url_patterns:
            if not (pattern.name or '').startswith('staff_'):
                continue
            kwargs = {}
            for name, converter in pattern.pattern.converters.items():
                kwargs[name] = 1 if converter.__class__.__name__ == 'IntConverter' else 'synthetic'
            path = reverse(pattern.name, kwargs=kwargs)
            for method in ('get', 'head', 'post'):
                with self.subTest(name=pattern.name, method=method), \
                     patch('django.contrib.sessions.backends.db.SessionStore.load',
                           side_effect=AssertionError('disabled staff route accessed a session')):
                    response = getattr(client, method)(path, secure=True, HTTP_COOKIE='sessionid=synthetic-canary')
                    self.assertEqual(response.status_code, 404)
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                    self.assertEqual(response['Referrer-Policy'], 'same-origin')
                    self.assertNotIn('synthetic-canary', response.content.decode('utf-8'))
