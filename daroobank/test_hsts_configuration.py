"""Opt-in HSTS configuration; never evidence of deployed TLS."""
import json
import os
import subprocess
import sys
from ipaddress import ip_network
from pathlib import Path

from django.test import Client, SimpleTestCase, override_settings
from django.urls import reverse

ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_KEY = 'synthetic-only-not-a-real-key-0123456789-abcdefghijklm'


class HstsConfigurationTests(SimpleTestCase):
    def settings_process(self, value, debug='0'):
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DAROOBANK_DEBUG=debug, DAROOBANK_SECRET_KEY=SYNTHETIC_KEY,
                   DAROOBANK_ALLOWED_HOSTS='example.org', POSTGRES_DB='synthetic',
                   POSTGRES_USER='synthetic', POSTGRES_HOST='synthetic-no-server', POSTGRES_PORT='5432')
        if value is not None:
            env['DAROOBANK_HSTS_SECONDS'] = value
        script = ('import json; from daroobank import settings; print(json.dumps(['
                  'settings.SECURE_HSTS_SECONDS, settings.SECURE_HSTS_INCLUDE_SUBDOMAINS, settings.SECURE_HSTS_PRELOAD]))')
        return subprocess.run([sys.executable, '-c', script], env=env, cwd=ROOT, timeout=10,
                              capture_output=True, text=True)

    def test_default_off_and_exact_nonnegative_bound(self):
        for value, expected in ((None, 0), ('0', 0), ('60', 60), ('31536000', 31536000)):
            with self.subTest(value=value):
                result = self.settings_process(value)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), [expected, False, False])
        result = self.settings_process('not-a-number', debug='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), [0, False, False])

    def test_real_nondebug_settings_emit_only_on_https(self):
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DJANGO_SETTINGS_MODULE='daroobank.settings', DAROOBANK_DEBUG='0',
                   DAROOBANK_SECRET_KEY=SYNTHETIC_KEY, DAROOBANK_ALLOWED_HOSTS='example.org',
                   POSTGRES_DB='synthetic', POSTGRES_USER='synthetic', POSTGRES_HOST='synthetic-no-server',
                   POSTGRES_PORT='5432', DAROOBANK_HSTS_SECONDS='60')
        script = ("import django,json; django.setup(); from django.test import Client; c=Client(); "
                  "responses=[c.get('/', HTTP_HOST='example.org'), c.get('/', secure=True, HTTP_HOST='example.org')]; "
                  "print(json.dumps([[r.status_code, r.get('Strict-Transport-Security')] for r in responses]))")
        result = subprocess.run([sys.executable, '-c', script], env=env, cwd=ROOT, timeout=15,
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [[301, None], [200, 'max-age=60']])
        self.assertNotIn(SYNTHETIC_KEY, result.stdout + result.stderr)

    def test_invalid_opt_in_fails_closed_without_echo(self):
        for value in ('', '-1', '+5', ' 60', '60\n', '1.0', '١٠', '31536001', '9' * 5000):
            with self.subTest(value=value[:10]):
                result = self.settings_process(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('DAROOBANK_HSTS_SECONDS', result.stderr)
                if len(value) > 2:
                    self.assertNotIn(value, result.stdout + result.stderr)


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=True, SECURE_HSTS_SECONDS=60,
                   SECURE_HSTS_INCLUDE_SUBDOMAINS=False, SECURE_HSTS_PRELOAD=False,
                   SECURE_PROXY_SSL_HEADER=('HTTP_X_FORWARDED_PROTO', 'https'),
                   TRUSTED_PROXY_SCHEME_NETWORKS=(ip_network('192.0.2.0/24'),))
class HstsResponseTests(SimpleTestCase):
    def test_header_only_on_direct_or_trusted_https_not_untrusted_forwarding(self):
        client = Client()
        direct = client.get(reverse('home'), secure=True, REMOTE_ADDR='198.51.100.7')
        self.assertEqual(direct['Strict-Transport-Security'], 'max-age=60')
        trusted = client.get(reverse('home'), REMOTE_ADDR='192.0.2.8', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(trusted['Strict-Transport-Security'], 'max-age=60')
        untrusted = client.get(reverse('home'), REMOTE_ADDR='198.51.100.7', HTTP_X_FORWARDED_PROTO='https')
        self.assertEqual(untrusted.status_code, 301)
        self.assertNotIn('Strict-Transport-Security', untrusted)

    @override_settings(SECURE_HSTS_SECONDS=0)
    def test_no_header_by_default(self):
        response = Client().get(reverse('home'), secure=True)
        self.assertNotIn('Strict-Transport-Security', response)
