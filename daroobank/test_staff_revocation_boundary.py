"""Selected staff authorization checks after a staff flag is revoked."""
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import AllowAllUsersModelBackend
from django.test import TestCase, override_settings
from django.urls import get_resolver, reverse


class SyntheticPermissiveBackend(AllowAllUsersModelBackend):
    """Test-only backend permits inactive accounts and grants every permission."""

    def has_perm(self, user_obj, perm, obj=None):
        return True


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffRevocationBoundaryTests(TestCase):
    def routes(self):
        for pattern in get_resolver().url_patterns:
            name = pattern.name or ''
            if not name.startswith('staff_') or name in {'staff_login', 'staff_logout'}:
                continue
            kwargs = {key: 1 if converter.__class__.__name__ == 'IntConverter' else 'synthetic'
                      for key, converter in pattern.pattern.converters.items()}
            yield name, reverse(name, kwargs=kwargs)

    def test_existing_session_with_superuser_permissions_but_no_staff_flag_is_denied(self):
        user = get_user_model().objects.create_user('synthetic-revoked-staff', password='synthetic-only',
                                                    is_staff=True, is_superuser=True)
        self.client.force_login(user)
        # Simulate a privilege change after a session was established.
        get_user_model().objects.filter(pk=user.pk).update(is_staff=False)
        checked = 0
        for name, path in self.routes():
            for method in ('get', 'head', 'post'):
                with self.subTest(name=name, method=method):
                    response = getattr(self.client, method)(path)
                    self.assertIn(response.status_code, (403, 405), f'{name} unexpectedly allowed a revoked staff account')
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                    checked += 1
        self.assertGreater(checked, 90)

    def test_reactivation_can_revive_an_existing_unexpired_session(self):
        # This demonstrates an unresolved default-backend limitation rather
        # than asserting that deactivation durably revokes every session.
        user = get_user_model().objects.create_user('synthetic-reactivation', password='synthetic-only', is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 200)
        get_user_model().objects.filter(pk=user.pk).update(is_active=False)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 302)
        get_user_model().objects.filter(pk=user.pk).update(is_active=True)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 200)

    def test_regranting_staff_can_reenable_an_existing_unexpired_session(self):
        user = get_user_model().objects.create_user('synthetic-regrant', password='synthetic-only', is_staff=True)
        self.client.force_login(user)
        get_user_model().objects.filter(pk=user.pk).update(is_staff=False)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 403)
        get_user_model().objects.filter(pk=user.pk).update(is_staff=True)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 200)

    def test_password_change_invalidates_an_old_session_after_reactivation(self):
        user = get_user_model().objects.create_user('synthetic-reset', password='synthetic-old', is_staff=True)
        self.client.force_login(user)
        get_user_model().objects.filter(pk=user.pk).update(is_active=False)
        user.set_password('synthetic-new-different-password')
        user.save(update_fields=['password'])
        get_user_model().objects.filter(pk=user.pk).update(is_active=True)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)

    @override_settings(AUTHENTICATION_BACKENDS=['daroobank.test_staff_revocation_boundary.SyntheticPermissiveBackend'])
    def test_deactivated_session_is_denied_even_by_a_permissive_backend(self):
        user = get_user_model().objects.create_user('synthetic-permissive-backend', password='synthetic-only',
                                                    is_staff=True, is_superuser=True)
        self.client.force_login(user)
        get_user_model().objects.filter(pk=user.pk).update(is_active=False)
        checked = 0
        for name, path in self.routes():
            for method in ('get', 'head', 'post'):
                with self.subTest(name=name, method=method):
                    response = getattr(self.client, method)(path)
                    self.assertIn(response.status_code, (403, 405))
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                    checked += 1
        self.assertGreater(checked, 90)

    def test_deactivated_existing_session_is_redirected_by_default_backend(self):
        from urllib.parse import parse_qs, urlsplit

        user = get_user_model().objects.create_user('synthetic-inactive-staff', password='synthetic-only',
                                                    is_staff=True, is_superuser=True)
        self.client.force_login(user)
        get_user_model().objects.filter(pk=user.pk).update(is_active=False)
        checked = 0
        for name, path in self.routes():
            for method in ('get', 'head', 'post'):
                with self.subTest(name=name, method=method):
                    response = getattr(self.client, method)(path)
                    self.assertEqual(response.status_code, 302)
                    location = urlsplit(response['Location'])
                    self.assertEqual((location.scheme, location.netloc, location.path), ('', '', reverse('staff_login')))
                    self.assertEqual(parse_qs(location.query).get('next'), [path])
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                    checked += 1
        self.assertGreater(checked, 90)
