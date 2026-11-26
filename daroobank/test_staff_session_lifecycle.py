"""Session lifecycle across the whole staff surface; synthetic evidence.

The write services bind a session hash (ADR 0193–0198) and the login/logout views
are covered where they live, but nothing pinned what an *ended* session means for
every route. This suite drives four lifecycle events and then walks all 41 staff
routes from the authorization matrix:

* an explicit logout;
* replaying the pre-logout session cookie;
* a password change behind the session's back;
* a session whose expiry is forced into the past.

Each walk is preceded by a positive control proving the same session did reach
protected content moments earlier, so a blanket redirect cannot pass vacuously. The
walks use the matrix's declared arguments, because an ended session is redirected
before any route argument is looked at; the positive control uses a real row.

It records current behavior on a development-only portal with synthetic data. It is
not a session-management review, and ADR 0191 remains an open release blocker: a
deactivated-and-reactivated account, or a credential change that does not touch the
password field, is outside what these walks prove.
"""
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .test_staff_authorization_matrix import ALL_PERMISSIONS, ROUTES
from .test_staff_authorization_objects import COUNTED_MODELS, build_object_rows

LOGIN = 'staff_login'
LOGOUT = 'staff_logout'
PASSWORD = 'synthetic-only'


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffSessionLifecycleTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user('lifecycle-staff', password=PASSWORD, is_staff=True)
        cls.staff.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        author = User.objects.create_user('lifecycle-author', password=PASSWORD, is_staff=True)
        author.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        cls.rows = build_object_rows(author)

    def login(self):
        client = Client()
        self.assertTrue(client.login(username='lifecycle-staff', password=PASSWORD))
        return client

    def login_forced(self):
        # Credential-free login for the walks that only need a live session; the
        # password-changing case below would otherwise break the next login.
        client = Client()
        client.force_login(get_user_model().objects.get(pk=self.staff.pk))
        return client

    def session_key(self, client):
        return client.cookies['sessionid'].value

    def token_for(self, client):
        self.assertEqual(client.get(reverse(LOGIN)).status_code, 200)
        return client.cookies['csrftoken'].value

    def logout(self, client):
        response = client.post(reverse(LOGOUT), {'csrfmiddlewaretoken': self.token_for(client)})
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('home'), response['Location'])
        return response

    def assert_working(self, client, label):
        """Positive control: this session reaches protected content right now."""
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 200, label)
        detail = client.get(reverse('staff_source_detail', kwargs={'pk': self.rows.claim.pk}))
        self.assertEqual(detail.status_code, 200, label)
        self.assertIn('no-store', detail['Cache-Control'])

    def walk(self, client, label):
        """Every staff route must send this client to the login page."""
        login = reverse(LOGIN)
        for name, kwargs, _method, _requirement in ROUTES:
            url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
            with self.subTest(case=label, route=name):
                response = client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response['Location'].startswith(login), response['Location'])
                self.assertIn('no-store', response['Cache-Control'])
                self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    def counts(self):
        return {model: model.objects.count() for model in COUNTED_MODELS}

    def test_the_walk_covers_every_matrix_route(self):
        self.assertEqual(len(ROUTES), 41)
        self.assertEqual(len({name for name, _kwargs, _method, _requirement in ROUTES}), 41)
        self.assertNotIn(LOGIN, {name for name, _kwargs, _method, _requirement in ROUTES})
        self.assertNotIn(LOGOUT, {name for name, _kwargs, _method, _requirement in ROUTES})

    def test_an_explicit_logout_ends_access_to_every_staff_route(self):
        client = self.login()
        self.assert_working(client, 'before logout')
        self.logout(client)
        self.walk(client, 'after logout')
        # The login page stays reachable and logout remains POST-only.
        self.assertEqual(client.get(reverse(LOGIN)).status_code, 200)
        self.assertEqual(client.get(reverse(LOGOUT)).status_code, 405)

    def test_a_pre_logout_session_cookie_cannot_be_replayed(self):
        client = self.login()
        self.assert_working(client, 'before logout')
        stolen = self.session_key(client)
        self.assertTrue(Session.objects.filter(session_key=stolen).exists())
        self.logout(client)
        self.assertFalse(Session.objects.filter(session_key=stolen).exists(),
                         'Logout must delete the session row, not merely clear the cookie.')
        replay = Client()
        replay.cookies['sessionid'] = stolen
        self.walk(replay, 'replayed cookie')

    def test_a_password_change_invalidates_the_existing_session_on_every_route(self):
        client = self.login()
        self.assert_working(client, 'before the password change')
        key = self.session_key(client)
        account = get_user_model().objects.get(pk=self.staff.pk)
        account.set_password('a-different-synthetic-passphrase')
        account.save(update_fields=['password'])
        self.walk(client, 'after the password change')
        # The account itself is untouched: only the credential binding broke.
        reloaded = get_user_model().objects.get(pk=self.staff.pk)
        self.assertTrue(reloaded.is_active and reloaded.is_staff)
        self.assertEqual(reloaded.user_permissions.count(), len(ALL_PERMISSIONS))
        fresh = Client()
        self.assertTrue(fresh.login(username='lifecycle-staff', password='a-different-synthetic-passphrase'))
        self.assert_working(fresh, 'a new session with the new password')
        replay = Client()
        replay.cookies['sessionid'] = key
        self.assertEqual(replay.get(reverse('staff_workspace')).status_code, 302)

    def test_an_expired_session_is_denied_every_staff_route(self):
        client = self.login()
        self.assert_working(client, 'before expiry')
        key = self.session_key(client)
        Session.objects.filter(session_key=key).update(expire_date=timezone.now() - timedelta(seconds=1))
        self.walk(client, 'after expiry')
        revived = Client()
        revived.cookies['sessionid'] = key
        self.assertEqual(revived.get(reverse('staff_workspace')).status_code, 302)

    def test_the_documented_session_settings_are_the_configured_ones(self):
        self.assertEqual(settings.SESSION_COOKIE_AGE, 3600)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')

    def test_lifecycle_walks_write_nothing(self):
        before = self.counts()
        for label in ('logout', 'replay', 'password', 'expiry'):
            client = self.login_forced()
            key = self.session_key(client)
            if label in ('logout', 'replay'):
                self.logout(client)
            if label == 'replay':
                replay = Client()
                replay.cookies['sessionid'] = key
                client = replay
            elif label == 'password':
                account = get_user_model().objects.get(pk=self.staff.pk)
                account.set_password('another-synthetic-passphrase')
                account.save(update_fields=['password'])
            elif label == 'expiry':
                Session.objects.filter(session_key=key).update(
                    expire_date=timezone.now() - timedelta(seconds=1))
            self.walk(client, label)
        self.assertEqual(self.counts(), before)
