"""Complete response-header inventory for the staff surface; synthetic evidence.

The parity suites assert selected headers on denials. Nothing pinned the *whole*
header set, on successes as well as errors, so a response that quietly lost
`no-store`, gained a debugging header, or served a CSV attachment from an
unexpected route would have passed every existing test.

This suite sweeps all 43 `staff_*` routes with seven methods and four account
shapes and asserts:

* seven pinned headers with exact values on every response, whatever its status;
* no header outside a pinned inventory anywhere on the surface, and `Allow` only
  where a method was refused, with one of the five values ADR 0209 recorded;
* content types limited to HTML, except the two sample downloads, which are the
  only attachment responses and carry pinned synthetic filenames;
* no server error and no permanent redirect, and every temporary redirect goes to
  the staff login or, for logout, to the home page;
* nothing is written by the sweep.

It records current behavior under the synthetic test configuration. It is not a
header-policy review: `X-Frame-Options` is absent here because the clickjacking
middleware is inserted only in non-debug mode, which `test_nondebug_frame_guard.py`
covers separately.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .middleware import DEVELOPMENT_CSP
from .test_staff_authorization_matrix import ALL_PERMISSIONS, ROUTES, VIEW_PERMISSIONS
from .test_staff_authorization_objects import COUNTED_MODELS, build_object_rows
from .test_staff_method_sweep import EXPECTED_ALLOW, METHODS, send

PINNED_HEADERS = {
    'cache-control': 'private, no-store, max-age=0',
    'pragma': 'no-cache',
    'x-robots-tag': 'noindex, nofollow',
    'referrer-policy': 'same-origin',
    'x-content-type-options': 'nosniff',
    'cross-origin-opener-policy': 'same-origin',
    'content-security-policy': DEVELOPMENT_CSP,
}
# Headers whose presence is expected but whose value varies per response.
VARIABLE_HEADERS = frozenset({'content-length', 'content-type', 'date', 'expires', 'location', 'allow', 'set-cookie',
                              'vary', 'content-disposition'})
# ADR 0209 pinned the exact `Allow` value per route group; only those five strings
# may ever be advertised, and only where a method was actually refused.
ALLOW_VALUES = frozenset(EXPECTED_ALLOW.values())
SAMPLE_ROUTES = {'staff_product_sample': 'attachment; filename="product_candidates.synthetic.csv"',
                 'staff_price_sample': 'attachment; filename="price_candidates.synthetic.csv"'}
ALLOWED_STATUSES = frozenset({200, 302, 400, 403, 404, 405, 409})
SWEEP_METHODS = METHODS + ('POST',)


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffHeaderInventoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.outsider = User.objects.create_user('header-outsider', password='synthetic-only')
        cls.viewer = User.objects.create_user('header-view-staff', password='synthetic-only', is_staff=True)
        cls.viewer.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in VIEW_PERMISSIONS]))
        cls.full = User.objects.create_user('header-full-staff', password='synthetic-only', is_staff=True)
        cls.full.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        author = User.objects.create_user('header-author', password='synthetic-only', is_staff=True)
        author.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        cls.rows = build_object_rows(author)

    def all_routes(self):
        rows = self.rows
        real = {
            'staff_source_detail': {'pk': rows.claim.pk}, 'staff_source_review_inspection': {'pk': rows.claim.pk},
            'staff_source_review': {'pk': rows.claim.pk}, 'staff_product_detail': {'pk': rows.candidate.pk},
            'staff_product_review_inspection': {'pk': rows.candidate.pk},
            'staff_product_review': {'pk': rows.candidate.pk}, 'staff_price_detail': {'pk': rows.price.pk},
            'staff_price_review_inspection': {'pk': rows.price.pk}, 'staff_price_review': {'pk': rows.price.pk},
            'staff_clinical_detail': {'pk': rows.draft.pk}, 'staff_clinical_review_inspection': {'pk': rows.draft.pk},
            'staff_clinical_lineage': {'pk': rows.draft.pk}, 'staff_clinical_revise': {'pk': rows.draft.pk},
            'staff_clinical_reference_create': {'pk': rows.draft.pk}, 'staff_clinical_review': {'pk': rows.draft.pk},
            'staff_identity_detail': {'kind': 'package', 'pk': rows.package.pk},
            'staff_identity_lineage': {'kind': 'package', 'pk': rows.package.pk},
            'staff_identity_create': {'kind': 'ingredient'}, 'staff_identity_revise': {'pk': rows.package.pk},
            'staff_identity_revise_component': {'kind': 'ingredient', 'pk': rows.ingredient.pk},
            'staff_identity_review': {'pk': rows.package.pk},
            'staff_catalog_quality_irc': {'pk': rows.presentation.pk},
            'staff_import_receipt_detail': {'pk': rows.receipt.pk},
            'staff_import_manifest_inspection': {'pk': rows.receipt.pk},
        }
        for name, kwargs, _method, _requirement in ROUTES:
            yield name, real.get(name, kwargs)
        yield 'staff_login', {}
        yield 'staff_logout', {}

    def sweep(self):
        for name, kwargs in self.all_routes():
            url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
            for account in (None, self.outsider, self.viewer, self.full):
                client = Client()
                if account is not None:
                    client.force_login(account)
                for method in SWEEP_METHODS:
                    yield name, method, account, send(client, url, method)

    def counts(self):
        return {model: model.objects.count() for model in COUNTED_MODELS}

    def test_every_response_carries_the_pinned_private_headers(self):
        checked = 0
        for name, method, account, response in self.sweep():
            headers = {key.lower(): value for key, value in response.headers.items()}
            for header, expected in PINNED_HEADERS.items():
                with self.subTest(route=name, method=method, header=header,
                                  account='anonymous' if account is None else account.username):
                    self.assertEqual(headers.get(header), expected)
            checked += 1
        self.assertEqual(checked, 43 * 4 * len(SWEEP_METHODS))

    def test_no_response_carries_a_header_outside_the_inventory(self):
        seen = {}
        for name, method, _account, response in self.sweep():
            for key in response.headers:
                seen.setdefault(key.lower(), set()).add(name)
        unexpected = set(seen) - set(PINNED_HEADERS) - VARIABLE_HEADERS
        self.assertEqual(unexpected, set(), f'Unexpected response headers: {sorted(unexpected)}')
        # The inventory is not vacuous: the sweep really produced these headers,
        # and every header it produced belongs to a known route.
        self.assertEqual(set(PINNED_HEADERS), set(seen) & set(PINNED_HEADERS))
        known = {name for name, _kwargs in self.all_routes()}
        self.assertIn('vary', seen)
        for header, names in seen.items():
            with self.subTest(header=header):
                self.assertTrue(names <= known, f'{header} appeared on an unknown route: {sorted(names - known)}')

    def test_allow_appears_only_where_a_method_was_refused(self):
        placements = {}
        for name, _method, _account, response in self.sweep():
            if 'Allow' not in response:
                continue
            value = response['Allow']
            with self.subTest(route=name, status=response.status_code):
                self.assertIn(value, ALLOW_VALUES, f'{name} advertised an unknown Allow value: {value!r}')
            placements.setdefault(response.status_code, set()).add(name)
        self.assertEqual(set(placements), {405, 200},
                         f'Allow must appear only on a refused method or an OPTIONS answer: {sorted(placements)}')
        # Only the two class-based endpoints answer OPTIONS with a 200.
        self.assertEqual(placements[200], {'staff_login', 'staff_logout'})
        known = {name for name, _kwargs in self.all_routes()}
        self.assertEqual(placements[405], known, 'Every staff route must refuse at least one swept method.')

    def test_content_types_are_html_except_the_two_sample_downloads(self):
        rendered = {}
        other = set()
        dispositions = {}
        for name, _method, _account, response in self.sweep():
            if response.status_code == 200:
                rendered.setdefault(name, set()).add(response['Content-Type'])
            else:
                other.add(response['Content-Type'])
            if 'Content-Disposition' in response:
                dispositions.setdefault(name, set()).add(response['Content-Disposition'])
        for name, values in rendered.items():
            with self.subTest(route=name):
                if name in SAMPLE_ROUTES:
                    self.assertEqual(values, {'text/csv; charset=utf-8'})
                else:
                    self.assertEqual(values, {'text/html; charset=utf-8'})
        # Redirects and errors are HTML, never a document type.
        self.assertEqual(other, {'text/html; charset=utf-8'})
        self.assertEqual(dispositions, {name: {value} for name, value in SAMPLE_ROUTES.items()})
        self.assertEqual(set(rendered) & set(SAMPLE_ROUTES), set(SAMPLE_ROUTES),
                         'Both sample downloads must really render for an authorized account.')

    def test_no_server_error_and_every_redirect_goes_to_login_or_home(self):
        login = reverse('staff_login')
        statuses = set()
        for name, method, account, response in self.sweep():
            statuses.add(response.status_code)
            with self.subTest(route=name, method=method,
                              account='anonymous' if account is None else account.username):
                self.assertIn(response.status_code, ALLOWED_STATUSES)
                if response.status_code == 302:
                    location = response['Location']
                    self.assertTrue(location.startswith(login) or location.endswith(reverse('home')),
                                    location)
                    self.assertNotIn('://', location.split('/staff/', 1)[-1],
                                     'A redirect target must stay on this host.')
        self.assertTrue(statuses <= ALLOWED_STATUSES)
        self.assertIn(200, statuses, 'The sweep must reach real content, not only errors.')
        self.assertIn(403, statuses)
        self.assertIn(405, statuses)

    def test_the_sweep_writes_nothing(self):
        before = self.counts()
        for _name, _method, _account, _response in self.sweep():
            pass
        self.assertEqual(self.counts(), before)
