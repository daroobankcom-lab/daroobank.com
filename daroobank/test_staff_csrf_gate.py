"""The CSRF gate on every staff route; synthetic evidence, not a review.

Django's CSRF middleware runs before authentication, authorization and the
per-view method decorators. This suite measures that ordering across all 43
`staff_*` routes rather than assuming it, and pins what each route does once a
valid same-session token is presented.

Recorded expectations:

* a token-less POST is rejected identically on every route for every account
  shape, including anonymous ones, and even on routes that would answer 405;
* the rejection body depends only on whether the client holds a CSRF cookie, never
  on the account's permissions or on the route;
* a cross-origin POST carrying a valid token, and a mangled, foreign or empty
  token, are rejected with the same response;
* with a valid same-session token the answer becomes route-specific and matches
  the method classification read from the view decorators: 405 on the 27
  safe-only routes, a rendered form on the 9 dual-method routes, 400 on the 5
  POST-only review routes;
* none of these probes writes a row.

It is not a CSRF review, a penetration test or an approval.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import get_resolver, reverse

from .test_staff_authorization_matrix import ALL_PERMISSIONS, AUTH_ROUTES, ROUTES, VIEW_PERMISSIONS, satisfies
from .test_staff_authorization_objects import COUNTED_MODELS, build_object_rows
from .test_staff_denial_parity import comparable

# Method classification read from the view decorators, not from a recorded run:
# `require_POST` views, `require_http_methods(['GET', 'POST'])` views and
# `require_safe` views.
POST_ONLY_ROUTES = frozenset({'staff_source_review', 'staff_product_review', 'staff_price_review',
                              'staff_clinical_review', 'staff_identity_review'})
DUAL_METHOD_ROUTES = frozenset({'staff_source_create', 'staff_product_upload', 'staff_price_upload',
                                'staff_clinical_create', 'staff_clinical_revise',
                                'staff_clinical_reference_create', 'staff_identity_create',
                                'staff_identity_revise', 'staff_identity_revise_component'})
EVIL_ORIGIN = 'https://evil.example'


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffCsrfGateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.outsider = User.objects.create_user('csrf-outsider', password='synthetic-only')
        cls.bare = User.objects.create_user('csrf-bare-staff', password='synthetic-only', is_staff=True)
        cls.viewer = User.objects.create_user('csrf-view-staff', password='synthetic-only', is_staff=True)
        cls.viewer.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in VIEW_PERMISSIONS]))
        cls.full = User.objects.create_user('csrf-full-staff', password='synthetic-only', is_staff=True)
        cls.full.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        author = User.objects.create_user('csrf-author', password='synthetic-only', is_staff=True)
        author.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        cls.rows = build_object_rows(author)

    def all_routes(self):
        """All 43 staff routes with real kwargs where a route takes a row."""
        rows = self.rows
        real = {
            'staff_source_detail': {'pk': rows.claim.pk},
            'staff_source_review_inspection': {'pk': rows.claim.pk},
            'staff_source_review': {'pk': rows.claim.pk},
            'staff_product_detail': {'pk': rows.candidate.pk},
            'staff_product_review_inspection': {'pk': rows.candidate.pk},
            'staff_product_review': {'pk': rows.candidate.pk},
            'staff_price_detail': {'pk': rows.price.pk},
            'staff_price_review_inspection': {'pk': rows.price.pk},
            'staff_price_review': {'pk': rows.price.pk},
            'staff_clinical_detail': {'pk': rows.draft.pk},
            'staff_clinical_review_inspection': {'pk': rows.draft.pk},
            'staff_clinical_lineage': {'pk': rows.draft.pk},
            'staff_clinical_revise': {'pk': rows.draft.pk},
            'staff_clinical_reference_create': {'pk': rows.draft.pk},
            'staff_clinical_review': {'pk': rows.draft.pk},
            'staff_identity_detail': {'kind': 'package', 'pk': rows.package.pk},
            'staff_identity_lineage': {'kind': 'package', 'pk': rows.package.pk},
            'staff_identity_create': {'kind': 'ingredient'},
            'staff_identity_revise': {'pk': rows.package.pk},
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

    def client_for(self, account, *, with_cookie=False):
        client = Client(enforce_csrf_checks=True)
        if account is not None:
            client.force_login(account)
        if with_cookie:
            # The login page renders a form, so it hands out a CSRF cookie to any
            # client, authorized or not.
            self.assertEqual(client.get(reverse('staff_login')).status_code, 200)
            self.assertIn('csrftoken', client.cookies)
        return client

    def token_of(self, client):
        return client.cookies['csrftoken'].value

    def counts(self):
        return {model: model.objects.count() for model in COUNTED_MODELS}

    def test_the_method_classification_matches_the_route_inventory(self):
        names = {name for name in get_resolver().reverse_dict if isinstance(name, str) and name.startswith('staff_')}
        self.assertEqual(len(names), 43)
        self.assertEqual(POST_ONLY_ROUTES | DUAL_METHOD_ROUTES | AUTH_ROUTES,
                         {'staff_source_review', 'staff_product_review', 'staff_price_review', 'staff_clinical_review',
                          'staff_identity_review', 'staff_source_create', 'staff_product_upload',
                          'staff_price_upload', 'staff_clinical_create', 'staff_clinical_revise',
                          'staff_clinical_reference_create', 'staff_identity_create', 'staff_identity_revise',
                          'staff_identity_revise_component', 'staff_login', 'staff_logout'})
        self.assertEqual(len(POST_ONLY_ROUTES), 5)
        self.assertEqual(len(DUAL_METHOD_ROUTES), 9)
        self.assertEqual(POST_ONLY_ROUTES & DUAL_METHOD_ROUTES, frozenset())
        self.assertEqual(len(names - POST_ONLY_ROUTES - DUAL_METHOD_ROUTES - AUTH_ROUTES), 27)
        self.assertTrue(POST_ONLY_ROUTES <= names and DUAL_METHOD_ROUTES <= names)
        # The five POST-only routes are exactly the review routes the matrix marks POST.
        self.assertEqual(POST_ONLY_ROUTES, {name for name, _kwargs, method, _requirement in ROUTES
                                            if method == 'POST'})

    def test_a_token_less_post_is_rejected_identically_on_every_route_for_every_shape(self):
        shapes = (None, self.outsider, self.bare, self.viewer, self.full)
        seen = {}
        for account in shapes:
            client = self.client_for(account)
            for name, kwargs in self.all_routes():
                response = client.post(reverse(name, kwargs=kwargs) if kwargs else reverse(name), {})
                seen.setdefault(comparable(response), []).append((account, name))
        with self.subTest(case='single-canonical-rejection'):
            self.assertEqual(len(seen), 1,
                             f'A token-less POST is answered differently: '
                             f'{[(key[0], len(value)) for key, value in seen.items()]}')
        status, body, headers = next(iter(seen))
        self.assertEqual(status, 403)
        self.assertEqual(len(seen[next(iter(seen))]), 5 * 43)
        header_map = dict(headers)
        self.assertIn('no-store', header_map['cache-control'])
        self.assertEqual(header_map['x-robots-tag'], 'noindex, nofollow')
        self.assertNotIn(b'MARKER', body)

    def test_the_rejection_depends_on_the_cookie_not_on_the_account_or_the_route(self):
        # A client that holds a CSRF cookie but sends no token gets one answer on
        # all 43 routes, and that answer is the same for an account with every
        # permission and for one with none, so the body reveals the client's own
        # cookie state and nothing about authorization.
        bodies = {}
        for account in (self.outsider, self.bare, self.viewer, self.full):
            client = self.client_for(account, with_cookie=True)
            responses = {comparable(client.post(reverse(name, kwargs=kwargs) if kwargs else reverse(name), {}))
                         for name, kwargs in self.all_routes()}
            self.assertEqual(len(responses), 1, f'{account.username}: the answer differs by route.')
            bodies[account.username] = responses.pop()
        self.assertEqual(len(set(bodies.values())), 1,
                         'The cookie-holding rejection differs by account.')
        cookieless = self.client_for(self.full)
        without = comparable(cookieless.post(reverse('staff_workspace'), {}))
        with_cookie = bodies[self.full.username]
        self.assertEqual(without[0], 403)
        self.assertEqual(with_cookie[0], 403)
        self.assertNotEqual(without[1], with_cookie[1],
                            'Expected the cookie-less and cookie-holding rejections to differ, so the '
                            'assertions above are about the cookie rather than about nothing.')

    def test_cross_origin_mangled_foreign_and_empty_tokens_are_rejected_identically(self):
        client = self.client_for(self.full, with_cookie=True)
        token = self.token_of(client)
        variants = {
            'no-token': {},
            'cross-origin': {'HTTP_X_CSRFTOKEN': token, 'HTTP_ORIGIN': EVIL_ORIGIN},
            'mangled': {'HTTP_X_CSRFTOKEN': token[:-1] + ('a' if token[-1] != 'a' else 'b')},
            'foreign': {'HTTP_X_CSRFTOKEN': 'x' * len(token)},
            'empty': {'HTTP_X_CSRFTOKEN': ''},
        }
        for name, kwargs in self.all_routes():
            url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
            seen = {label: comparable(client.post(url, {}, **extra)) for label, extra in variants.items()}
            with self.subTest(route=name):
                self.assertEqual(len(set(seen.values())), 1,
                                 f'The rejection differs by token failure mode: {sorted(seen)}')
                self.assertEqual(next(iter(seen.values()))[0], 403)

    def test_with_a_valid_same_session_token_the_answer_follows_the_view_decorators(self):
        client = self.client_for(self.full, with_cookie=True)
        token = self.token_of(client)
        for name, kwargs in self.all_routes():
            url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
            response = client.post(url, {}, HTTP_X_CSRFTOKEN=token)
            with self.subTest(route=name):
                self.assertIn('no-store', response['Cache-Control'])
                if name in POST_ONLY_ROUTES:
                    # An empty submission reaches form handling and fails validation.
                    self.assertEqual(response.status_code, 400)
                elif name in DUAL_METHOD_ROUTES or name == 'staff_login':
                    self.assertIn(response.status_code, (200, 400))
                elif name == 'staff_logout':
                    self.assertEqual(response.status_code, 302)
                else:
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response.content, b'')
                    self.assertEqual(response['Allow'], 'GET, HEAD')

    def test_an_unauthorized_account_with_a_valid_token_still_gets_no_content(self):
        # The CSRF gate is not the authorization gate: once a token is accepted the
        # permission check still denies, with the usual 403.
        for account in (self.outsider, self.bare, self.viewer):
            client = self.client_for(account, with_cookie=True)
            token = self.token_of(client)
            for name, kwargs, method, requirement in ROUTES:
                if name in POST_ONLY_ROUTES | DUAL_METHOD_ROUTES and not satisfies(account, requirement):
                    with self.subTest(account=account.username, route=name):
                        url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
                        self.assertEqual(client.post(url, {}, HTTP_X_CSRFTOKEN=token).status_code, 403)

    def test_no_csrf_probe_writes_anything(self):
        before = self.counts()
        for account in (None, self.outsider, self.bare, self.viewer, self.full):
            for with_cookie in (False, True):
                client = self.client_for(account, with_cookie=with_cookie)
                token = self.token_of(client) if with_cookie else ''
                for name, kwargs in self.all_routes():
                    url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
                    client.post(url, {})
                    client.post(url, {}, HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN=EVIL_ORIGIN)
                    if with_cookie:
                        client.post(url, {}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(self.counts(), before)
