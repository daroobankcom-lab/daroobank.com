"""Selected access observations on an isolated synthetic PostgreSQL database."""
import io
import json
from unittest.mock import patch
from uuid import uuid4

from django.core.management import CommandError, call_command
from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from catalog.models import ProductCandidate, ProductPresentation
from .postgresql_access import inspect_access
from .postgresql_inspection import expected_tables


@override_settings(DEBUG=True)
class PostgreSQLAccessInspectionTests(TransactionTestCase):
    def test_one_read_only_statement_reports_aggregates_without_names(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
            with CaptureQueriesContext(connection) as queries:
                report = inspect_access(expected_tables())
        self.assertEqual(len(queries), 1)
        self.assertTrue(report['transaction_read_only'])
        self.assertEqual(report['expected_relations'], len(expected_tables()))
        self.assertEqual(report['selected_tables'], len(expected_tables()))
        self.assertEqual(report['unresolved_relations'], 0)
        self.assertIn(report['connection_transport'], ('unix_socket', 'tls', 'tcp_without_tls', 'unknown'))
        for key in ('tables_select', 'tables_insert', 'tables_update', 'tables_delete', 'tables_truncate',
                    'tables_rls_enabled', 'tables_rls_forced'):
            self.assertGreaterEqual(report[key], 0)
            self.assertLessEqual(report[key], report['selected_tables'])
        encoded = json.dumps(report)
        self.assertNotIn(ProductPresentation._meta.db_table, encoded)

    def test_role_flags_match_current_postgresql_role(self):
        report = inspect_access([])
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls '
                           'FROM pg_catalog.pg_roles WHERE rolname = current_user')
            observed = cursor.fetchone()
        self.assertEqual(tuple(report[key] for key in ('role_superuser', 'role_create_database',
                         'role_create_roles', 'role_replication', 'role_bypass_rls')), observed)
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls '
                           'FROM pg_catalog.pg_roles WHERE rolname = session_user')
            session = cursor.fetchone()
        self.assertEqual(tuple(report[key] for key in ('session_superuser', 'session_create_database',
                         'session_create_roles', 'session_replication', 'session_bypass_rls')), session)
        self.assertEqual((report['expected_relations'], report['selected_tables']), (0, 0))

    def test_names_are_bound_and_unresolved_or_non_tables_are_not_table_privileges(self):
        name = "missing'); DROP TABLE auth_user; --"
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('CREATE TEMP VIEW synthetic_access_view AS SELECT 1 AS value')
            report = inspect_access([ProductPresentation._meta.db_table, name, 'synthetic_access_view'])
        self.assertEqual(report['expected_relations'], 3)
        self.assertEqual(report['unresolved_relations'], 1)
        self.assertEqual(report['non_table_relations'], 1)
        self.assertEqual(report['selected_tables'], 1)
        self.assertNotIn(name, json.dumps(report))
        self.assertFalse(ProductPresentation.objects.exists())

    def test_rls_flags_are_catalog_clues_not_effective_policy_check(self):
        table = connection.ops.quote_name(ProductPresentation._meta.db_table)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
                cursor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            report = inspect_access([ProductPresentation._meta.db_table])
            self.assertEqual((report['tables_rls_enabled'], report['tables_rls_forced']), (1, 1))
            transaction.set_rollback(True)
        report = inspect_access([ProductPresentation._meta.db_table])
        self.assertEqual((report['tables_rls_enabled'], report['tables_rls_forced']), (0, 0))

    def test_forced_rls_flag_does_not_constrain_a_superuser(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user')
            if not cursor.fetchone()[0]:
                self.skipTest('Synthetic RLS-bypass demonstration requires a disposable superuser')
        ProductPresentation.objects.create(
            name_fa='محصول ساختگی', manufacturer='سازنده', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', source_name='منبع',
            source_url='https://example.org/synthetic')
        table = connection.ops.quote_name(ProductPresentation._meta.db_table)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
                cursor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            report = inspect_access([ProductPresentation._meta.db_table])
            self.assertTrue(report['role_superuser'])
            self.assertEqual((report['tables_rls_enabled'], report['tables_rls_forced']), (1, 1))
            self.assertEqual(ProductPresentation.objects.count(), 1)
            transaction.set_rollback(True)

    def test_table_owner_bypasses_unforced_rls_even_without_a_policy(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user')
            if not cursor.fetchone()[0]:
                self.skipTest('Synthetic RLS owner test requires a disposable superuser')
        role = connection.ops.quote_name('daroobank_owner_' + uuid4().hex)
        name = 'synthetic_owned_' + uuid4().hex
        table = connection.ops.quote_name(name)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE ROLE {role} NOLOGIN NOSUPERUSER NOBYPASSRLS')
                cursor.execute(f'GRANT USAGE ON SCHEMA public TO {role}')
                cursor.execute(f'CREATE TABLE {table} (value integer)')
                cursor.execute(f'INSERT INTO {table} VALUES (456)')
                cursor.execute(f'ALTER TABLE {table} OWNER TO {role}')
                cursor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
                cursor.execute(f'SET LOCAL ROLE {role}')
            unforced = inspect_access([name])
            self.assertFalse(unforced['role_superuser'])
            self.assertFalse(unforced['role_bypass_rls'])
            self.assertEqual((unforced['tables_rls_enabled'], unforced['tables_rls_forced']), (1, 0))
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT count(*) FROM {table}')
                self.assertEqual(cursor.fetchone(), (1,))  # Owner bypasses unforced RLS.
                cursor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
            forced = inspect_access([name])
            self.assertEqual((forced['tables_rls_enabled'], forced['tables_rls_forced']), (1, 1))
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT count(*) FROM {table}')
                self.assertEqual(cursor.fetchone(), (0,))  # No policies: default deny for this role.
            transaction.set_rollback(True)

    def test_missing_public_schema_has_unknown_create_privilege(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user')
            if not cursor.fetchone()[0]:
                self.skipTest('Synthetic schema rename test requires a disposable superuser')
        new_name = connection.ops.quote_name('synthetic_public_' + uuid4().hex)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'ALTER SCHEMA public RENAME TO {new_name}')
            self.assertIsNone(inspect_access([])['public_schema_create_privilege'])
            transaction.set_rollback(True)
        self.assertIsInstance(inspect_access([])['public_schema_create_privilege'], bool)

    def test_restricted_role_reports_selected_privileges_and_switched_role(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user')
            if not cursor.fetchone()[0]:
                self.skipTest('Synthetic role-switch test requires a disposable superuser')
        role_name = 'daroobank_access_' + uuid4().hex
        role = connection.ops.quote_name(role_name)
        table = connection.ops.quote_name(ProductPresentation._meta.db_table)
        candidate_table = connection.ops.quote_name(ProductCandidate._meta.db_table)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS')
                cursor.execute(f'REVOKE ALL ON TABLE {table} FROM PUBLIC')
                cursor.execute(f'REVOKE ALL ON TABLE {candidate_table} FROM PUBLIC')
                cursor.execute(f'GRANT SELECT ON TABLE {table} TO {role}')
                cursor.execute(f'GRANT SELECT (source_name) ON TABLE {candidate_table} TO {role}')
                cursor.execute(f'SET LOCAL ROLE {role}')
            report = inspect_access([ProductPresentation._meta.db_table])
            self.assertNotIn(role_name, json.dumps(report))
            self.assertTrue(report['role_switched'])
            self.assertTrue(report['session_superuser'])
            for key in ('role_superuser', 'role_create_database', 'role_create_roles', 'role_replication', 'role_bypass_rls'):
                self.assertFalse(report[key], key)
            self.assertEqual(report['tables_select'], 1)
            for key in ('tables_insert', 'tables_update', 'tables_delete', 'tables_truncate'):
                self.assertEqual(report[key], 0, key)
            # A table-level SELECT count of zero does not exclude column grants.
            partial = inspect_access([ProductCandidate._meta.db_table])
            self.assertEqual(partial['tables_select'], 0)
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT source_name FROM {candidate_table} LIMIT 1')
                self.assertIsNone(cursor.fetchone())
            transaction.set_rollback(True)  # Removes synthetic role and all grants.

    def test_changed_session_authorization_can_hide_original_superuser(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user')
            if not cursor.fetchone()[0]:
                self.skipTest('Synthetic session-authorization test requires a disposable superuser')
        role = connection.ops.quote_name('daroobank_session_' + uuid4().hex)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE ROLE {role} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS')
                cursor.execute(f'SET LOCAL SESSION AUTHORIZATION {role}')
            restricted = inspect_access([])
            self.assertFalse(restricted['role_superuser'])
            self.assertFalse(restricted['session_superuser'])
            self.assertFalse(restricted['role_switched'])
            with connection.cursor() as cursor:
                cursor.execute('RESET SESSION AUTHORIZATION')
            self.assertTrue(inspect_access([])['role_superuser'])
            transaction.set_rollback(True)

    def test_role_membership_can_enable_escalation_not_visible_in_role_flags(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user')
            if not cursor.fetchone()[0]:
                self.skipTest('Synthetic role-membership test requires a disposable superuser')
        low = connection.ops.quote_name('daroobank_low_' + uuid4().hex)
        high = connection.ops.quote_name('daroobank_high_' + uuid4().hex)
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE ROLE {low} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS')
                cursor.execute(f'CREATE ROLE {high} NOLOGIN SUPERUSER')
                cursor.execute(f'GRANT {high} TO {low}')
                cursor.execute(f'SET LOCAL SESSION AUTHORIZATION {low}')
            before = inspect_access([])
            self.assertFalse(before['role_superuser'])
            self.assertFalse(before['session_superuser'])
            self.assertFalse(before['role_switched'])
            with connection.cursor() as cursor:
                cursor.execute(f'SET LOCAL ROLE {high}')
            after = inspect_access([])
            self.assertTrue(after['role_superuser'])
            self.assertFalse(after['session_superuser'])
            self.assertTrue(after['role_switched'])
            with connection.cursor() as cursor:
                cursor.execute('RESET SESSION AUTHORIZATION')
            transaction.set_rollback(True)

    def test_command_outputs_fixed_json_and_generic_database_failure(self):
        output = io.StringIO()
        call_command('inspect_postgresql_access', stdout=output)
        self.assertEqual(json.loads(output.getvalue())['expected_relations'], len(expected_tables()))
        with patch('catalog.management.commands.inspect_postgresql_access.inspect_access',
                   side_effect=DatabaseError('synthetic-secret-canary')):
            with self.assertRaisesMessage(CommandError, 'PostgreSQL access inspection could not be completed.') as error:
                call_command('inspect_postgresql_access', stdout=io.StringIO())
            self.assertNotIn('synthetic-secret-canary', str(error.exception))
            # The raw exception remains introspectable but is deliberately
            # suppressed from normal and --traceback formatted output.
            self.assertIsNone(error.exception.__cause__)
            self.assertIsInstance(error.exception.__context__, DatabaseError)
            self.assertTrue(error.exception.__suppress_context__)

    def test_command_rejects_other_backend_before_query(self):
        with patch('catalog.management.commands.inspect_postgresql_access.connection') as db, \
             patch('catalog.management.commands.inspect_postgresql_access.inspect_access') as inspect:
            db.vendor = 'sqlite'
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_access', stdout=io.StringIO())
        inspect.assert_not_called()

    @override_settings(DEBUG=False)
    def test_command_rejects_non_development_before_query(self):
        with patch('catalog.management.commands.inspect_postgresql_access.inspect_access') as inspect:
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_access', stdout=io.StringIO())
        inspect.assert_not_called()
