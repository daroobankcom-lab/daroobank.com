"""Staff login remains fail-closed when a backend returns inactive accounts."""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .forms import StaffAuthenticationForm


@override_settings(STAFF_PORTAL_ENABLED=True,
                   AUTHENTICATION_BACKENDS=['django.contrib.auth.backends.AllowAllUsersModelBackend'])
class InactiveBackendStaffLoginTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.inactive = users.objects.create_user('inactive-backend-staff', password='synthetic-passphrase',
                                                 is_staff=True, is_active=False)
        cls.nonstaff = users.objects.create_user('inactive-backend-nonstaff', password='synthetic-passphrase')
        cls.staff = users.objects.create_user('inactive-backend-active', password='synthetic-passphrase', is_staff=True)

    def form(self, user, password='synthetic-passphrase'):
        return StaffAuthenticationForm(data={'username': user.username, 'password': password})

    def test_inactive_backend_result_is_generic_and_form_never_returns_the_user(self):
        inactive, nonstaff, bad = self.form(self.inactive), self.form(self.nonstaff), self.form(self.staff, 'wrong')
        for form in (inactive, nonstaff, bad):
            self.assertFalse(form.is_valid())
            self.assertIsNone(form.get_user())
        self.assertEqual(inactive.errors.as_data()['__all__'][0].code, 'invalid_login')
        self.assertEqual(inactive.errors.as_text(), nonstaff.errors.as_text())
        self.assertEqual(inactive.errors.as_text(), bad.errors.as_text())
        active = self.form(self.staff)
        self.assertTrue(active.is_valid())
        self.assertEqual(active.get_user().pk, self.staff.pk)

    def test_inactive_login_does_not_establish_a_session(self):
        login = reverse('staff_login')
        client = Client()
        response = client.post(login, {'username': self.inactive.username, 'password': 'synthetic-passphrase'})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('_auth_user_id', client.session)
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertNotContains(response, 'This account is inactive')
        invalid = client.post(login, {'username': self.staff.username, 'password': 'wrong'})
        self.assertEqual(response.context['form'].errors.as_text(), invalid.context['form'].errors.as_text())
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 302)

    def test_active_staff_can_log_in_but_still_needs_domain_permission(self):
        client = Client()
        response = client.post(reverse('staff_login'), {'username': self.staff.username, 'password': 'synthetic-passphrase'})
        self.assertRedirects(response, reverse('staff_workspace'), fetch_redirect_response=False)
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 200)
        self.assertEqual(client.get(reverse('staff_clinical_drafts')).status_code, 403)

    def test_already_authenticated_inactive_account_still_cannot_access_workspace(self):
        client = Client()
        client.force_login(self.inactive)
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 403)
