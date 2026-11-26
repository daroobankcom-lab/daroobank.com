"""Selected staff authorization checks after a staff flag is revoked.

The two tests that used to demonstrate the ADR 0191 revival gap now assert the
opposite, because `daroobank/session_guard.py` ends a session the first time it is
presented while the account differs from the state the session was bound to.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import AllowAllUsersModelBackend
from django.test import Client, TestCase, override_settings
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
                    self.assertEqual(response.status_code, 302, f'{name} unexpectedly allowed a revoked staff account')
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                    checked += 1
        self.assertGreater(checked, 90)
        # Denied by losing the session, not by a per-request permission check, so
        # restoring the flag has nothing to revive.
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_revoked_staff_posts_with_valid_csrf_do_not_write_selected_models(self):
        from catalog.models import IngredientDraft, ProductCandidate
        from clinical.models import ClinicalDraft
        from pricing.models import PriceCandidate
        from sources.models import SourceClaim

        user = get_user_model().objects.create_user('synthetic-revoked-csrf', password='synthetic-only',
                                                    is_staff=True, is_superuser=True)
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        self.assertEqual(client.get(reverse('staff_login')).status_code, 200)
        csrf = client.cookies['csrftoken'].value
        get_user_model().objects.filter(pk=user.pk).update(is_staff=False)
        models = (IngredientDraft, ProductCandidate, ClinicalDraft, PriceCandidate, SourceClaim)
        before = [model.objects.count() for model in models]
        routes = (('staff_identity_create', {'kind': 'ingredient'}), ('staff_product_upload', {}),
                  ('staff_price_upload', {}), ('staff_clinical_create', {}), ('staff_source_create', {}))
        # Negative control: confirm CSRF enforcement is actually in this stack.
        from django.http import HttpResponseForbidden
        with patch('django.middleware.csrf.CsrfViewMiddleware._reject', autospec=True,
                   return_value=HttpResponseForbidden('synthetic csrf rejection')) as reject:
            response = client.post(reverse('staff_product_upload'), {}, HTTP_X_CSRFTOKEN='bad')
            self.assertEqual(response.status_code, 403)
            reject.assert_called_once()
        for name, kwargs in routes:
            with self.subTest(name=name), patch('django.middleware.csrf.CsrfViewMiddleware._reject',
                                                side_effect=AssertionError('CSRF was not accepted')):
                response = client.post(reverse(name, kwargs=kwargs), {}, HTTP_X_CSRFTOKEN=csrf)
                # The token is accepted and the request is still refused: the session
                # was ended, so the write route answers an anonymous caller.
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual([model.objects.count() for model in models], before)

    def test_reactivation_does_not_revive_an_existing_session(self):
        # ADR 0191 recorded the opposite as an open release blocker: the denial seen
        # while the flag was off did not survive the flag being restored.
        user = get_user_model().objects.create_user('synthetic-reactivation', password='synthetic-only', is_staff=True)
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 200)
        get_user_model().objects.filter(pk=user.pk).update(is_active=False)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)
        get_user_model().objects.filter(pk=user.pk).update(is_active=True)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 302)
        # The account kept its flags and can authenticate again; only the old session
        # was destroyed.
        refreshed = get_user_model().objects.get(pk=user.pk)
        self.assertTrue(refreshed.is_active and refreshed.is_staff)
        self.client.force_login(refreshed)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 200)

    def test_regranting_staff_does_not_reenable_an_existing_session(self):
        user = get_user_model().objects.create_user('synthetic-regrant', password='synthetic-only', is_staff=True)
        self.client.force_login(user)
        get_user_model().objects.filter(pk=user.pk).update(is_staff=False)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 302)
        self.assertNotIn('_auth_user_id', self.client.session)
        get_user_model().objects.filter(pk=user.pk).update(is_staff=True)
        self.assertEqual(self.client.get(reverse('staff_workspace')).status_code, 302)
        self.client.force_login(get_user_model().objects.get(pk=user.pk))
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
                    # The backend would keep this user authenticated; the session guard
                    # ends the session first, so every route answers an anonymous caller.
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                    checked += 1
        self.assertGreater(checked, 90)
        self.assertNotIn('_auth_user_id', self.client.session)

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
