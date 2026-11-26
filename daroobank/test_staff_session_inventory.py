"""Read-only inspection of synthetic staff sessions; no credential material is emitted.

`list_staff_sessions` exists because the session guard can only act when a request
arrives: a dormant session left behind by a transition nobody observed is invisible to
it, and `revoke_staff_sessions` needs somewhere to aim. This suite pins the report's
shape, that it exposes no session material, that it names the sessions the guard would
end, and that it changes nothing.
"""
import io
import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from staff_security.management.commands.list_staff_sessions import session_alias

from .session_guard import SESSION_FINGERPRINT_KEY
from .test_staff_authorization_matrix import ALL_PERMISSIONS
from .test_staff_authorization_objects import COUNTED_MODELS

PASSWORD = 'synthetic-only'


@override_settings(STAFF_PORTAL_ENABLED=True, DEBUG=True)
class StaffSessionInventoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.User = get_user_model()

    def account(self, username, **kwargs):
        user = self.User.objects.create_user(username, password=PASSWORD, is_staff=True, **kwargs)
        user.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        return user

    def login(self, username):
        client = Client()
        client.force_login(self.User.objects.get(username=username))
        return client

    def report(self, *args):
        out = io.StringIO()
        call_command('list_staff_sessions', *args, stdout=out)
        return out.getvalue(), json.loads(out.getvalue())

    def test_the_report_lists_each_account_and_its_sessions(self):
        first = self.account('inventory-first')
        second = self.account('inventory-second', is_superuser=True)
        self.login('inventory-first')
        self.login('inventory-first')
        self.login('inventory-second')
        self.assertEqual(Session.objects.count(), 3)
        _raw, report = self.report()
        self.assertEqual(report['scanned'], 3)
        self.assertEqual(report['sessions_matched'], 3)
        self.assertEqual(report['sessions_unbound'], 0)
        self.assertEqual([row['username'] for row in report['accounts']], ['inventory-first', 'inventory-second'])
        self.assertEqual([row['session_count'] for row in report['accounts']], [2, 1])
        by_name = {row['username']: row for row in report['accounts']}
        self.assertEqual(by_name['inventory-first']['account_id'], str(first.pk))
        self.assertEqual((by_name['inventory-first']['is_active'], by_name['inventory-first']['is_staff']),
                         (True, True))
        self.assertTrue(by_name['inventory-second']['is_superuser'])
        for row in report['accounts']:
            for session in row['sessions']:
                self.assertEqual(session['bound'], True)
                self.assertEqual(session['guard_would_end_it'], False, 'a current session must not be flagged')
                self.assertLess(timezone.now().isoformat(), session['expires_at'])

    def test_the_report_never_contains_session_material(self):
        self.account('inventory-secret')
        client = self.login('inventory-secret')
        keys = list(Session.objects.values_list('session_key', flat=True))
        self.assertEqual(len(keys), 1)
        raw, report = self.report()
        session = report['accounts'][0]['sessions'][0]
        for secret in keys + [client.cookies['sessionid'].value]:
            with self.subTest(secret='a session identifier'):
                self.assertNotIn(secret, raw, 'the report leaked a usable session identifier')
        self.assertEqual(session['alias'], session_alias(keys[0]))
        self.assertRegex(session['alias'], r'\A[0-9a-f]{32}\Z')
        self.assertNotEqual(session['alias'], keys[0])
        # Aliases are stable, so two reports can be compared, and distinct per session.
        self.assertEqual(session_alias(keys[0]), session_alias(keys[0]))
        self.assertNotEqual(session_alias(keys[0]), session_alias(keys[0] + 'x'))
        self.assertNotIn(client.session[SESSION_FINGERPRINT_KEY], raw,
                         'the report must not echo the stored digest')

    def test_a_dormant_session_is_named_as_one_the_guard_would_end(self):
        # The ADR 0213 residual, made visible: no request arrived, so the session row is
        # still there, and the report is what tells an operator to revoke it.
        self.account('inventory-dormant')
        self.login('inventory-dormant')
        _raw, before = self.report()
        self.assertEqual(before['accounts'][0]['sessions'][0]['guard_would_end_it'], False)
        self.User.objects.filter(username='inventory-dormant').update(is_active=False)
        _raw, after = self.report()
        row = after['accounts'][0]
        self.assertEqual(row['is_active'], False)
        self.assertEqual(row['session_count'], 1, 'the session row is still in the store')
        self.assertEqual(row['sessions'][0]['guard_would_end_it'], True)
        # A revoked account's session leaves the report, and the account with it.
        out = io.StringIO()
        call_command('revoke_staff_sessions', '--username', 'inventory-dormant', '--apply', stdout=out)
        self.assertEqual(json.loads(out.getvalue())['revoked'], 1)
        _raw, cleared = self.report()
        self.assertEqual(cleared['accounts'], [])
        self.assertEqual(cleared['sessions_matched'], 0)

    def test_an_unbound_or_unreadable_session_is_not_trusted_in_the_report(self):
        self.account('inventory-unbound')
        client = self.login('inventory-unbound')
        session = client.session
        del session[SESSION_FINGERPRINT_KEY]
        session.save()
        _raw, report = self.report()
        self.assertEqual(report['sessions_unbound'], 1)
        listed = report['accounts'][0]['sessions'][0]
        self.assertEqual((listed['bound'], listed['guard_would_end_it']), (False, True))
        # A session can outlive its account: the row stays, marked as belonging to no
        # account, and is one the guard would end.
        self.User.objects.filter(username='inventory-unbound').delete()
        _raw, report = self.report()
        self.assertEqual(report['scanned'], 1)
        self.assertEqual(len(report['accounts']), 1)
        orphan = report['accounts'][0]
        self.assertEqual((orphan['account_exists'], orphan['username']), (False, None))
        self.assertEqual((orphan['is_active'], orphan['is_staff']), (None, None))
        self.assertEqual(orphan['sessions'][0]['guard_would_end_it'], True)

    def test_expired_sessions_are_not_listed(self):
        self.account('inventory-expired')
        self.login('inventory-expired')
        Session.objects.update(expire_date=timezone.now() - timedelta(seconds=1))
        _raw, report = self.report()
        self.assertEqual((report['scanned'], report['sessions_matched'], report['accounts']), (0, 0, []))

    def test_the_username_filter_and_its_errors(self):
        self.account('inventory-kept')
        self.account('inventory-hidden')
        self.login('inventory-kept')
        self.login('inventory-hidden')
        _raw, report = self.report('--username', 'inventory-hidden')
        self.assertEqual(report['username'], 'inventory-hidden')
        self.assertEqual([row['username'] for row in report['accounts']], ['inventory-hidden'])
        self.assertEqual(report['sessions_matched'], 1)
        self.assertEqual(report['scanned'], 2, 'the whole store was still scanned')
        with self.assertRaises(CommandError):
            call_command('list_staff_sessions', '--username', 'no-such-account')
        with self.assertRaises(CommandError):
            call_command('list_staff_sessions', '--username', '')

    def test_the_command_is_read_only_and_repeatable(self):
        self.account('inventory-readonly')
        self.login('inventory-readonly')
        domains_before = {model: model.objects.count() for model in COUNTED_MODELS}
        sessions_before = Session.objects.count()
        first, _report = self.report()
        second, _report = self.report()
        self.assertEqual(first, second, 'two inspections of an unchanged store must agree byte for byte')
        self.assertEqual(Session.objects.count(), sessions_before)
        self.assertEqual({model: model.objects.count() for model in COUNTED_MODELS}, domains_before)
