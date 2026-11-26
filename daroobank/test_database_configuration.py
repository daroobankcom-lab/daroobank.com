"""Database configuration errors must not disclose environment values."""
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent


class DatabaseConfigurationTests(SimpleTestCase):
    def run_settings(self, **changes):
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DAROOBANK_DEBUG='1', POSTGRES_DB='synthetic', POSTGRES_USER='synthetic',
                   POSTGRES_HOST='no-database-needed', POSTGRES_PORT='5432')
        env.update(changes)
        return subprocess.run([sys.executable, '-c',
                               'import json; from daroobank.settings import DATABASES; '
                               'print(json.dumps([DATABASES["default"]["PORT"], '
                               'DATABASES["default"]["CONN_MAX_AGE"]]))'],
                              cwd=ROOT, env=env, capture_output=True, text=True, timeout=10)

    def test_nonnumeric_values_fail_without_echo_or_chained_exception(self):
        for name in ('POSTGRES_PORT', 'POSTGRES_CONN_MAX_AGE'):
            with self.subTest(name=name):
                canary = 'synthetic-sensitive-config-canary-' + name
                result = self.run_settings(**{name: canary})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Invalid PostgreSQL port or connection lifetime', result.stderr)
                self.assertNotIn(canary, result.stdout + result.stderr)
                self.assertNotIn('During handling of the above exception', result.stderr)

    def test_valid_and_out_of_range_values(self):
        result = self.run_settings(POSTGRES_PORT='55432', POSTGRES_CONN_MAX_AGE='20')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '[55432, 20]')
        result = self.run_settings(POSTGRES_CONN_MAX_AGE='31536000')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), '[5432, 31536000]')
        for changes in ({'POSTGRES_PORT': '0'}, {'POSTGRES_PORT': '65536'},
                        {'POSTGRES_CONN_MAX_AGE': '-1'}, {'POSTGRES_CONN_MAX_AGE': '31536001'},
                        {'POSTGRES_CONN_MAX_AGE': '9' * 1000}):
            with self.subTest(setting=next(iter(changes)), length=len(next(iter(changes.values())))):
                result = self.run_settings(**changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Invalid PostgreSQL port or connection lifetime', result.stderr)
