"""Denial parity for staff object routes; synthetic evidence, not a review.

ADR 0201 compares only status codes, and says so: an unauthorized account gets
403 whether or not the row exists. That leaves open whether the *response* differs
— a longer body, a different header, an error message naming the object — which
would still turn the route into an existence oracle. This suite closes that gap by
comparing whole responses.

For every object route and every unauthorized account shape it asserts that the
response for an existing row is byte-identical to the response for a missing
primary key, in status, body and headers, and that the denial is also identical
across account shapes, so the reason for the denial cannot be read back either.

Timing is deliberately **not** compared: wall-clock differences in a test process
measure the harness, not the application, and asserting on them would produce a
flaky test that looks like a security guarantee. A real timing channel would need
a measurement setup this suite does not provide.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from .test_staff_authorization_matrix import ALL_PERMISSIONS, ROUTES, VIEW_PERMISSIONS, satisfies
from .test_staff_authorization_objects import COUNTED_MODELS, OBJECT_ROUTES, build_object_rows

MISSING_PK = 999_999_999
# Headers that legitimately differ between two requests for reasons unrelated to
# authorization: the session cookie is rotated per login and the date moves.
# `Date` and `Set-Cookie` differ per response. `Expires` differs per *second* on the
# two class-based auth endpoints, whose views are wrapped in `never_cache`; the 41
# function-view routes never emit it. Comparing it made every parity assertion that
# included logout timing-dependent, which failed in CI and passed locally (ADR 0212).
VOLATILE_HEADERS = frozenset({'date', 'set-cookie', 'expires'})


def missing_kwargs(name, existing):
    return {'kind': existing['kind'], 'pk': MISSING_PK} if 'kind' in existing else {'pk': MISSING_PK}


def comparable(response):
    headers = {key.lower(): value for key, value in response.items() if key.lower() not in VOLATILE_HEADERS}
    return response.status_code, response.content, tuple(sorted(headers.items()))


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffDenialParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.outsider = User.objects.create_user('parity-outsider', password='synthetic-only')
        cls.bare = User.objects.create_user('parity-bare-staff', password='synthetic-only', is_staff=True)
        cls.viewer = User.objects.create_user('parity-view-staff', password='synthetic-only', is_staff=True)
        cls.viewer.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in VIEW_PERMISSIONS]))
        cls.full = User.objects.create_user('parity-full-staff', password='synthetic-only', is_staff=True)
        cls.full.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        author = User.objects.create_user('parity-author', password='synthetic-only', is_staff=True)
        author.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        cls.rows = build_object_rows(author)

    def object_routes(self):
        objects = OBJECT_ROUTES
        for name, _kwargs, method, requirement in ROUTES:
            if name not in objects:
                continue
            yield name, method, requirement

    def kwargs_for(self, name):
        rows = self.rows
        table = {
            'staff_source_detail': rows.claim, 'staff_source_review_inspection': rows.claim,
            'staff_source_review': rows.claim, 'staff_product_detail': rows.candidate,
            'staff_product_review_inspection': rows.candidate, 'staff_product_review': rows.candidate,
            'staff_price_detail': rows.price, 'staff_price_review_inspection': rows.price,
            'staff_price_review': rows.price, 'staff_clinical_detail': rows.draft,
            'staff_clinical_review_inspection': rows.draft, 'staff_clinical_lineage': rows.draft,
            'staff_clinical_revise': rows.draft, 'staff_clinical_reference_create': rows.draft,
            'staff_clinical_review': rows.draft, 'staff_identity_detail': rows.package,
            'staff_identity_lineage': rows.package, 'staff_identity_revise_component': rows.ingredient,
            'staff_identity_revise': rows.package, 'staff_identity_review': rows.package,
            'staff_catalog_quality_irc': rows.presentation, 'staff_import_receipt_detail': rows.receipt,
            'staff_import_manifest_inspection': rows.receipt,
        }
        row = table[name]
        kwargs = {'pk': row.pk}
        if name in ('staff_identity_detail', 'staff_identity_lineage'):
            kwargs['kind'] = 'package'
        if name == 'staff_identity_revise_component':
            kwargs['kind'] = 'ingredient'
        return kwargs

    def request(self, account, url, method):
        client = self.client_class()
        if account is not None:
            client.force_login(account)
        return client.get(url) if method == 'GET' else client.post(url, {})

    def counts(self):
        return {model: model.objects.count() for model in COUNTED_MODELS}

    def test_the_row_set_is_the_one_the_parity_checks_compare(self):
        self.assertEqual(len(OBJECT_ROUTES), 23)
        self.assertEqual(len(list(self.object_routes())), 23)
        for name, _method, _requirement in self.object_routes():
            with self.subTest(route=name):
                self.assertTrue(reverse(name, kwargs=self.kwargs_for(name)))

    def test_denials_are_identical_whether_or_not_the_row_exists(self):
        for account in (self.outsider, self.bare, self.viewer):
            for name, method, requirement in self.object_routes():
                if satisfies(account, requirement):
                    continue
                with self.subTest(account=account.username, route=name):
                    existing = self.kwargs_for(name)
                    present = comparable(self.request(account, reverse(name, kwargs=existing), method))
                    absent = comparable(self.request(account, reverse(name, kwargs=missing_kwargs(name, existing)),
                                                      method))
                    self.assertEqual(present[0], 403, 'A denial must be a 403, not a 404 or content.')
                    self.assertEqual(present, absent,
                                     'The response for an existing row differs from the missing-row response, '
                                     'so the route leaks existence.')

    def test_the_denial_reason_is_not_distinguishable_across_account_shapes(self):
        for name, method, requirement in self.object_routes():
            denials = []
            for account in (self.outsider, self.bare, self.viewer):
                if satisfies(account, requirement):
                    continue
                denials.append((account.username, comparable(self.request(account, reverse(
                    name, kwargs=self.kwargs_for(name)), method))))
            self.assertGreaterEqual(len(denials), 2, 'Parity across shapes needs at least two denied shapes.')
            with self.subTest(route=name):
                self.assertEqual({item[1] for item in denials}, {denials[0][1]},
                                 'A non-staff account, a staff account without permissions and a staff '
                                 'account with other permissions must be indistinguishable.')

    def test_denials_carry_the_staff_privacy_headers(self):
        for account in (self.outsider, self.bare, self.viewer):
            for name, method, requirement in self.object_routes():
                if satisfies(account, requirement):
                    continue
                with self.subTest(account=account.username, route=name):
                    response = self.request(account, reverse(name, kwargs=self.kwargs_for(name)), method)
                    self.assertEqual(response.status_code, 403)
                    self.assertIn('no-store', response['Cache-Control'])
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                    self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_authorized_accounts_are_not_denied_for_the_same_rows(self):
        # Parity assertions are only meaningful if the authorized path differs.
        for name, method, requirement in self.object_routes():
            with self.subTest(route=name):
                response = self.request(self.full, reverse(name, kwargs=self.kwargs_for(name)), method)
                self.assertNotEqual(response.status_code, 403)
                self.assertEqual(response.status_code, 200 if method == 'GET' else 400)

    def test_comparing_every_route_twice_writes_nothing(self):
        before = self.counts()
        for account in (self.outsider, self.bare, self.viewer, self.full):
            for name, method, _requirement in self.object_routes():
                existing = self.kwargs_for(name)
                self.request(account, reverse(name, kwargs=existing), method)
                self.request(account, reverse(name, kwargs=missing_kwargs(name, existing)), method)
        self.assertEqual(self.counts(), before)
