"""The deployment readiness report must discriminate, and must not overclaim.

`check_deployment_readiness` collects the settings and database conditions a deployment
has to get right into one JSON report, because `health/ready/` answers only "can this
process run a SELECT" and the non-debug startup checks only refuse to boot. This suite
pins three things: that a hardened configuration reports ready, that the development
configuration reports not ready and says which checks failed, and that **every** required
check can fail on its own — a readiness report whose checks cannot fail is decoration.

It also pins what the report refuses to claim: no secret material in the output, an
explicit scope line, review items that stay open even in a hardened configuration, and no
writes of any kind.
"""
import io
import json
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from django.core.management import call_command
from django.db import connection, connections, transaction
from django.test import TransactionTestCase, override_settings

from daroobank.management.commands import check_deployment_readiness
from daroobank.management.commands.check_deployment_readiness import (CLICKJACKING_MIDDLEWARE, REQUIRED, SCOPE,
                                                                      Command, readiness_report)
from .test_staff_authorization_objects import COUNTED_MODELS

PROBE_PREFIX = 'daroobank_readiness_probe_'
SYNTHETIC_SECRET = 'synthetic-readiness-probe-secret-key-0123456789abcdef'

# A configuration that passes every required check and leaves no review item. It is a
# test fixture, not a recommended production profile: TLS issuance, proxy topology,
# monitoring and MFA are all still open gates.
HARDENED = {
    'DEBUG': False,
    'STAFF_PORTAL_ENABLED': False,
    'SECRET_KEY': SYNTHETIC_SECRET,
    'ALLOWED_HOSTS': ['example.org'],
    'SESSION_COOKIE_SECURE': True,
    'CSRF_COOKIE_SECURE': True,
    'SECURE_SSL_REDIRECT': True,
    'SECURE_PROXY_SSL_HEADER': ('HTTP_X_FORWARDED_PROTO', 'https'),
    'SECURE_HSTS_SECONDS': 31_536_000,
    'HEALTH_PROBES_ENABLED': False,
    'STAFF_LOGIN_THROTTLE_ENABLED': False,
}

# One setting change per required check, each of which must fail that check alone.
BREAKS = {
    'debug_disabled': {'DEBUG': True},
    'staff_portal_disabled': {'STAFF_PORTAL_ENABLED': True},
    'secret_key_shape': {'SECRET_KEY': 'django-insecure-short'},
    'allowed_hosts_explicit': {'ALLOWED_HOSTS': ['*']},
    'cookies_secure': {'SESSION_COOKIE_SECURE': False},
    'session_flags': {'SESSION_COOKIE_AGE': 86_400},
    'ssl_redirect_enabled': {'SECURE_SSL_REDIRECT': False},
}


@contextmanager
def throwaway_database():
    """An isolated PostgreSQL database, registered dynamically and dropped again."""
    name = PROBE_PREFIX + uuid4().hex[:12]
    alias = 'readiness_probe'
    default = connections['default']
    settings_dict = {**default.settings_dict, 'NAME': name, 'TEST': {'NAME': name}}
    with default.cursor() as cursor:
        cursor.execute(f'CREATE DATABASE {default.ops.quote_name(name)}')
    connections[alias] = type(default)(settings_dict, alias)
    try:
        yield alias
    finally:
        probe = connections[alias]
        probe.close()
        del connections[alias]
        with default.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS {default.ops.quote_name(name)} WITH (FORCE)')


