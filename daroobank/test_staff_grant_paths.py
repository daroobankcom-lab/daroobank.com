"""How staff permission grants reach each route; synthetic evidence, not a review.

`test_staff_authorization_matrix.py` grants permissions directly to an account.
Real deployments grant them through groups, and Django also grants everything to a
superuser. This suite repeats the same 41-route matrix for grant paths that the
matrix does not cover, so that:

* a group grant is equivalent to a direct grant of the same permissions;
* a superuser reaches every route, which is recorded as the bypass it is;
* `is_staff` still gates a superuser, and `is_active` still gates everyone;
* an alternate backend that authenticates inactive accounts still gets no content;
* a service-level recheck denies an in-memory actor whose group grant was revoked,
  even though that stale object still reports the permission.

This records current behavior. It does not judge whether any requirement is
correct, and it is not an authorization review.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from .actor_recheck import recheck_actor
from .test_staff_authorization_matrix import (ALL_PERMISSIONS, ROUTES, VIEW_PERMISSIONS, satisfies)

BACKEND = 'django.contrib.auth.backends.AllowAllUsersModelBackend'


def fresh(pk):
    """Load an account from the database so no permission cache is reused."""
    return get_user_model().objects.get(pk=pk)


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffGrantPathTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        every = list(Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        views = list(Permission.objects.filter(codename__in=[c for _a, c in VIEW_PERMISSIONS]))
        cls.full_group = Group.objects.create(name='grants-full')
        cls.full_group.permissions.set(every)
        cls.view_group = Group.objects.create(name='grants-view')
        cls.view_group.permissions.set(views)

        cls.group_full = User.objects.create_user('grants-group-full', password='synthetic-only', is_staff=True)
        cls.group_full.groups.add(cls.full_group)
        cls.group_view = User.objects.create_user('grants-group-view', password='synthetic-only', is_staff=True)
        cls.group_view.groups.add(cls.view_group)
        cls.superuser = User.objects.create_user('grants-superuser', password='synthetic-only', is_staff=True,
                                                 is_superuser=True)
        cls.superuser_nonstaff = User.objects.create_user('grants-superuser-nonstaff', password='synthetic-only',
                                                          is_superuser=True)
        cls.inactive_group_full = User.objects.create_user('grants-inactive', password='synthetic-only', is_staff=True)
        cls.inactive_group_full.groups.add(cls.full_group)
        User.objects.filter(pk=cls.inactive_group_full.pk).update(is_active=False)
        cls.stale = User.objects.create_user('grants-stale', password='synthetic-only', is_staff=True)
        cls.stale.groups.add(cls.full_group)

    def request(self, account, name, kwargs, method):
        client = self.client_class()
        if account is not None:
            client.force_login(account)
        url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
        return client.get(url) if method == 'GET' else client.post(url, {})

    def test_a_group_grant_reaches_exactly_what_the_same_direct_grant_reaches(self):
        for account in (self.group_full, self.group_view):
            loaded = fresh(account.pk)
            reached = 0
            for name, kwargs, method, requirement in ROUTES:
                expected = satisfies(loaded, requirement)
                with self.subTest(account=account.username, route=name):
                    response = self.request(account, name, kwargs, method)
                    self.assertEqual(response.status_code == 403, not expected)
                    if expected:
                        # Routes are probed with the matrix's missing primary keys,
                        # so 404 is the normal authorized outcome here.
                        reached += 1
                        self.assertIn(response.status_code, (200, 302, 400, 404, 405, 409))
            self.assertEqual(reached, sum(1 for row in ROUTES if satisfies(loaded, row[3])))
        # A full group grant is equivalent to the 41/41 direct grant; a view-only
        # group reaches the same 25 routes as a view-only direct grant.
        self.assertEqual(sum(1 for row in ROUTES if satisfies(fresh(self.group_full.pk), row[3])), 41)
        self.assertEqual(sum(1 for row in ROUTES if satisfies(fresh(self.group_view.pk), row[3])), 25)

    def test_a_superuser_reaches_every_route_without_any_explicit_grant(self):
        # Recorded as the bypass it is: Django grants every permission to an active
        # superuser, so least privilege does not apply to that account shape.
        self.assertEqual(self.superuser.user_permissions.count(), 0)
        self.assertEqual(self.superuser.groups.count(), 0)
        for name, kwargs, method, _requirement in ROUTES:
            with self.subTest(route=name):
                response = self.request(self.superuser, name, kwargs, method)
                self.assertNotEqual(response.status_code, 403)
                self.assertIn(response.status_code, (200, 302, 400, 404, 405, 409))

    def test_is_staff_still_gates_a_superuser(self):
        for name, kwargs, method, _requirement in ROUTES:
            with self.subTest(route=name):
                self.assertEqual(self.request(self.superuser_nonstaff, name, kwargs, method).status_code, 403)

    def test_an_inactive_group_member_is_never_served_content(self):
        login = reverse('staff_login')
        for name, kwargs, method, _requirement in ROUTES:
            with self.subTest(route=name):
                response = self.request(self.inactive_group_full, name, kwargs, method)
                self.assertIn(response.status_code, (302, 403))
                if response.status_code == 302:
                    self.assertTrue(response['Location'].startswith(login))

    def test_a_backend_that_authenticates_inactive_accounts_still_gets_no_content(self):
        with override_settings(AUTHENTICATION_BACKENDS=[BACKEND]):
            client = self.client_class()
            self.assertTrue(client.login(username='grants-inactive', password='synthetic-only'),
                            'The alternate backend should authenticate this account.')
            # Recorded as a hazard, not as an accident: this backend establishes a
            # real session for a deactivated account. Denial therefore depends on
            # every destination checking `is_active` itself.
            self.assertIn('_auth_user_id', client.session)
            for name, kwargs, method, _requirement in ROUTES:
                with self.subTest(route=name):
                    url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
                    response = client.get(url) if method == 'GET' else client.post(url, {})
                    self.assertEqual(response.status_code, 403)
                    self.assertNotIn('Location', response)
                    self.assertIn('no-store', response['Cache-Control'])
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                    # The denial is identical to the default backend's denial of an
                    # active account that lacks `is_staff`, so the reason is not
                    # distinguishable from the response.
                    baseline = self.request(self.superuser_nonstaff, name, kwargs, method)
                    self.assertEqual(baseline.status_code, 403)
                    self.assertEqual(response.content, baseline.content)

    def test_denials_for_every_grant_path_carry_staff_privacy_headers(self):
        for account in (self.superuser_nonstaff, self.group_view, self.inactive_group_full):
            for name, kwargs, method, requirement in ROUTES[:6]:
                if satisfies(fresh(account.pk), requirement):
                    continue
                with self.subTest(account=account.username, route=name):
                    response = self.request(account, name, kwargs, method)
                    self.assertIn(response.status_code, (302, 403))
                    self.assertIn('no-store', response['Cache-Control'])
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    def test_a_service_recheck_denies_a_revoked_group_grant_a_stale_object_still_reports(self):
        # Prime the in-memory permission cache, then revoke through a second object.
        stale = fresh(self.stale.pk)
        self.assertTrue(stale.has_perm('catalog.view_productcandidate'))
        second = fresh(self.stale.pk)
        Group.objects.get(pk=self.full_group.pk).permissions.clear()
        self.assertTrue(stale.has_perm('catalog.view_productcandidate'),
                        'Expected the stale object to keep its cached grant; this is why services recheck.')
        self.assertFalse(fresh(self.stale.pk).has_perm('catalog.view_productcandidate'))
        with self.assertRaises(PermissionDenied):
            recheck_actor(stale, ('catalog.view_productcandidate',))
        self.assertFalse(second.has_perm('catalog.review_productcandidate'))
        with self.assertRaises(PermissionDenied):
            recheck_actor(stale, ('catalog.view_productcandidate',), session_auth_hash=stale.get_session_auth_hash())
        # A reloaded account with the grant restored is accepted again.
        Group.objects.get(pk=self.full_group.pk).permissions.set(
            Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        self.assertEqual(recheck_actor(stale, ('catalog.view_productcandidate',)).pk, self.stale.pk)
