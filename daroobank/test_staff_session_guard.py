"""Durable staff-session invalidation when account state changes; synthetic evidence.

ADR 0191 recorded an unresolved release blocker: a denial observed while `is_active` or
`is_staff` was false did not survive the flag being restored, so an unexpired session
could be revived. `daroobank/session_guard.py` binds each session to a keyed digest of
the account state at login and `StaffSessionGuardMiddleware` compares that digest with
the current state of the account the session names, on every staff request, flushing
the session on any difference.

This suite pins the guarantee and its edges:

* what the fingerprint is sensitive to, and that login really stores it;
* deactivation, staff-flag removal, permission removal, group changes, account deletion
  and a password change each end the session, and restoring the state does not;
* a session that names an account but carries no fingerprint is not trusted;
* the effect is walked across all 41 staff routes behind a positive control;
* the guard is scoped to staff paths, so public reads are untouched;
* the `revoke_staff_sessions` command covers the transition no request observes;
* revocation deletes sessions and touches no domain row.

It is not an account-lifecycle design review: a request that has already passed the
guard still runs to completion, and removing an authentication backend is a settings
change no request-time comparison can observe.
"""
import io
import json
from datetime import timedelta
from types import SimpleNamespace

from django.contrib.auth import BACKEND_SESSION_KEY, SESSION_KEY, get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .session_guard import SESSION_FINGERPRINT_KEY, authorization_fingerprint, session_matches_account
from .test_staff_authorization_matrix import ALL_PERMISSIONS, ROUTES, VIEW_PERMISSIONS
from .test_staff_authorization_objects import COUNTED_MODELS

PASSWORD = 'synthetic-only'
BACKEND = 'django.contrib.auth.backends.ModelBackend'


