"""Abuse protection is external: what the application itself limits, and what it does not.

`docs/SECURITY.md` lists rate limits among the controls this product is supposed
to have, and its upload section says the application's size check happens after Django has
received the request. Neither statement was measured, and the difference between "the platform
will protect this" and "nothing here protects this" is exactly what an operator has to know
before a public deployment.

What is true today:

* two limiters exist and both are opt-in and off by default. The staff login limiter (ADR 0181)
  is debug-only, has one call site, refuses with a `429` that names no retry delay, and answers
  `503` when the counter is unavailable. The public read limiter (ADR 0228) is one middleware
  above the session layer, counts reads per keyed client, refuses with a `429` and a
  `Retry-After`, and serves the read when the counter is unavailable;
* with both limiters off, which is the default and what every test environment sets, nothing
  limits any public request — 48 sequential anonymous reads of the catalog, the search page and
  the search API all answer 200 with no rate-limit header and write nothing;
* no request-size ceiling is configured: `DATA_UPLOAD_MAX_MEMORY_SIZE` and
  `FILE_UPLOAD_MAX_MEMORY_SIZE` are Django's defaults and `settings.py` sets neither, no project
  module mentions 413, and the upload limits that do exist (1 MiB for product intake, 2 MiB for
  price staging) are `upload.size` checks in a form, so they run after Django has spooled the
  body.

The suite pins that shape so that adding abuse protection — or quietly removing the login limiter
— is a documented event, and so that the deployment guide keeps assigning the rest to the
operator. It does not judge whether the current limits are right, and it cannot see a proxy, a
CDN, a firewall or a host-level control.
"""
import ast
import io
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from unittest import mock

from catalog.intake import MAX_FILE_BYTES as PRODUCT_LIMIT
from daroobank.test_no_read_audit import MIDDLEWARE, project_models
from pricing.importer import MAX_FILE_BYTES as PRICE_LIMIT
from pricing.models import PriceCandidate

ROOT = Path(__file__).resolve().parent.parent
PROJECT_DIRS = ('catalog', 'clinical', 'daroobank', 'ingestion', 'pricing', 'sources',
                'staff_security', 'tools')
LIMITER_WORDS = ('ratelimit', 'rate_limit', 'throttle', 'limit')
PUBLIC_READS = (
    ('home', {}),
    ('about', {}),
    ('prices', {}),
    ('search', {'q': 'synthetic'}),
    ('search_api', {'q': 'synthetic'}),
    ('openapi_document', {}),
)
RATE_HEADERS = ('retry-after', 'x-ratelimit', 'x-rate-limit', 'ratelimit')
READS_PER_ROUTE = 8


def source_modules():
    files = [ROOT / 'manage.py']
    files += [path for name in PROJECT_DIRS for path in sorted((ROOT / name).rglob('*.py'))
              if 'test' not in path.name and 'migrations' not in path.parts]
    return sorted(files)


def modules_containing(literal):
    return sorted(str(path.relative_to(ROOT)) for path in source_modules()
                  if literal in path.read_text(encoding='utf-8'))


def modules_importing(module_name):
    found = []
    for path in source_modules():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            elif isinstance(node, ast.ImportFrom) and node.level and node.names:
                names = [f'{"." * node.level}{alias.name}' for alias in node.names]
            if any(name == module_name or name.endswith(module_name) for name in names):
                found.append(str(path.relative_to(ROOT)))
                break
    return sorted(found)


def limiter_class_names():
    names = []
    for path in source_modules():
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.ClassDef) and any(word in node.name.lower() for word in LIMITER_WORDS):
                names.append(f'{path.relative_to(ROOT)}:{node.name}')
    return sorted(names)


