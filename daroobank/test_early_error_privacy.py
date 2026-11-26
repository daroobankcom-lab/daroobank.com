"""Known staff/public paths retain privacy headers on selected early errors."""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent


class EarlyErrorPrivacyTests(SimpleTestCase):
    def test_invalid_host_before_redirect_has_known_path_privacy(self):
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DJANGO_SETTINGS_MODULE='daroobank.settings', DAROOBANK_DEBUG='0',
                   DAROOBANK_SECRET_KEY='synthetic-only-not-a-real-key-0123456789-abcdefghijklm',
                   DAROOBANK_ALLOWED_HOSTS='example.org', POSTGRES_DB='synthetic',
                   POSTGRES_USER='synthetic', POSTGRES_HOST='not-connected', POSTGRES_PORT='5432')
        script = ("import django,json; django.setup(); from django.test import Client; c=Client(); "
                  "responses=[c.get(p,HTTP_HOST='badhost.invalid') for p in ['/staff/login/','/staff/missing/',"
                  "'/search/','/api/v1/search/','/products/1/','/about/']]; "
                  "print(json.dumps([[r.status_code,r.get('Cache-Control'),r.get('Referrer-Policy'),"
                  "r.get('X-Robots-Tag')] for r in responses]))")
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env, timeout=15,
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), [
            [400, 'private, no-store, max-age=0', 'same-origin', 'noindex, nofollow'],
            [400, 'private, no-store, max-age=0', 'same-origin', 'noindex, nofollow'],
            [400, 'no-store', 'no-referrer', 'noindex, follow'],
            [400, 'no-store', 'no-referrer', 'noindex, follow'],
            [400, 'no-store', 'no-referrer', 'noindex, follow'],
            [400, None, None, None],
        ])
