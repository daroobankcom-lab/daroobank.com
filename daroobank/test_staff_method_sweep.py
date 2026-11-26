"""HTTP method sweep across every staff route; synthetic evidence, not a review.

ADR 0200 and ADR 0205 exercised GET and POST. This suite sweeps HEAD, OPTIONS,
PUT, PATCH and DELETE as well, over all 43 `staff_*` routes and three account
shapes, and pins what the surface accepts:

* no route in the matrix, and neither authentication endpoint except the login
  form, accepts a destructive method: PUT, PATCH and DELETE are answered 405 with
  an empty body, and an anonymous request is redirected before the method is even
  considered;
* `Allow` names exactly the methods the view decorators declare, so a rejected
  method does not advertise one the route does not have;
* HEAD mirrors GET in status with an empty body on the 27 `require_safe` routes and
  on the class-based login view, while the 9 dual-method routes, the 5 POST-only
  routes and logout answer 405, because their decorators do not list HEAD;
* the method gate runs before authorization: an unauthorized account and a fully
  permitted one receive the identical 405;
* Django's class-based login form does accept PUT and routes it to its `post`
  handler, which means the opt-in login throttle cannot be bypassed by switching
  method. That is measured separately, because the throttle is a no-op inside a
  test transaction.

It records current behavior on a development-only portal with synthetic data. It is
not a method-level security review.
"""
import time
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .test_staff_authorization_matrix import ALL_PERMISSIONS, ROUTES, VIEW_PERMISSIONS
from .test_staff_authorization_objects import COUNTED_MODELS, build_object_rows
from .test_staff_csrf_gate import DUAL_METHOD_ROUTES, POST_ONLY_ROUTES
from .test_staff_denial_parity import comparable

METHODS = ('GET', 'HEAD', 'OPTIONS', 'PUT', 'PATCH', 'DELETE')
DESTRUCTIVE = ('PUT', 'PATCH', 'DELETE')
AUTH_ROUTES = ('staff_login', 'staff_logout')
# `Allow` as the decorators declare it: `require_safe`, the dual-method form views
# and `require_POST`. The two class-based authentication endpoints differ because
# Django's generic views answer OPTIONS and, for the login form, PUT.
EXPECTED_ALLOW = {
    'safe-only': 'GET, HEAD',
    'dual': 'GET, POST',
    'post-only': 'POST',
    'staff_logout': 'POST, OPTIONS',
    'staff_login': 'GET, POST, PUT, HEAD, OPTIONS',
}