class AbuseProtectionShapeTests(SimpleTestCase):
    def test_rate_refusals_come_from_exactly_the_two_opt_in_limiters(self):
        self.assertFalse(settings.STAFF_LOGIN_THROTTLE_ENABLED,
                         'the synthetic environment enabled the login limiter')
        self.assertFalse(settings.PUBLIC_READ_LIMIT_ENABLED,
                         'the synthetic environment enabled the read limiter')
        self.assertEqual(modules_containing('429'), ['daroobank/middleware.py', 'pricing/staff_views.py'],
                         'a third place now refuses requests by rate')
        self.assertEqual(modules_containing('Retry-After'), ['daroobank/middleware.py'],
                         'the read limiter tells a client when to retry and the login refusal still does not')
        self.assertEqual(modules_importing('staff_security.throttle'), ['pricing/staff_views.py'],
                         'the login limiter is now applied somewhere else')
        self.assertEqual(modules_importing('staff_security.read_limit'), ['daroobank/middleware.py'],
                         'the read limiter is now applied somewhere else')
        self.assertEqual(limiter_class_names(), ['daroobank/middleware.py:PublicReadLimitMiddleware'],
                         'a limiter class appeared outside the two opt-in ones')

    def test_the_only_limiting_middleware_is_the_opt_in_read_limiter(self):
        self.assertEqual(tuple(settings.MIDDLEWARE), MIDDLEWARE)
        limiting = [entry for entry in MIDDLEWARE
                    if any(word in entry.lower() for word in LIMITER_WORDS)]
        self.assertEqual(limiting, ['daroobank.middleware.PublicReadLimitMiddleware'],
                         'a middleware entry other than the opt-in read limiter can limit a request')

    def test_no_request_size_ceiling_is_configured(self):
        text = (ROOT / 'daroobank' / 'settings.py').read_text(encoding='utf-8')
        for name in ('DATA_UPLOAD_MAX_MEMORY_SIZE', 'FILE_UPLOAD_MAX_MEMORY_SIZE'):
            with self.subTest(setting=name):
                self.assertNotIn(name, text, 'settings.py now configures a request-size ceiling')
                self.assertEqual(getattr(settings, name), 2621440,
                                 'Django changed its default, so the documented ceiling changed')
        self.assertEqual(modules_containing('413'), [], 'a module now answers 413')
        self.assertEqual(PRODUCT_LIMIT, 1024 * 1024)
        self.assertEqual(PRICE_LIMIT, 2 * 1024 * 1024)
        # The upload limits are size checks on a spooled upload, so they run after receipt.
        form = (ROOT / 'pricing' / 'forms.py').read_text(encoding='utf-8')
        self.assertIn('upload.size > MAX_FILE_BYTES', form)
        intake = (ROOT / 'catalog' / 'staff_forms.py').read_text(encoding='utf-8')
        self.assertIn('file.size > MAX_FILE_BYTES', intake)


class PublicReadRateTests(TestCase):
    def test_public_reads_are_unlimited_and_write_nothing_while_both_limiters_are_off(self):
        # The default configuration, and what the synthetic environment sets: with the read
        # limiter off, a repeated anonymous read is counted nowhere and refused for no reason.
        self.assertFalse(settings.PUBLIC_READ_LIMIT_ENABLED)
        self.assertFalse(settings.STAFF_LOGIN_THROTTLE_ENABLED)
        before = {label: model.objects.count() for label, model in sorted(project_models().items())}
        seen = 0
        for name, query in PUBLIC_READS:
            url = reverse(name)
            for _ in range(READS_PER_ROUTE):
                response = self.client.get(url, query)
                seen += 1
                with self.subTest(route=name):
                    self.assertEqual(response.status_code, 200,
                                 'a repeated public read was refused or did not resolve')
                    lowered = {header.lower() for header in response.headers}
                    self.assertEqual([header for header in lowered
                                      if any(word in header for word in RATE_HEADERS)], [],
                                     'a public response now carries a rate-limit header')
                    self.assertIn('content-security-policy', lowered,
                                  'the header inspection has nothing to see, so it proves nothing')
        self.assertEqual(seen, len(PUBLIC_READS) * READS_PER_ROUTE)
        self.assertEqual({label: model.objects.count() for label, model in sorted(project_models().items())},
                         before, 'repeated public reads wrote a row')


