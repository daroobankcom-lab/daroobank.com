"""Query-parameter parity on staff routes; synthetic evidence, not a review.

ADR 0204–0205 compared denials across identifier shapes and methods. Query
parameters are the remaining caller-controlled input on these routes: filters,
pagination cursors, scan offsets and date-window arguments. This suite asks three
questions of all 41 staff routes:

* can a query parameter change what an unauthorized account receives? It must not —
  every variant has to produce the identical 403;
* can a query parameter make an authorized request fail with a server error? No
  variant may produce a 500, and every response keeps the staff privacy headers;
* can a filter widen what an account sees beyond its own kind? A product-only
  account must not receive price-receipt content through ``?kind=price``.

It records current behavior on a development-only portal with synthetic data. It is
not an authorization review, not fuzzing, and timing is not compared.
"""
import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from .test_staff_authorization_matrix import ALL_PERMISSIONS, ROUTES, VIEW_PERMISSIONS, satisfies
from catalog.test_intake import make_csv
from pricing.test_workflow import csv_bytes

from .test_staff_authorization_objects import (COUNTED_MODELS, PRICE_ROW, PRODUCT_ROW, build_object_rows)
from .test_staff_denial_parity import comparable

# Nine caller-controlled query shapes: the empty case, both legitimate receipt
# kinds, an HTML-injection attempt, out-of-range and absurd pagination, a
# non-numeric scan offset with a NUL category, an oversized search term, and
# malformed date-window arguments.
QUERY_VARIANTS = (
    {},
    {'kind': 'product'},
    {'kind': 'price'},
    {'kind': '<script>alert(1)</script>'},
    {'page': '-1'},
    {'page': '99999999999999999999'},
    {'after': 'abc', 'category': '\x00'},
    {'q': 'x' * 5000},
    {'at': 'not-a-date', 'days': '-3'},
)
ALLOWED_STATUSES = frozenset({200, 302, 400, 404, 405, 409})
# One receipt per kind, each with a distinct source name and URL, so a cross-kind
# leak would be visible in both the list (which renders the name) and the detail
# page (which renders the URL).
PRODUCT_NAME = 'منبع رسید فرآورده ساختگی'
PRODUCT_MARKER = 'https://example.org/query-parity-product'
PRICE_NAME = 'منبع رسید قیمت ساختگی'
PRICE_MARKER = 'https://example.org/query-parity-price'
# The only route whose answer may legitimately depend on a query parameter is the
# receipt list, where `kind=price` is outside a product-only account's scope.
KIND_FILTER_ROUTE = 'staff_import_receipts'


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffQueryParityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.outsider = User.objects.create_user('query-outsider', password='synthetic-only')
        cls.bare = User.objects.create_user('query-bare-staff', password='synthetic-only', is_staff=True)
        cls.viewer = User.objects.create_user('query-view-staff', password='synthetic-only', is_staff=True)
        cls.viewer.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in VIEW_PERMISSIONS]))
        cls.product_only = User.objects.create_user('query-product-staff', password='synthetic-only', is_staff=True)
        cls.product_only.user_permissions.add(
            *Permission.objects.filter(codename__in=['view_productcandidate', 'add_productcandidate']))
        cls.full = User.objects.create_user('query-full-staff', password='synthetic-only', is_staff=True)
        cls.full.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        author = User.objects.create_user('query-author', password='synthetic-only', is_staff=True)
        author.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        cls.rows = build_object_rows(author)
        from ingestion.receipts import stage_price_with_receipt, stage_product_with_receipt
        _counts, cls.product_receipt = stage_product_with_receipt(
            io.BytesIO(make_csv([dict(PRODUCT_ROW, source_record_id='query-parity-product')])), PRODUCT_NAME,
            PRODUCT_MARKER, actor=author, rights_attested=True)
        _counts, cls.price_receipt = stage_price_with_receipt(
            io.BytesIO(csv_bytes([dict(PRICE_ROW, source_record_id='query-parity-price')])), PRICE_NAME,
            PRICE_MARKER, actor=author, rights_attested=True)

    def request(self, account, name, kwargs, method, query):
        client = self.client_class()
        if account is not None:
            client.force_login(account)
        url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
        if method == 'GET':
            return client.get(url, query)
        return client.post(url + ('?' + '&'.join(f'{k}={v}' for k, v in query.items()) if query else ''), {})

    def counts(self):
        return {model: model.objects.count() for model in COUNTED_MODELS}

    def test_query_variants_cannot_change_an_unauthorized_denial(self):
        for account in (self.outsider, self.bare, self.viewer, self.product_only):
            for name, kwargs, method, requirement in ROUTES:
                if satisfies(account, requirement):
                    continue
                seen = {index: comparable(self.request(account, name, kwargs, method, query))
                        for index, query in enumerate(QUERY_VARIANTS)}
                with self.subTest(account=account.username, route=name):
                    self.assertEqual(len(set(seen.values())), 1,
                                     f'A query parameter changed the denial: {sorted(seen)}')
                    self.assertEqual(next(iter(seen.values()))[0], 403)

    def test_query_variants_never_produce_a_server_error_for_an_authorized_account(self):
        for account in (self.viewer, self.product_only, self.full):
            for name, kwargs, method, requirement in ROUTES:
                if not satisfies(account, requirement):
                    continue
                for index, query in enumerate(QUERY_VARIANTS):
                    with self.subTest(account=account.username, route=name, variant=index):
                        response = self.request(account, name, kwargs, method, query)
                        if response.status_code == 403:
                            # The single legitimate query-driven denial: a kind
                            # filter outside this account's scope.
                            self.assertEqual(name, KIND_FILTER_ROUTE)
                            self.assertEqual(query.get('kind'), 'price')
                            self.assertNotIn(PRICE_NAME, response.content.decode('utf-8'))
                        else:
                            self.assertIn(response.status_code, ALLOWED_STATUSES)
                        self.assertIn('no-store', response['Cache-Control'])
                        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    def test_query_variants_never_change_the_anonymous_redirect(self):
        login = reverse('staff_login')
        for name, kwargs, method, _requirement in ROUTES:
            for index, query in enumerate(QUERY_VARIANTS):
                with self.subTest(route=name, variant=index):
                    response = self.request(None, name, kwargs, method, query)
                    self.assertEqual(response.status_code, 302)
                    self.assertTrue(response['Location'].startswith(login))

    def test_a_kind_filter_cannot_widen_an_account_beyond_its_own_kind(self):
        # The product-only account holds catalog permissions and no pricing ones, so
        # the receipt list is reachable but the price kind is not.
        index = reverse('staff_import_receipts')
        client = self.client_class()
        client.force_login(self.product_only)
        allowed = client.get(index, {'kind': 'product'})
        self.assertEqual(allowed.status_code, 200)
        listed = allowed.content.decode('utf-8')
        self.assertIn(PRODUCT_NAME, listed)
        self.assertNotIn(PRICE_NAME, listed)
        self.assertNotIn(PRICE_MARKER, listed)
        forbidden = client.get(index, {'kind': 'price'})
        self.assertEqual(forbidden.status_code, 403)
        body = forbidden.content.decode('utf-8')
        self.assertNotIn(PRICE_NAME, body)
        self.assertNotIn(PRICE_MARKER, body)
        self.assertNotIn(PRODUCT_NAME, body)
        self.assertIn('no-store', forbidden['Cache-Control'])
        # Its own receipt is reachable; the other kind's receipt is answered exactly
        # as a receipt that does not exist at all.
        own = client.get(reverse('staff_import_receipt_detail', kwargs={'pk': self.product_receipt.pk}))
        self.assertEqual(own.status_code, 200)
        self.assertIn(PRODUCT_MARKER, own.content.decode('utf-8'))
        other = client.get(reverse('staff_import_receipt_detail', kwargs={'pk': self.price_receipt.pk}))
        missing = client.get(reverse('staff_import_receipt_detail', kwargs={'pk': self.price_receipt.pk + 1000}))
        self.assertEqual(comparable(other), comparable(missing))
        self.assertEqual(other.status_code, 404)
        self.assertNotIn(PRICE_MARKER, other.content.decode('utf-8'))
        # The same holds for the per-receipt manifest inspection.
        inspection = client.get(reverse('staff_import_manifest_inspection', kwargs={'pk': self.price_receipt.pk}))
        self.assertEqual(comparable(inspection), comparable(client.get(
            reverse('staff_import_manifest_inspection', kwargs={'pk': self.price_receipt.pk + 1000}))))
        self.assertEqual(inspection.status_code, 404)

    def test_probing_every_query_variant_writes_nothing(self):
        before = self.counts()
        for account in (None, self.outsider, self.bare, self.viewer, self.product_only, self.full):
            for name, kwargs, method, _requirement in ROUTES:
                for query in QUERY_VARIANTS:
                    self.request(account, name, kwargs, method, query)
        self.assertEqual(self.counts(), before)
