"""Verify frame policy on early responses using real synthetic settings."""
import json
import os
import subprocess
import sys
from pathlib import Path

from django.http import HttpResponse
from django.test import SimpleTestCase
from django.urls import path
from django.views.decorators.clickjacking import xframe_options_exempt, xframe_options_sameorigin


@xframe_options_exempt
def exempt(request):
    return HttpResponse('synthetic')


@xframe_options_sameorigin
def explicit_sameorigin(request):
    return HttpResponse('synthetic')


# Test-only URL configuration for response-specific Django frame policies.
urlpatterns = [path('exempt/', exempt), path('sameorigin/', explicit_sameorigin)]

ROOT = Path(__file__).resolve().parent.parent
KEY = 'synthetic-only-not-a-real-key-0123456789-abcdefghijklm'


class NonDebugFrameGuardTests(SimpleTestCase):
    def run_script(self, debug, script):
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DJANGO_SETTINGS_MODULE='daroobank.settings', DAROOBANK_DEBUG=debug,
                   DAROOBANK_SECRET_KEY=KEY, DAROOBANK_ALLOWED_HOSTS='example.org',
                   POSTGRES_DB='synthetic', POSTGRES_USER='synthetic', POSTGRES_HOST='not-connected',
                   POSTGRES_PORT='5432')
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=env, timeout=15,
                                capture_output=True, text=True, check=True)
        self.assertNotIn(KEY, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_real_nondebug_settings_guard_early_and_normal_responses(self):
        script = ("import django,json; django.setup(); from django.test import Client; "
                  "c=Client(enforce_csrf_checks=True); h={'HTTP_HOST':'example.org'}; "
                  "responses=[c.get('/',secure=True,**h), c.get('/',**h), c.get('/staff/',secure=True,**h), "
                  "c.get('/staff/login/',secure=True,**h), c.get('/missing/',secure=True,**h), "
                  "c.post('/search/',{'q':'synthetic'},secure=True,**h), c.get('/search',secure=True,**h)]; "
                  "print(json.dumps([[r.status_code,r.get('X-Frame-Options')] for r in responses]))")
        self.assertEqual(self.run_script('0', script),
                         [[200, 'DENY'], [301, 'DENY'], [404, 'DENY'], [404, 'DENY'],
                          [404, 'DENY'], [403, 'DENY'], [301, 'DENY']])

    def test_explicit_view_exemption_and_policy_are_preserved(self):
        script = ("import django,json; django.setup(); from django.conf import settings; "
                  "settings.ROOT_URLCONF='daroobank.test_nondebug_frame_guard'; from django.test import Client; "
                  "c=Client(); responses=[c.get(p,secure=True,HTTP_HOST='example.org') "
                  "for p in ['/exempt/','/sameorigin/']]; "
                  "print(json.dumps([[r.status_code,r.get('X-Frame-Options')] for r in responses]))")
        self.assertEqual(self.run_script('0', script), [[200, None], [200, 'SAMEORIGIN']])

    def test_debug_preview_does_not_add_frame_header(self):
        script = ("import django,json; django.setup(); from django.test import Client; "
                  "r=Client().get('/',HTTP_HOST='example.org'); print(json.dumps([r.status_code,r.get('X-Frame-Options')]))")
        self.assertEqual(self.run_script('1', script), [200, None])