def permissions_for(pairs):
    return Permission.objects.filter(codename__in=[codename for _app, codename in pairs])


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffSessionGuardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.User = get_user_model()

    def account(self, username='guard-staff', perms=ALL_PERMISSIONS, **kwargs):
        user = self.User.objects.create_user(username, password=PASSWORD, is_staff=True, **kwargs)
        if perms:
            user.user_permissions.add(*permissions_for(perms))
        return user

    def logged_in(self, user):
        client = Client()
        client.force_login(self.User.objects.get(pk=user.pk))
        return client

    def session_of(self, client):
        return client.session

    def assert_dead(self, client, label):
        # `logout` flushes the session store row, so the cookie this client still holds
        # resolves to an empty session rather than to the old account.
        session = self.session_of(client)
        self.assertNotIn(SESSION_KEY, session, f'{label}: the session still names an account')
        self.assertNotIn(SESSION_FINGERPRINT_KEY, session, f'{label}: the fingerprint survived')
        self.assertNotIn(BACKEND_SESSION_KEY, session, f'{label}: the backend binding survived')

    def assert_working(self, client, label):
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 200, label)

    def test_login_binds_a_digest_of_the_accounts_current_state(self):
        user = self.account()
        client = self.logged_in(user)
        stored = self.session_of(client)[SESSION_FINGERPRINT_KEY]
        self.assertEqual(stored, authorization_fingerprint(user.pk))
        self.assertRegex(stored, r'\A[0-9a-f]{64}\Z')
        # The digest is sensitive to every part of the state that authorizes access.
        seen = {stored}
        User = self.User
        for label, change in (
            ('is_active', lambda u: User.objects.filter(pk=u.pk).update(is_active=False)),
            ('is_staff', lambda u: User.objects.filter(pk=u.pk).update(is_staff=False)),
            ('password', lambda u: self.set_password(u)),
            ('is_superuser', lambda u: User.objects.filter(pk=u.pk).update(is_superuser=True)),
        ):
            with self.subTest(change=label):
                change(User.objects.get(pk=user.pk))
                digest = authorization_fingerprint(user.pk)
                self.assertNotIn(digest, seen, f'{label} did not change the digest')
                seen.add(digest)
        # Effective access is what matters, not the rows behind it: a superuser holds
        # every permission whatever its own grants say, so clearing them changes
        # nothing and deliberately does not end a session.
        superuser_digest = authorization_fingerprint(user.pk)
        User.objects.get(pk=user.pk).user_permissions.clear()
        self.assertEqual(authorization_fingerprint(user.pk), superuser_digest)

        # Permission and group changes are measured on an account that is not a
        # superuser, where they really do change effective access.
        member = self.account('guard-perm-sensitive', perms=ALL_PERMISSIONS)
        baseline = authorization_fingerprint(member.pk)
        self.assertNotIn(baseline, seen)
        changes = {baseline}
        for label, change in (
            ('one direct permission removed',
             lambda: User.objects.get(pk=member.pk).user_permissions.remove(*permissions_for(VIEW_PERMISSIONS)[:1])),
            ('all direct permissions removed', lambda: User.objects.get(pk=member.pk).user_permissions.clear()),
        ):
            with self.subTest(change=label):
                change()
                digest = authorization_fingerprint(member.pk)
                self.assertNotIn(digest, changes, f'{label} did not change the digest')
                changes.add(digest)
        # Joining a group that grants nothing changes no effective permission, so it
        # changes no digest either.
        before_empty = authorization_fingerprint(member.pk)
        Group.objects.create(name='guard-empty').user_set.add(member)
        self.assertEqual(authorization_fingerprint(member.pk), before_empty)
        # A group's permissions reach every member's digest without naming the group.
        group = Group.objects.create(name='guard-grant')
        group.user_set.add(member)
        before = authorization_fingerprint(member.pk)
        group.permissions.add(*permissions_for(VIEW_PERMISSIONS))
        self.assertNotEqual(authorization_fingerprint(member.pk), before)
        # A missing account has no digest at all.
        self.assertIsNone(authorization_fingerprint(999_999_999))
        self.assertIsNone(authorization_fingerprint('not-an-int'))
        self.assertIsNone(authorization_fingerprint(0))

    def set_password(self, user):
        fresh = self.User.objects.get(pk=user.pk)
        fresh.set_password('a-different-synthetic-password')
        fresh.save(update_fields=['password'])

    def test_deactivation_ends_the_session_and_reactivation_does_not_restore_it(self):
        user = self.account('guard-deactivated')
        client = self.logged_in(user)
        self.assert_working(client, 'before')
        self.User.objects.filter(pk=user.pk).update(is_active=False)
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 302)
        self.assert_dead(client, 'deactivated')
        self.assertEqual(Session.objects.count(), 0, 'the session row was not deleted')
        self.User.objects.filter(pk=user.pk).update(is_active=True)
        # The cookie the client still holds resolves to nothing.
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 302)
        self.assert_dead(client, 'reactivated')
        # The account itself is intact and can authenticate again.
        restored = self.User.objects.get(pk=user.pk)
        self.assertTrue(restored.is_active and restored.is_staff)
        self.assert_working(self.logged_in(restored), 'fresh login')

    def test_removing_the_staff_flag_or_a_permission_ends_the_session(self):
        for label, revoke in (
            ('is_staff', lambda pk: self.User.objects.filter(pk=pk).update(is_staff=False)),
            ('permission', lambda pk: self.User.objects.get(pk=pk).user_permissions.clear()),
            ('one permission', lambda pk: self.User.objects.get(pk=pk).user_permissions.remove(
                *permissions_for(VIEW_PERMISSIONS)[:1])),
        ):
            with self.subTest(revoked=label):
                user = self.account(f'guard-{label.replace(" ", "-").replace("_", "-")}')
                client = self.logged_in(user)
                self.assert_working(client, f'{label} before')
                revoke(user.pk)
                self.assertEqual(client.get(reverse('staff_workspace')).status_code, 302, label)
                self.assert_dead(client, label)
                # Restoring the state does not restore the session.
                if label == 'is_staff':
                    self.User.objects.filter(pk=user.pk).update(is_staff=True)
                else:
                    self.User.objects.get(pk=user.pk).user_permissions.add(*permissions_for(ALL_PERMISSIONS))
                self.assertEqual(client.get(reverse('staff_workspace')).status_code, 302, f'{label} regrant')

    def test_a_group_change_ends_every_member_session(self):
        group = Group.objects.create(name='guard-reviewers')
        group.permissions.add(*permissions_for(VIEW_PERMISSIONS))
        first = self.User.objects.create_user('guard-member-one', password=PASSWORD, is_staff=True)
        second = self.User.objects.create_user('guard-member-two', password=PASSWORD, is_staff=True)
        group.user_set.add(first, second)
        clients = [self.logged_in(first), self.logged_in(second)]
        for client in clients:
            self.assertEqual(client.get(reverse('staff_prices')).status_code, 200, 'positive control')
        group.permissions.clear()
        for client in clients:
            self.assertEqual(client.get(reverse('staff_prices')).status_code, 302)
            self.assert_dead(client, 'group permissions cleared')
        # Removing a member from the group is a change to that member's state too.
        group.permissions.add(*permissions_for(VIEW_PERMISSIONS))
        member = self.User.objects.create_user('guard-member-three', password=PASSWORD, is_staff=True)
        group.user_set.add(member)
        client = self.logged_in(member)
        self.assertEqual(client.get(reverse('staff_prices')).status_code, 200)
        group.user_set.remove(member)
        self.assertEqual(client.get(reverse('staff_prices')).status_code, 302)
        self.assert_dead(client, 'removed from group')

    def test_deleting_the_account_ends_the_session(self):
        user = self.account('guard-deleted')
        client = self.logged_in(user)
        self.assert_working(client, 'before')
        self.User.objects.filter(pk=user.pk).delete()
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 302)
        self.assert_dead(client, 'deleted')

    def test_a_password_change_ends_the_session_without_any_flag_changing(self):
        user = self.account('guard-password')
        client = self.logged_in(user)
        self.assert_working(client, 'before')
        self.set_password(user)
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 302)
        self.assert_dead(client, 'password changed')
        # Django's own session-auth hash would have produced the same answer here; the
        # guard does not depend on it, and the flags are unchanged.
        unchanged = self.User.objects.get(pk=user.pk)
        self.assertTrue(unchanged.is_active and unchanged.is_staff)

    def test_a_session_without_a_fingerprint_is_not_trusted(self):
        user = self.account('guard-unbound')
        client = self.logged_in(user)
        self.assert_working(client, 'before')
        session = client.session
        del session[SESSION_FINGERPRINT_KEY]
        session.save()
        # Nothing about the account changed, yet an unbound session is ended rather
        # than trusted: this is the shape a pre-guard session would have.
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 302)
        self.assert_dead(client, 'unbound')
        self.assert_working(self.logged_in(self.User.objects.get(pk=user.pk)), 'fresh login')

    def test_the_comparison_rejects_a_session_it_cannot_bind_to_an_account(self):
        # Unit level, because over HTTP a non-integer `_auth_user_id` is rejected inside
        # Django's own AuthenticationMiddleware before this guard runs.
        user = self.account('guard-unreadable')
        store = SessionStore()
        self.assertTrue(session_matches_account(SimpleNamespace(session=store)),
                        'a session that names nobody has nothing to guard')
        self.assertTrue(session_matches_account(SimpleNamespace()), 'a request without a session is not guarded')
        store[SESSION_KEY] = 'not-an-integer'
        self.assertFalse(session_matches_account(SimpleNamespace(session=store)))
        store[SESSION_KEY] = '999999999'
        self.assertFalse(session_matches_account(SimpleNamespace(session=store)), 'a missing account')
        store[SESSION_KEY] = str(user.pk)
        self.assertFalse(session_matches_account(SimpleNamespace(session=store)), 'a named account, no fingerprint')
        store[SESSION_FINGERPRINT_KEY] = 'not-a-digest'
        self.assertFalse(session_matches_account(SimpleNamespace(session=store)), 'a malformed fingerprint')
        store[SESSION_FINGERPRINT_KEY] = authorization_fingerprint(user.pk)
        self.assertTrue(session_matches_account(SimpleNamespace(session=store)))
        self.User.objects.filter(pk=user.pk).update(is_active=False)
        self.assertFalse(session_matches_account(SimpleNamespace(session=store)))

    def test_every_staff_route_denies_a_revoked_session(self):
        user = self.account('guard-walk')
        client = self.logged_in(user)
        before = {}
        for name, kwargs, _method, _requirement in ROUTES:
            url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
            before[name] = client.get(url).status_code
        self.assertEqual(len(before), 41)
        self.assertNotIn(302, before.values(),
                         'A fully permitted account must not be redirected anywhere; the control is vacuous')
        self.User.objects.filter(pk=user.pk).update(is_active=False)
        login = reverse('staff_login')
        after = {}
        for name, kwargs, _method, _requirement in ROUTES:
            url = reverse(name, kwargs=kwargs) if kwargs else reverse(name)
            response = client.get(url)
            after[name] = response.status_code
            self.assertEqual(response.status_code, 302, name)
            self.assertTrue(response['Location'].startswith(login), response['Location'])
        self.assertEqual(len(after), 41)
        self.assertEqual(set(after.values()), {302})

    def test_public_read_paths_are_not_guarded(self):
        user = self.account('guard-public')
        client = self.logged_in(user)
        self.User.objects.filter(pk=user.pk).update(is_staff=False)
        # The guard is scoped to staff paths, so a public read neither pays the
        # comparison nor ends the session; the next staff request does.
        anonymous = Client()
        for name in ('home', 'search', 'prices', 'about', 'openapi_document'):
            url = reverse(name)
            with self.subTest(route=name):
                self.assertEqual(client.get(url).status_code, anonymous.get(url).status_code,
                                 f'{name}: a stale session changed a public answer')
        self.assertIn(SESSION_KEY, client.session)
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 302)
        self.assert_dead(client, 'staff path after public reads')

    @override_settings(DEBUG=True)
    def test_the_revoke_command_deletes_only_what_it_is_asked_to(self):
        target = self.account('guard-command-target')
        other = self.account('guard-command-other')
        target_client, other_client = self.logged_in(target), self.logged_in(other)
        self.assert_working(target_client, 'target before')
        self.assert_working(other_client, 'other before')
        self.assertEqual(Session.objects.count(), 2)

        # Read-only by default: it reports without deleting.
        out = io.StringIO()
        call_command('revoke_staff_sessions', '--username', 'guard-command-target', stdout=out)
        report = json.loads(out.getvalue())
        self.assertEqual(report['applied'], False)
        self.assertEqual(report['matched'], 1)
        self.assertEqual(report['revoked'], 0)
        self.assertEqual(Session.objects.count(), 2)
        self.assert_working(target_client, 'inspection must not revoke')

        out = io.StringIO()
        call_command('revoke_staff_sessions', '--username', 'guard-command-target', '--apply', stdout=out)
        report = json.loads(out.getvalue())
        self.assertEqual((report['applied'], report['matched'], report['revoked']), (True, 1, 1))
        self.assertEqual(Session.objects.count(), 1)
        self.assertEqual(target_client.get(reverse('staff_workspace')).status_code, 302)
        self.assert_dead(target_client, 'revoked by command')
        # The unrelated account keeps its session, and a revoked session is not revived
        # by anything the command did.
        self.assert_working(other_client, 'unrelated account')

        # `--all` reaches every unexpired authenticated session, not just one account.
        third = self.account('guard-command-third')
        self.logged_in(third)
        self.assertEqual(Session.objects.count(), 2)
        out = io.StringIO()
        call_command('revoke_staff_sessions', '--all', '--apply', stdout=out)
        report = json.loads(out.getvalue())
        self.assertEqual((report['applied'], report['matched'], report['revoked']), (True, 2, 2))
        self.assertEqual(Session.objects.count(), 0)
        self.assertEqual(other_client.get(reverse('staff_workspace')).status_code, 302)

        # An expired session is not part of the batch.
        self.logged_in(self.User.objects.get(pk=third.pk))
        self.assertEqual(Session.objects.count(), 1)
        Session.objects.update(expire_date=timezone.now() - timedelta(seconds=1))
        out = io.StringIO()
        call_command('revoke_staff_sessions', '--all', '--apply', stdout=out)
        report = json.loads(out.getvalue())
        self.assertEqual((report['matched'], report['revoked']), (0, 0))
        self.assertEqual(Session.objects.count(), 1)

        for args in ([], ['--all', '--username', 'guard-command-other'], ['--username', 'no-such-account'],
                     ['--username', '']):
            with self.subTest(args=args), self.assertRaises(CommandError):
                call_command('revoke_staff_sessions', *args)

    @override_settings(DEBUG=True)
    def test_revocation_touches_no_domain_row(self):
        before = {model: model.objects.count() for model in COUNTED_MODELS}
        sessions_before = Session.objects.count()
        user = self.account('guard-no-writes')
        client = self.logged_in(user)
        self.User.objects.filter(pk=user.pk).update(is_active=False)
        client.get(reverse('staff_workspace'))
        call_command('revoke_staff_sessions', '--all', '--apply', stdout=io.StringIO())
        self.assertEqual({model: model.objects.count() for model in COUNTED_MODELS}, before)
        self.assertEqual(Session.objects.count(), 0)
        self.assertLessEqual(Session.objects.count(), sessions_before)