def send(client, url, method, **extra):
    if method == 'GET':
        return client.get(url, **extra)
    if method == 'HEAD':
        return client.head(url, **extra)
    if method == 'OPTIONS':
        return client.options(url, **extra)
    if method == 'PUT':
        return client.put(url, data='{}', content_type='application/json', **extra)
    if method == 'PATCH':
        return client.patch(url, data='{}', content_type='application/json', **extra)
    return client.delete(url, **extra)


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffMethodSweepTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.outsider = User.objects.create_user('method-outsider', password='synthetic-only')
        cls.bare = User.objects.create_user('method-bare-staff', password='synthetic-only', is_staff=True)
        cls.viewer = User.objects.create_user('method-view-staff', password='synthetic-only', is_staff=True)
        cls.viewer.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in VIEW_PERMISSIONS]))
        cls.full = User.objects.create_user('method-full-staff', password='synthetic-only', is_staff=True)
        cls.full.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        author = User.objects.create_user('method-author', password='synthetic-only', is_staff=True)
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
            yield name, real.get(name, kwargs), 'matrix'
        for name in AUTH_ROUTES:
            yield name, {}, 'auth'

    def group_of(self, name):
        if name == 'staff_login' or name == 'staff_logout':
            return name
        if name in POST_ONLY_ROUTES:
            return 'post-only'
        if name in DUAL_METHOD_ROUTES:
            return 'dual'
        return 'safe-only'

    def request(self, account, url, method):
        client = Client()
        if account is not None:
            client.force_login(account)
        return send(client, url, method)

    def counts(self):
        return {model: model.objects.count() for model in COUNTED_MODELS}

    def test_the_route_groups_are_the_sizes_the_decorators_declare(self):
        groups = {}
        for name, _kwargs, kind in self.all_routes():
            groups.setdefault(self.group_of(name), []).append(name)
        self.assertEqual(len(groups['safe-only']), 27)
        self.assertEqual(len(groups['dual']), 9)
        self.assertEqual(len(groups['post-only']), 5)
        self.assertEqual(sorted(groups['staff_login'] + groups['staff_logout']), list(AUTH_ROUTES))
        self.assertEqual(sum(len(value) for value in groups.values()), 43)

    def test_no_route_accepts_a_destructive_method(self):
        login = reverse('staff_login')
        for name, kwargs, kind in self.all_routes():
            url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
            for method in DESTRUCTIVE:
                if name == 'staff_login' and method == 'PUT':
                    continue  # Django's login FormView routes PUT to its post handler.
                for account in (None, self.outsider, self.bare, self.viewer, self.full):
                    with self.subTest(route=name, method=method,
                                      account='anonymous' if account is None else account.username):
                        response = self.request(account, url, method)
                        if account is None and kind == 'matrix':
                            self.assertEqual(response.status_code, 302)
                            self.assertTrue(response['Location'].startswith(login))
                            continue
                        self.assertEqual(response.status_code, 405)
                        self.assertEqual(response.content, b'')
                        self.assertNotIn(method, response['Allow'])
                        self.assertIn('no-store', response['Cache-Control'])

    def test_the_login_form_accepts_put_without_authenticating_anything(self):
        # Recorded because it is Django's `ProcessFormView.put` delegating to
        # `post`: the route does accept PUT, and an empty submission must not
        # create a session.
        url = reverse('staff_login')
        for account in (None, self.outsider, self.full):
            client = Client()
            if account is not None:
                client.force_login(account)
            with self.subTest(account='anonymous' if account is None else account.username):
                response = send(client, url, 'PUT')
                self.assertEqual(response.status_code, 200)
                self.assertIn('no-store', response['Cache-Control'])
                if account is None:
                    self.assertNotIn('_auth_user_id', client.session)
                else:
                    self.assertEqual(response.status_code, 200, 'A logged-in PUT must re-render, not redirect.')

    def test_head_mirrors_get_only_where_require_safe_declares_it(self):
        # Recorded as a difference between decorator groups: `require_safe` allows
        # GET and HEAD, while `require_http_methods(['GET', 'POST'])` and
        # `require_POST` do not list HEAD, so those routes answer 405. Django's
        # class-based login view allows HEAD; its logout view does not.
        login = reverse('staff_login')
        for name, kwargs, kind in self.all_routes():
            url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
            group = self.group_of(name)
            for account in (None, self.outsider, self.viewer, self.full):
                who = 'anonymous' if account is None else account.username
                with self.subTest(route=name, group=group, account=who):
                    got = self.request(account, url, 'GET')
                    headed = self.request(account, url, 'HEAD')
                    self.assertEqual(headed.content, b'')
                    self.assertIn('no-store', headed['Cache-Control'])
                    self.assertEqual(headed['X-Robots-Tag'], 'noindex, nofollow')
                    if account is None and kind == 'matrix':
                        self.assertEqual((headed.status_code, got.status_code), (302, 302))
                        self.assertTrue(headed['Location'].startswith(login))
                    elif group in ('safe-only', 'staff_login'):
                        self.assertEqual(headed.status_code, got.status_code)
                        self.assertEqual(headed['Cache-Control'], got['Cache-Control'])
                    else:
                        self.assertEqual(headed.status_code, 405)
                        self.assertEqual(headed['Allow'], EXPECTED_ALLOW[group])
                        self.assertNotIn('HEAD', headed['Allow'])

    def test_allow_names_exactly_the_declared_methods(self):
        for name, kwargs, _kind in self.all_routes():
            url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
            group = self.group_of(name)
            expected = EXPECTED_ALLOW[group]
            rejected = 'OPTIONS' if group != 'staff_logout' else 'GET'
            for account in (self.outsider, self.bare, self.viewer, self.full):
                with self.subTest(route=name, group=group, account=account.username):
                    response = self.request(account, url, rejected)
                    # Django's generic views answer OPTIONS with 200 and an Allow
                    # header; the function views answer 405 with the same header.
                    self.assertIn(response.status_code, (200, 405))
                    self.assertEqual(response['Allow'], expected)

    def test_the_method_gate_runs_before_authorization(self):
        # An account with every permission and one with none must receive the
        # identical rejection, so the method answer reveals nothing about access.
        for name, kwargs, _kind in self.all_routes():
            if name == 'staff_login':
                continue
            url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
            for method in METHODS:
                if method in ('GET', 'HEAD'):
                    continue
                with self.subTest(route=name, method=method):
                    permitted = comparable(self.request(self.full, url, method))
                    denied = [comparable(self.request(account, url, method))
                              for account in (self.outsider, self.bare)]
                    self.assertEqual(len(set(denied)), 1)
                    self.assertEqual(denied[0], permitted,
                                     'The method answer differs by account.')

    def test_the_comparison_ignores_the_per_second_expires_stamp(self):
        # `never_cache` wraps the two class-based auth endpoints, so their answers
        # carry an `Expires` header with second granularity. Two identical requests
        # a second apart must still compare equal, otherwise every parity assertion
        # that includes logout depends on the clock (ADR 0212).
        for name in AUTH_ROUTES:
            url = reverse(name)
            first = self.request(self.full, url, 'OPTIONS')
            self.assertIn('Expires', first.headers, f'{name} no longer stamps Expires; this guard is vacuous')
            expected = comparable(first)
            time.sleep(1.1)
            second = self.request(self.full, url, 'OPTIONS')
            with self.subTest(route=name):
                self.assertNotEqual(first.headers['Expires'], second.headers['Expires'])
                self.assertEqual(expected, comparable(second))

    def test_sweeping_every_method_writes_nothing(self):
        before = self.counts()
        for account in (None, self.outsider, self.bare, self.viewer, self.full):
            for name, kwargs, _kind in self.all_routes():
                url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
                for method in METHODS:
                    self.request(account, url, method)
        self.assertEqual(self.counts(), before)


