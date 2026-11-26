"""Selected regression checks for the default-closed non-debug staff boundary."""
import json
import os
import subprocess
import sys
from pathlib import Path
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

    def test_real_nondebug_settings_close_all_named_staff_routes(self):
        # A fresh process verifies the actual settings and middleware assembly,
        # not merely an override of a debug-initialized configuration.
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DJANGO_SETTINGS_MODULE='daroobank.settings', DAROOBANK_DEBUG='0',
                   DAROOBANK_SECRET_KEY='synthetic-only-not-a-real-key-0123456789-abcdefghijklm',
                   DAROOBANK_ALLOWED_HOSTS='example.org', POSTGRES_DB='synthetic',
                   POSTGRES_USER='synthetic', POSTGRES_HOST='not-connected', POSTGRES_PORT='5432')
        script = '''
import django, json
django.setup()
from django.conf import settings
from django.test import Client
from django.urls import get_resolver, reverse
from unittest.mock import patch
if settings.DEBUG or settings.STAFF_PORTAL_ENABLED:
    raise RuntimeError('non-debug staff gate unexpectedly open')
client = Client(enforce_csrf_checks=True)
client.cookies['sessionid'] = 'synthetic-session-canary'
checked = 0
with patch('django.contrib.sessions.backends.db.SessionStore.load', side_effect=RuntimeError('unexpected session load')):
    for pattern in get_resolver().url_patterns:
        if not (pattern.name or '').startswith('staff_'):
            continue
        kwargs = {name: 1 if converter.__class__.__name__ == 'IntConverter' else 'synthetic'
                  for name, converter in pattern.pattern.converters.items()}
        path = reverse(pattern.name, kwargs=kwargs)
        for method in ('get', 'head', 'post'):
            response = getattr(client, method)(path, secure=True, HTTP_HOST='example.org')
            if (response.status_code != 404 or response.get('Cache-Control') != 'private, no-store, max-age=0'
                    or response.get('X-Robots-Tag') != 'noindex, nofollow'
                    or response.get('X-Frame-Options') != 'DENY'):
                raise RuntimeError('staff boundary failed for a selected named route')
            checked += 1
print(json.dumps(checked))
'''
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parent.parent,
                                env=env, capture_output=True, text=True, timeout=20, check=True)
        self.assertGreater(json.loads(result.stdout), 90)
        self.assertNotIn('synthetic-session-canary', result.stdout + result.stderr)

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
