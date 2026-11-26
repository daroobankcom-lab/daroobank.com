"""Fail-closed configuration checks; synthetic values are never real secrets."""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from .configuration import require_nondebug_hosts, require_nondebug_secret

ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_KEY = 'synthetic-only-not-a-real-key-0123456789-abcdefghijklm'


class NonDebugConfigurationTests(SimpleTestCase):
    def run_settings(self, *, debug='0', key=SYNTHETIC_KEY, hosts='example.org'):
        env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG') if k in os.environ}
        env.update(DAROOBANK_DEBUG=debug, POSTGRES_DB='synthetic', POSTGRES_USER='synthetic',
                   POSTGRES_HOST='synthetic-no-server', POSTGRES_PORT='5432')
        if key is not None:
            env['DAROOBANK_SECRET_KEY'] = key
        if hosts is not None:
            env['DAROOBANK_ALLOWED_HOSTS'] = hosts
        script = ('import json; from daroobank.settings import ALLOWED_HOSTS, DEBUG; '
                  'print(json.dumps({"debug": DEBUG, "hosts": ALLOWED_HOSTS}))')
        return subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env, timeout=10,
                              capture_output=True, text=True, check=False)

    def test_nondebug_rejects_missing_weak_and_nonprintable_secrets_without_echo(self):
        for key in (None, '', 'development-only-not-for-production', 'x' * 60,
                    'aB12!' * 9, 'aB12!' * 11 + '\n', 'django-insecure-' + 'aB12!' * 11):
            with self.subTest(kind='missing' if key is None else 'synthetic-weak'):
                result = self.run_settings(key=key)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(key or 'never-present', result.stdout + result.stderr)
                self.assertIn('DAROOBANK_SECRET_KEY', result.stderr)

    def test_direct_validators_reject_non_strings_and_unicode_controls(self):
        for value in (None, 5, True, b'abc', 'aB12!' * 11 + '\ud800', 'aB12!' * 11 + ' '):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(ImproperlyConfigured):
                    require_nondebug_secret(value)
        for value in (None, 5, True, b'example.org', 'xn--example.org\u200b', 'example.org\x00'):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaises(ImproperlyConfigured):
                    require_nondebug_hosts(value)

    def test_nondebug_requires_explicit_narrow_well_formed_hosts(self):
        for hosts in (None, '', ' , ', '*', 'example.org,*', 'https://example.org',
                      'example.org:443', '.','..example.org', 'example.org/', 'example.org\n',
                      '-bad.example', 'bad-.example', '[not-an-ipv6]'):
            with self.subTest(hosts=repr(hosts)):
                result = self.run_settings(hosts=hosts)
                self.assertNotEqual(result.returncode, 0, hosts)
                self.assertIn('DAROOBANK_ALLOWED_HOSTS', result.stderr)

    def test_valid_explicit_hosts_and_generated_shape_start_without_db_access(self):
        for hosts in ('example.org', '.example.org,api.example.org', 'localhost,127.0.0.1',
                      '[::1]', 'xn--mgbh0fb.example'):
            with self.subTest(hosts=hosts):
                result = self.run_settings(hosts=hosts)
                self.assertEqual(result.returncode, 0, result.stderr)
                parsed = json.loads(result.stdout)
                self.assertFalse(parsed['debug'])
                self.assertEqual(parsed['hosts'], hosts.split(','))
                self.assertNotIn(SYNTHETIC_KEY, result.stdout + result.stderr)

    def test_configured_host_boundary_is_enforced_by_django(self):
        env = {k: os.environ[k] for k in ('PATH', 'HOME', 'LANG') if k in os.environ}
        env.update(DJANGO_SETTINGS_MODULE='daroobank.settings', DAROOBANK_DEBUG='0',
                   DAROOBANK_SECRET_KEY=SYNTHETIC_KEY, DAROOBANK_ALLOWED_HOSTS='.example.org',
                   POSTGRES_DB='synthetic', POSTGRES_USER='synthetic', POSTGRES_HOST='synthetic-no-server',
                   POSTGRES_PORT='5432')
        script = ("import django,json; django.setup(); from django.test import Client; c=Client(); "
                  "print(json.dumps([c.get('/', secure=True, HTTP_HOST=h).status_code for h in "
                  "['example.org','www.example.org','evil-example.org','attacker.example']]))")
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env, timeout=15,
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [200, 200, 400, 400])
        self.assertNotIn(SYNTHETIC_KEY, result.stdout + result.stderr)

    def test_debug_defaults_remain_local_and_allow_existing_preview(self):
        result = self.run_settings(debug='1', key=None, hosts=None)
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout)
        self.assertTrue(parsed['debug'])
        self.assertIn('localhost', parsed['hosts'])
        self.assertIn('.e2b.app', parsed['hosts'])