class DeploymentReadinessTests(TransactionTestCase):
    def run_command(self, *args):
        out = io.StringIO()
        code = 0
        try:
            call_command('check_deployment_readiness', *args, stdout=out)
        except SystemExit as exit_code:
            code = exit_code.code
        return code, out.getvalue(), json.loads(out.getvalue())

    def test_a_hardened_configuration_reports_ready(self):
        with override_settings(MIDDLEWARE=[*settings_middleware(), CLICKJACKING_MIDDLEWARE]), \
                override_settings(**HARDENED):
            code, raw, report = self.run_command()
        self.assertEqual(code, 0)
        self.assertTrue(report['ready'])
        self.assertEqual(report['failed'], [])
        self.assertEqual([item['id'] for item in report['required'] if not item['passed']], [])
        self.assertEqual(report['review'], [], 'a hardened fixture should leave no review item')
        self.assertEqual(len(report['required']), len(REQUIRED))
        self.assertNotIn(SYNTHETIC_SECRET, raw, 'the report leaked the secret value')
        self.assertNotIn(SYNTHETIC_SECRET[:24], raw)

    def test_the_development_configuration_reports_not_ready_and_names_why(self):
        code, _raw, report = self.run_command()
        self.assertEqual(code, 1)
        self.assertFalse(report['ready'])
        # Django's test runner sets DEBUG=False for the whole suite, so `debug_disabled`
        # cannot fail here; it is covered by the per-check test below. `STAFF_PORTAL_ENABLED`
        # is a separate setting that was computed when the development settings were
        # imported, and it is still on.
        self.assertEqual(report['failed'], ['staff_portal_disabled', 'secret_key_shape',
                                            'cookies_secure', 'ssl_redirect_enabled'])
        passed = {item['id'] for item in report['required'] if item['passed']}
        # The suite's own database is migrated and reachable, so those checks pass here.
        self.assertEqual(passed, {'debug_disabled', 'allowed_hosts_explicit', 'session_flags',
                                  'migrations_applied', 'migration_history_consistent',
                                  'database_reachable'})
        self.assertEqual({item['id'] for item in report['review']},
                         {'hsts_disabled', 'development_hosts', 'clickjacking_middleware_absent'})

    def test_every_required_check_fails_on_its_own(self):
        for check_id, override in sorted(BREAKS.items()):
            with self.subTest(check=check_id):
                with override_settings(MIDDLEWARE=[*settings_middleware(), CLICKJACKING_MIDDLEWARE]), \
                        override_settings(**{**HARDENED, **override}):
                    code, _raw, report = self.run_command()
                self.assertEqual(code, 1)
                self.assertEqual(report['failed'], [check_id],
                                 f'breaking {check_id} should fail exactly that check')

    def test_pending_migrations_fail_the_report(self):
        with throwaway_database() as alias:
            with override_settings(**HARDENED), \
                    patch_connection(connections[alias]):
                code, _raw, report = self.run_command()
        self.assertEqual(code, 1)
        self.assertEqual(report['failed'], ['migrations_applied'])
        detail = next(item['detail'] for item in report['required'] if item['id'] == 'migrations_applied')
        self.assertIn('32 migrations are not applied', detail)

    def test_an_applied_migration_with_no_file_fails_the_report(self):
        with throwaway_database() as alias:
            call_command('migrate', database=alias, interactive=False, verbosity=0)
            with connections[alias].cursor() as cursor:
                cursor.execute("INSERT INTO django_migrations (app, name, applied) VALUES (%s, %s, now())",
                               ['catalog', '0099_never_written'])
            with override_settings(**HARDENED), patch_connection(connections[alias]):
                code, _raw, report = self.run_command()
            with connections[alias].cursor() as cursor:
                cursor.execute("DELETE FROM django_migrations WHERE name = '0099_never_written'")
        self.assertEqual(code, 1)
        self.assertEqual(report['failed'], ['migration_history_consistent'])
        self.assertIn('catalog.0099_never_written',
                      next(item['detail'] for item in report['required']
                           if item['id'] == 'migration_history_consistent'))

    def test_an_unreachable_database_fails_the_report(self):
        # `database_ready` answers false inside an open transaction, which is the documented
        # caveat of the check and a real way for it to fail.
        with override_settings(**HARDENED), transaction.atomic():
            code, _raw, report = self.run_command()
        self.assertEqual(code, 1)
        self.assertEqual(report['failed'], ['database_reachable'])
        self.assertIn('open transaction',
                      next(item['detail'] for item in report['required'] if item['id'] == 'database_reachable'))

    def test_strict_fails_on_review_items_only(self):
        with override_settings(MIDDLEWARE=[*settings_middleware(), CLICKJACKING_MIDDLEWARE]), \
                override_settings(**HARDENED):
            self.assertEqual(self.run_command('--strict')[0], 0)
        with override_settings(MIDDLEWARE=[*settings_middleware(), CLICKJACKING_MIDDLEWARE]), \
                override_settings(**{**HARDENED, 'SECURE_HSTS_SECONDS': 0}):
            code, _raw, report = self.run_command('--strict')
            self.assertEqual(code, 1)
            self.assertTrue(report['ready'], 'a review item is not a failed required check')
            self.assertEqual([item['id'] for item in report['review']], ['hsts_disabled'])
            self.assertEqual(self.run_command()[0], 0, 'without --strict a review item does not fail')

    def test_each_review_condition_appears_with_a_reason(self):
        cases = {
            'hsts_disabled': {'SECURE_HSTS_SECONDS': 0},
            'proxy_scheme_untrusted': {'SECURE_PROXY_SSL_HEADER': None},
            'development_hosts': {'ALLOWED_HOSTS': ['example.org', 'localhost']},
            'health_probes_reachable': {'HEALTH_PROBES_ENABLED': True},
            'synthetic_login_throttle': {'STAFF_LOGIN_THROTTLE_ENABLED': True},
        }
        for review_id, override in sorted(cases.items()):
            with self.subTest(review=review_id):
                with override_settings(MIDDLEWARE=[*settings_middleware(), CLICKJACKING_MIDDLEWARE]), \
                        override_settings(**{**HARDENED, **override}):
                    items = readiness_report()['review']
                self.assertEqual([item['id'] for item in items], [review_id],
                                 'the review conditions are not independent')
                self.assertEqual(set(items[0]), {'id', 'reason'})
                self.assertTrue(items[0]['reason'])
        # The remaining condition is about the middleware list, which the fixture above edits.
        with override_settings(**HARDENED):
            items = readiness_report()['review']
        self.assertEqual([item['id'] for item in items], ['clickjacking_middleware_absent'])

    def test_the_report_shape_is_stable_and_makes_no_claim_it_cannot_support(self):
        with override_settings(**HARDENED):
            first = self.run_command()[1]
            second = self.run_command()[1]
        self.assertEqual(first, second, 'two reports of an unchanged configuration must agree byte for byte')
        report = json.loads(first)
        self.assertEqual(set(report), {'failed', 'ready', 'required', 'review', 'scope'})
        self.assertEqual([item['id'] for item in report['required']], [check_id for check_id, _check in REQUIRED])
        for item in report['required']:
            self.assertEqual(set(item), {'id', 'passed', 'detail'})
        self.assertEqual(report['scope'], SCOPE)
        for phrase in ('not monitoring', 'independent security assessment'):
            self.assertIn(phrase, SCOPE, 'the scope line dropped a statement of its own limits')
        self.assertIn('not a certification', Command.help)
        self.assertIn('zero exit status is not a deployment', check_deployment_readiness.__doc__)

    def test_the_command_is_named_where_an_operator_would_look(self):
        root = Path(__file__).resolve().parent.parent
        for relative in ('docs/DEPLOYMENT.md', 'docs/OPERATIONS_RUNBOOK.md'):
            with self.subTest(document=relative):
                text = (root / relative).read_text(encoding='utf-8')
                self.assertIn('check_deployment_readiness', text)
                self.assertIn('0217-deployment-readiness-report.md', text)

    def test_the_command_writes_nothing(self):
        before = {model: model.objects.count() for model in COUNTED_MODELS}
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM django_migrations')
            migrations_before = cursor.fetchone()[0]
        self.run_command()
        with override_settings(**HARDENED):
            self.run_command('--strict')
        self.assertEqual({model: model.objects.count() for model in COUNTED_MODELS}, before)
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM django_migrations')
            self.assertEqual(cursor.fetchone()[0], migrations_before)
        with connection.cursor() as cursor:
            cursor.execute('SELECT datname FROM pg_database WHERE datname LIKE %s', [PROBE_PREFIX + '%'])
            self.assertEqual([row[0] for row in cursor.fetchall()], [],
                             'a throwaway readiness database was left behind')


def settings_middleware():
    from django.conf import settings
    return list(settings.MIDDLEWARE)


@contextmanager
def patch_connection(probe):
    """Point the command's migration checks at another connection."""
    from unittest import mock

    with mock.patch.object(check_deployment_readiness, 'connection', probe):
        yield
