"""Endpoint-by-endpoint staff authorization matrix; synthetic evidence, not a review.

Every ``staff_*`` route except the two authentication endpoints is exercised with
four account shapes, and the expectation for each is derived from the route's
declared requirement rather than recorded from a single run:

* anonymous -> redirected to the staff login;
* active non-staff -> 403;
* active staff without the requirement -> 403;
* active staff with the requirement -> anything except 403 (200/302/400/404/409
  all prove the authorization check passed; detail routes use a missing pk);
* a deactivated full-permission account -> never served content.

This does not prove the checks are correctly designed, only that each route
enforces the requirement recorded here and that a new route cannot appear without
an explicit entry.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import get_resolver, reverse

ALL_PERMISSIONS = (
    ('catalog', 'view_productcandidate'), ('catalog', 'add_productcandidate'),
    ('catalog', 'review_productcandidate'), ('catalog', 'view_identityworkspace'),
    ('catalog', 'add_identityworkspace'), ('catalog', 'review_identityworkspace'),
    ('catalog', 'view_productpresentation'),
    ('pricing', 'view_pricecandidate'), ('pricing', 'add_pricecandidate'),
    ('pricing', 'review_pricecandidate'),
    ('sources', 'view_sourceclaim'), ('sources', 'add_sourceclaim'), ('sources', 'review_sourceclaim'),
    ('clinical', 'view_clinicaldraft'), ('clinical', 'add_clinicaldraft'), ('clinical', 'review_clinicaldraft'),
)
VIEW_PERMISSIONS = tuple(item for item in ALL_PERMISSIONS if item[1].startswith('view_'))

STAFF_ONLY = ('staff',)
PRODUCT = 'catalog.view_productcandidate'
PRICE = 'pricing.view_pricecandidate'
CLAIM = 'sources.view_sourceclaim'
DRAFT = 'clinical.view_clinicaldraft'
IDENTITY = 'catalog.view_identityworkspace'
PRESENTATION = 'catalog.view_productpresentation'

# name, kwargs, method, requirement ('all' every permission, 'any' one of them)
ROUTES = (
    ('staff_workspace', {}, 'GET', STAFF_ONLY),
    ('staff_sources', {}, 'GET', ('all', CLAIM)),
    ('staff_source_date_inspection', {}, 'GET', ('all', CLAIM)),
    ('staff_source_detail', {'pk': 1}, 'GET', ('all', CLAIM)),
    ('staff_source_review_inspection', {'pk': 1}, 'GET', ('all', CLAIM)),
    ('staff_source_create', {}, 'GET', ('all', CLAIM, 'sources.add_sourceclaim')),
    ('staff_source_review', {'pk': 1}, 'POST', ('all', CLAIM, 'sources.review_sourceclaim')),
    ('staff_products', {}, 'GET', ('all', PRODUCT)),
    ('staff_product_detail', {'pk': 1}, 'GET', ('all', PRODUCT)),
    ('staff_product_review_inspection', {'pk': 1}, 'GET', ('all', PRODUCT)),
    ('staff_product_upload', {}, 'GET', ('all', PRODUCT, 'catalog.add_productcandidate')),
    ('staff_product_sample', {}, 'GET', ('all', PRODUCT, 'catalog.add_productcandidate')),
    ('staff_product_review', {'pk': 1}, 'POST', ('all', PRODUCT, 'catalog.review_productcandidate')),
    ('staff_prices', {}, 'GET', ('all', PRICE)),
    ('staff_price_detail', {'pk': 1}, 'GET', ('all', PRICE)),
    ('staff_price_review_inspection', {'pk': 1}, 'GET', ('all', PRICE)),
    ('staff_price_upload', {}, 'GET', ('all', PRICE, 'pricing.add_pricecandidate')),
    ('staff_price_sample', {}, 'GET', ('all', PRICE, 'pricing.add_pricecandidate')),
    ('staff_price_review', {'pk': 1}, 'POST', ('all', PRICE, 'pricing.review_pricecandidate')),
    ('staff_clinical_drafts', {}, 'GET', ('all', DRAFT)),
    ('staff_clinical_inspection', {}, 'GET', ('all', DRAFT)),
    ('staff_clinical_detail', {'pk': 1}, 'GET', ('all', DRAFT)),
    ('staff_clinical_review_inspection', {'pk': 1}, 'GET', ('all', DRAFT)),
    ('staff_clinical_lineage', {'pk': 1}, 'GET', ('all', DRAFT)),
    ('staff_clinical_create', {}, 'GET', ('all', DRAFT, 'clinical.add_clinicaldraft')),
    ('staff_clinical_revise', {'pk': 1}, 'GET', ('all', DRAFT, 'clinical.add_clinicaldraft')),
    ('staff_clinical_reference_create', {'pk': 1}, 'GET', ('all', DRAFT, 'clinical.add_clinicaldraft')),
    ('staff_clinical_review', {'pk': 1}, 'POST', ('all', DRAFT, 'clinical.review_clinicaldraft')),
    ('staff_identity_list', {}, 'GET', ('all', IDENTITY)),
    ('staff_identity_detail', {'kind': 'ingredient', 'pk': 1}, 'GET', ('all', IDENTITY)),
    ('staff_identity_lineage', {'kind': 'ingredient', 'pk': 1}, 'GET', ('all', IDENTITY)),
    ('staff_identity_create', {'kind': 'ingredient'}, 'GET', ('all', IDENTITY, 'catalog.add_identityworkspace')),
    ('staff_identity_revise', {'pk': 1}, 'GET', ('all', IDENTITY, 'catalog.add_identityworkspace')),
    ('staff_identity_revise_component', {'kind': 'ingredient', 'pk': 1}, 'GET',
     ('all', IDENTITY, 'catalog.add_identityworkspace')),
    ('staff_identity_review', {'pk': 1}, 'POST', ('all', IDENTITY, 'catalog.review_identityworkspace')),
    ('staff_catalog_quality', {}, 'GET', ('all', PRESENTATION)),
    ('staff_catalog_quality_irc', {'pk': 1}, 'GET', ('all', PRESENTATION)),
    ('staff_import_receipts', {}, 'GET', ('any', PRODUCT, PRICE)),
    ('staff_import_receipt_detail', {'pk': 1}, 'GET', ('any', PRODUCT, PRICE)),
    ('staff_import_manifest_inspection', {'pk': 1}, 'GET', ('any', PRODUCT, PRICE)),
    ('staff_ingestion_window', {}, 'GET', ('any', PRODUCT, PRICE, CLAIM)),
)
AUTH_ROUTES = frozenset({'staff_login', 'staff_logout'})


def satisfies(account, requirement):
    if requirement == STAFF_ONLY:
        return True
    mode, *permissions = requirement
    held = {perm for perm in permissions if account.has_perm(perm)}
    return bool(held) if mode == 'any' else len(held) == len(permissions)


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffAuthorizationMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.outsider = User.objects.create_user('matrix-outsider', password='synthetic-only')
        cls.bare = User.objects.create_user('matrix-bare-staff', password='synthetic-only', is_staff=True)
        cls.viewer = User.objects.create_user('matrix-view-staff', password='synthetic-only', is_staff=True)
        cls.viewer.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in VIEW_PERMISSIONS]))
        cls.full = User.objects.create_user('matrix-full-staff', password='synthetic-only', is_staff=True)
        cls.full.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        cls.disabled = User.objects.create_user('matrix-disabled-staff', password='synthetic-only', is_staff=True)
        cls.disabled.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        get_user_model().objects.filter(pk=cls.disabled.pk).update(is_active=False)

    def request(self, account, name, kwargs, method):
        client = self.client_class()
        if account is not None:
            client.force_login(account)
        url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
        return client.get(url) if method == 'GET' else client.post(url, {})

    def test_matrix_covers_every_staff_route(self):
        names = {name for name in get_resolver().reverse_dict if isinstance(name, str) and name.startswith('staff_')}
        listed = {row[0] for row in ROUTES}
        self.assertEqual(len(listed), len(ROUTES), 'A route is listed twice.')
        self.assertEqual(names - listed - AUTH_ROUTES, set(),
                         'A new staff route needs an explicit authorization expectation.')
        self.assertEqual((listed | AUTH_ROUTES) - names, set(),
                         'A listed staff route no longer exists.')

    def test_matrix_shape_is_not_vacuous(self):
        # Exact counts keep the matrix honest: if a requirement is weakened or a
        # route is dropped, one of these numbers moves and must be reviewed.
        self.assertEqual(len(ROUTES), 41)
        self.assertEqual(sum(1 for row in ROUTES if satisfies(self.bare, row[3])), 1)
        self.assertEqual(sum(1 for row in ROUTES if satisfies(self.viewer, row[3])), 25)
        self.assertEqual(sum(1 for row in ROUTES if satisfies(self.full, row[3])), len(ROUTES))
        self.assertEqual(sum(1 for row in ROUTES if row[3][0] == 'any'), 4)
        self.assertEqual(sum(1 for row in ROUTES if row[2] == 'POST'), 5)
        self.assertEqual(sum(1 for row in ROUTES if row[1]), 24)

    def test_anonymous_requests_are_redirected_to_the_staff_login(self):
        login = reverse('staff_login')
        for name, kwargs, method, _requirement in ROUTES:
            with self.subTest(route=name):
                response = self.request(None, name, kwargs, method)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response['Location'].startswith(login), response['Location'])

    def test_active_non_staff_accounts_are_denied_every_route(self):
        for name, kwargs, method, _requirement in ROUTES:
            with self.subTest(route=name):
                self.assertEqual(self.request(self.outsider, name, kwargs, method).status_code, 403)

    def test_staff_accounts_are_denied_routes_they_do_not_satisfy(self):
        for account in (self.bare, self.viewer):
            for name, kwargs, method, requirement in ROUTES:
                if satisfies(account, requirement):
                    continue
                with self.subTest(account=account.username, route=name):
                    self.assertEqual(self.request(account, name, kwargs, method).status_code, 403)

    def test_staff_accounts_reach_every_route_they_satisfy(self):
        for account in (self.bare, self.viewer, self.full):
            for name, kwargs, method, requirement in ROUTES:
                if not satisfies(account, requirement):
                    continue
                with self.subTest(account=account.username, route=name):
                    response = self.request(account, name, kwargs, method)
                    self.assertNotEqual(response.status_code, 403)
                    self.assertIn(response.status_code, (200, 302, 400, 404, 405, 409))
                    if response.status_code == 302:
                        self.assertFalse(response['Location'].startswith(reverse('staff_login')),
                                         'An authorized account was redirected to login.')

    def test_a_deactivated_full_permission_account_is_never_served_content(self):
        for name, kwargs, method, _requirement in ROUTES:
            with self.subTest(route=name):
                response = self.request(self.disabled, name, kwargs, method)
                self.assertIn(response.status_code, (302, 403))
                if response.status_code == 302:
                    self.assertTrue(response['Location'].startswith(reverse('staff_login')))

    def test_denied_routes_do_not_leak_private_staff_headers_or_content(self):
        # A denial must still carry the staff privacy headers applied by middleware.
        for name, kwargs, method, _requirement in ROUTES[:6]:
            with self.subTest(route=name):
                response = self.request(self.outsider, name, kwargs, method)
                self.assertEqual(response.status_code, 403)
                self.assertIn('no-store', response['Cache-Control'])
                self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