class LoginLimiterTests(TestCase):
    def post_login(self):
        return self.client.post(reverse('staff_login'), {'username': 'nobody', 'password': 'wrong-passphrase'})

    @override_settings(STAFF_LOGIN_THROTTLE_ENABLED=True)
    def test_a_limited_login_is_refused_with_429_and_no_retry_after(self):
        with mock.patch('staff_security.throttle.consume_attempt', return_value='limited'):
            response = self.post_login()
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.headers['Content-Type'], 'text/plain; charset=utf-8')
        self.assertEqual([header for header in response.headers
                          if any(word in header.lower() for word in RATE_HEADERS)], [],
                         'a 429 that names no retry delay leaves a client to guess')
        self.assertNotIn('csrfmiddlewaretoken', response.content.decode('utf-8'))

    @override_settings(STAFF_LOGIN_THROTTLE_ENABLED=True)
    def test_an_unavailable_limiter_fails_closed_with_503(self):
        with mock.patch('staff_security.throttle.consume_attempt', return_value='unavailable'):
            response = self.post_login()
        self.assertEqual(response.status_code, 503)
        self.assertEqual([header for header in response.headers
                          if any(word in header.lower() for word in RATE_HEADERS)], [])

    @override_settings(STAFF_LOGIN_THROTTLE_ENABLED=True)
    def test_an_allowed_attempt_reaches_the_login_form(self):
        with mock.patch('staff_security.throttle.consume_attempt', return_value='allowed') as consume:
            response = self.post_login()
        self.assertEqual(consume.call_count, 1)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'csrfmiddlewaretoken')

    def test_the_limiter_is_not_consulted_when_it_is_disabled(self):
        with mock.patch('staff_security.throttle.consume_attempt') as consume:
            response = self.post_login()
        self.assertEqual(consume.call_count, 0, 'the limiter ran outside a debug environment')
        self.assertEqual(response.status_code, 200)


class OversizedUploadTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        stager = get_user_model().objects.create_user('upload-stager', password='synthetic-only',
                                                      is_staff=True)
        stager.user_permissions.add(*Permission.objects.filter(
            codename__in=('view_pricecandidate', 'add_pricecandidate'),
            content_type__app_label='pricing'))
        cls.stager = stager

    def test_an_oversized_upload_is_refused_by_the_form_not_by_a_ceiling(self):
        self.client.force_login(self.stager)
        payload = b'source_record_id,irc\n' + b'x' * (PRICE_LIMIT + 1024)
        response = self.client.post(reverse('staff_price_upload'), {
            'source_name': 'منبع ساختگی', 'source_url': 'https://example.org/feed', 'action': 'stage',
            'rights_attested': 'on',
            'csv_file': SimpleUploadedFile('oversized.csv', io.BytesIO(payload).read(),
                                           content_type='text/csv'),
        })
        self.assertEqual(response.status_code, 200, 'the application answered with a transport-level refusal')
        self.assertIn('csv_file', response.context['form'].errors)
        self.assertEqual(PriceCandidate.objects.count(), 0)
        self.assertEqual([header for header in response.headers
                          if any(word in header.lower() for word in RATE_HEADERS)], [])


class AbuseProtectionDocumentationTests(SimpleTestCase):
    def test_the_deployment_guide_assigns_abuse_protection_to_the_operator(self):
        text = (ROOT / 'docs' / 'DEPLOYMENT.md').read_text(encoding='utf-8')
        for topic in ('rate limit', 'request size'):
            with self.subTest(topic=topic):
                self.assertIn(topic, text,
                              'the deployment guide no longer says who limits request rate and size')
        self.assertIn('no rate limit', text,
                      'the deployment guide should say plainly that the application has none')