@override_settings(STAFF_PORTAL_ENABLED=True, STAFF_LOGIN_THROTTLE_ENABLED=True)
class StaffLoginPutThrottleTests(TransactionTestCase):
    """The opt-in throttle is a no-op inside a test transaction, hence the class."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('method-throttle-staff', password='synthetic-passphrase',
                                                         is_staff=True)
        self.url = reverse('staff_login')

    def attempt(self, client, method, *, address='192.0.2.97', password='wrong'):
        payload = {'username': 'method-throttle-staff', 'password': password}
        if method == 'POST':
            return client.post(self.url, payload, REMOTE_ADDR=address)
        return client.put(self.url, data=payload, REMOTE_ADDR=address)

    def test_a_put_login_attempt_consumes_the_same_window_as_a_post(self):
        from staff_security.throttle import ATTEMPT_LIMIT
        client = Client()
        for _ in range(ATTEMPT_LIMIT):
            self.assertEqual(self.attempt(client, 'PUT').status_code, 200)
        # If PUT bypassed the throttled `post` override, the window would still be
        # open and these correct credentials would authenticate.
        blocked = self.attempt(client, 'POST', password='synthetic-passphrase')
        self.assertEqual(blocked.status_code, 429)
        self.assertNotIn('_auth_user_id', client.session)
        self.assertIn('no-store', blocked['Cache-Control'])

    def test_a_post_filled_window_also_blocks_a_put(self):
        from staff_security.throttle import ATTEMPT_LIMIT
        client = Client()
        for _ in range(ATTEMPT_LIMIT):
            self.assertEqual(self.attempt(client, 'POST').status_code, 200)
        blocked = self.attempt(client, 'PUT', password='synthetic-passphrase')
        self.assertEqual(blocked.status_code, 429)
        self.assertNotIn('_auth_user_id', client.session)
