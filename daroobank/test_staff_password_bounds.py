"""Development staff password form boundary, not an HTTP request size limit."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .forms import StaffAuthenticationForm


class PasswordBoundFormTests(SimpleTestCase):
    def test_boundary_and_generic_error_before_backend(self):
        for size in (4096, 4097, 10000):
            with self.subTest(size=size):
                password = 'synthetic-canary-' + 'x' * (size - len('synthetic-canary-'))
                form = StaffAuthenticationForm(data={'username': 'synthetic-user', 'password': password})
                with patch('django.contrib.auth.forms.authenticate', return_value=None) as authenticate:
                    self.assertFalse(form.is_valid())
                self.assertEqual(authenticate.call_count, 1 if size == 4096 else 0)
                self.assertEqual(form.errors.as_data()['__all__'][0].code, 'invalid_login')
                self.assertIsNone(form.get_user())
                self.assertNotIn(password, form.errors.as_text())

    def test_prefix_and_disabled_field_use_cleaned_server_value(self):
        data = QueryDict('', mutable=True)
        data.update({'p-username': 'synthetic-user', 'p-password': 'x' * 4097})
        form = StaffAuthenticationForm(data=data, prefix='p', initial={'password': 'server-only'})
        form.fields['password'].disabled = True
        with patch('django.contrib.auth.forms.authenticate', return_value=None) as authenticate:
            self.assertFalse(form.is_valid())
        self.assertEqual(authenticate.call_args.kwargs['password'], 'server-only')


@override_settings(STAFF_PORTAL_ENABLED=True)
class PasswordBoundHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('synthetic-user', password='synthetic-password', is_staff=True)

    def test_oversized_does_not_authenticate_or_replace_session(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = reverse('staff_login')
        client.get(url)
        secret = 'private-password-canary-' + 'x' * 4097
        with patch('django.contrib.auth.forms.authenticate', side_effect=AssertionError('backend reached')):
            response = client.post(url, {'username': 'synthetic-user', 'password': secret},
                                   HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].errors.as_data()['__all__'][0].code, 'invalid_login')
        self.assertNotContains(response, secret)
        self.assertNotContains(response, 'private-password-canary-')
        self.assertEqual(str(client.session['_auth_user_id']), str(self.user.pk))
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')


@override_settings(STAFF_PORTAL_ENABLED=True, STAFF_LOGIN_THROTTLE_ENABLED=True)
class PasswordBoundThrottleTests(TransactionTestCase):
    def test_oversized_attempt_counts_once_when_throttle_enabled(self):
        from staff_security.models import StaffLoginWindow
        client = Client(enforce_csrf_checks=True)
        url = reverse('staff_login')
        client.get(url)
        with patch('django.contrib.auth.forms.authenticate', side_effect=AssertionError('backend reached')):
            response = client.post(url, {'username': 'synthetic-user', 'password': 'x' * 4097},
                                   HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StaffLoginWindow.objects.get().attempts, 1)
        self.assertNotIn('_auth_user_id', client.session)
