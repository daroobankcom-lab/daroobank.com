"""Selected response-header guarantees, not a complete browser security assessment."""
import json
import os
from pathlib import Path
import subprocess
import sys

from django.http import HttpResponse
from django.test import Client, SimpleTestCase, override_settings
from django.urls import path, reverse

from .middleware import ContentSecurityPolicyMiddleware, DEVELOPMENT_CSP


def synthetic_error(request):
    raise RuntimeError('synthetic error')


urlpatterns = [path('synthetic-error/', synthetic_error)]


class ContentSecurityPolicyTests(SimpleTestCase):
    def test_selected_responses_get_restrictive_policy(self):
        client = Client()
        for path, method in ((reverse('home'), 'get'), (reverse('search'), 'get'),
                             (reverse('search_api'), 'get'), (reverse('staff_login'), 'get'),
                             ('/missing-synthetic-page', 'get'), (reverse('home'), 'post')):
            with self.subTest(path=path, method=method):
                response = getattr(client, method)(path)
                self.assertEqual(response['Content-Security-Policy'], DEVELOPMENT_CSP)
        self.assertIn("script-src 'self'", DEVELOPMENT_CSP)
        self.assertIn("style-src 'self'", DEVELOPMENT_CSP)
        self.assertIn("object-src 'none'", DEVELOPMENT_CSP)
        self.assertIn("base-uri 'none'", DEVELOPMENT_CSP)
        self.assertIn("form-action 'self'", DEVELOPMENT_CSP)
        self.assertNotIn("'unsafe-inline'", DEVELOPMENT_CSP)
        self.assertNotIn("'unsafe-eval'", DEVELOPMENT_CSP)
        # Do not block the development preview from framing the app.
        self.assertNotIn('frame-ancestors', DEVELOPMENT_CSP)

    @override_settings(SECURE_SSL_REDIRECT=True)
    def test_security_redirect_gets_policy_too(self):
        response = Client().get(reverse('home'))
        self.assertEqual(response.status_code, 301)
        self.assertEqual(response['Content-Security-Policy'], DEVELOPMENT_CSP)

    @override_settings(ROOT_URLCONF=__name__, DEBUG=False, SECURE_SSL_REDIRECT=False)
    def test_converted_server_error_gets_policy(self):
        with self.assertLogs('django.request', level='ERROR'):
            response = Client(raise_request_exception=False).get('/synthetic-error/')
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response['Content-Security-Policy'], DEVELOPMENT_CSP)

    def test_non_debug_settings_retain_separate_frame_deny(self):
        # Fresh process imports the real non-debug middleware list. Its DB
        # coordinates are deliberately invalid; this home request needs no DB.
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DJANGO_SETTINGS_MODULE='daroobank.settings', DAROOBANK_DEBUG='0',
                   DAROOBANK_SECRET_KEY='synthetic-only-test-key', DAROOBANK_ALLOWED_HOSTS='localhost',
                   POSTGRES_DB='synthetic-no-connection', POSTGRES_USER='synthetic',
                   POSTGRES_HOST='/synthetic-no-server', POSTGRES_PORT='5432')
        script = ("import django, json; django.setup(); from django.test import Client; "
                  "r=Client().get('/', secure=True, HTTP_HOST='localhost'); "
                  "print(json.dumps([r.status_code, r.get('X-Frame-Options'), r.get('Content-Security-Policy')]))")
        result = subprocess.run([sys.executable, '-c', script], env=env, cwd=Path(__file__).resolve().parent.parent,
                                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=True)
        status, frame, policy = json.loads(result.stdout)
        self.assertEqual((status, frame, policy), (200, 'DENY', DEVELOPMENT_CSP))

    def test_explicit_response_policy_is_not_overwritten(self):
        response = HttpResponse()
        response['Content-Security-Policy'] = "default-src 'none'"
        wrapped = ContentSecurityPolicyMiddleware(lambda request: response)
        self.assertEqual(wrapped(None)['Content-Security-Policy'], "default-src 'none'")
