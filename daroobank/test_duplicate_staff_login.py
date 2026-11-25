"""Repeated staff-login credentials must never be silently collapsed."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import QueryDict
from django.test import Client, SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .forms import StaffAuthenticationForm


class DuplicateLoginFormTests(SimpleTestCase):
    def test_duplicate_credentials_reject_before_authentication_with_prefix(self):
        for field in ('username', 'password'):
            for first, last in (('same', 'same'), ('first-canary', 'last-canary')):
                with self.subTest(field=field, first=first):
                    data = QueryDict('', mutable=True)
                    data.update({'p-username': 'synthetic-user', 'p-password': 'synthetic-password'})
                    data.setlist('p-' + field, [first, last])
                    form = StaffAuthenticationForm(data=data, prefix='p')
                    with patch('django.contrib.auth.forms.authenticate', side_effect=AssertionError('authenticated ambiguous data')):
                        self.assertFalse(form.is_valid())
                    self.assertEqual(form.errors.as_data()['__all__'][0].code, 'invalid_login')
                    self.assertIsNone(form.get_user())
                    self.assertNotIn(first, form.errors.as_text())
                    self.assertNotIn(last, form.errors.as_text())

    def test_disabled_fields_ignore_duplicate_request_values(self):
        data = QueryDict('', mutable=True)
        data.setlist('p-username', ['ignored-one', 'ignored-two'])
        data['p-password'] = 'password'
        form = StaffAuthenticationForm(data=data, prefix='p', initial={'username': 'synthetic-user'})
        form.fields['username'].disabled = True
        with patch('django.contrib.auth.forms.authenticate', return_value=None) as authenticate:
            self.assertFalse(form.is_valid())
        self.assertEqual(authenticate.call_args.kwargs['username'], 'synthetic-user')


@override_settings(STAFF_PORTAL_ENABLED=True)
class DuplicateLoginHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('synthetic-login', password='synthetic-password', is_staff=True)

    def test_csrf_valid_repeated_credentials_do_not_authenticate_or_leak_passwords(self):
        for field, values in (('username', ['other-user', 'synthetic-login']),
                              ('password', ['password-canary-first', 'synthetic-password'])):
            with self.subTest(field=field):
                client = Client(enforce_csrf_checks=True)
                url = reverse('staff_login')
                client.get(url)
                data = QueryDict('', mutable=True)
                data.update({'username': 'synthetic-login', 'password': 'synthetic-password'})
                data.setlist(field, values)
                with patch('django.contrib.auth.forms.authenticate', side_effect=AssertionError('authenticated ambiguous data')):
                    response = client.post(url, data.urlencode(), content_type='application/x-www-form-urlencoded',
                                           HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['form'].errors.as_data()['__all__'][0].code, 'invalid_login')
                self.assertNotIn('_auth_user_id', client.session)
                self.assertNotContains(response, 'synthetic-password')
                self.assertNotContains(response, 'password-canary-first')
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    def test_multipart_duplicate_credentials_are_also_rejected(self):
        client = Client(enforce_csrf_checks=True)
        url = reverse('staff_login')
        client.get(url)
        with patch('django.contrib.auth.forms.authenticate', side_effect=AssertionError('authenticated ambiguous data')):
            response = client.post(url, {'username': 'synthetic-login',
                                        'password': ['first-secret-canary', 'synthetic-password']},
                                   HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'first-secret-canary')
        self.assertNotContains(response, 'synthetic-password')
        self.assertNotIn('_auth_user_id', client.session)

    def test_ambiguous_login_does_not_replace_existing_authenticated_session(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        url = reverse('staff_login')
        client.get(url)
        data = QueryDict('', mutable=True)
        data.update({'username': 'synthetic-login', 'password': 'synthetic-password'})
        data.setlist('username', ['somebody-else', 'synthetic-login'])
        response = client.post(url, data.urlencode(), content_type='application/x-www-form-urlencoded',
                               HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(str(client.session['_auth_user_id']), str(self.user.pk))


@override_settings(STAFF_PORTAL_ENABLED=True, STAFF_LOGIN_THROTTLE_ENABLED=True)
class DuplicateLoginThrottleIntegrationTests(TransactionTestCase):
    def test_duplicate_credentials_consume_one_attempt_without_authentication(self):
        from staff_security.models import StaffLoginWindow
        client = Client(enforce_csrf_checks=True)
        url = reverse('staff_login')
        client.get(url)
        values = QueryDict('', mutable=True)
        values.update({'username': 'synthetic-user', 'password': 'synthetic-password'})
        values.setlist('username', ['other', 'synthetic-user'])
        with patch('django.contrib.auth.forms.authenticate', side_effect=AssertionError('authenticated ambiguous data')):
            response = client.post(url, values.urlencode(), content_type='application/x-www-form-urlencoded',
                                   HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(StaffLoginWindow.objects.get().attempts, 1)
        self.assertNotIn('_auth_user_id', client.session)
