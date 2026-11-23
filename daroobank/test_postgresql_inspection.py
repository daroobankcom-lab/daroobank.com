"""Read-only PostgreSQL catalog inspection on a disposable synthetic database."""
import io
import json
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import DatabaseError, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from .postgresql_inspection import expected_foreign_keys, expected_tables, expected_unique_keys, inspect_schema


@override_settings(DEBUG=True)
class PostgreSQLSchemaInspectionTests(TransactionTestCase):
    def test_clean_migrated_database_and_read_only_report(self):
        before = set(connection.introspection.table_names())
        output = io.StringIO()
        call_command('inspect_postgresql_schema', stdout=output)
        report = json.loads(output.getvalue())
        self.assertEqual(report['status'], 'no_selected_issues')
        self.assertEqual(report['expected_tables'], len(expected_tables()))
        self.assertEqual(report['expected_foreign_keys'], len(expected_foreign_keys()))
        self.assertGreater(report['expected_foreign_keys'], 0)
        self.assertEqual(report['expected_unique_keys'], len(expected_unique_keys()))
        self.assertGreater(report['expected_unique_keys'], 0)
        for key in ('unresolved_tables', 'non_table_relations', 'unvalidated_constraints', 'invalid_indexes', 'disabled_triggers',
                    'missing_foreign_keys', 'nondeferred_foreign_keys', 'nondefault_action_foreign_keys', 'missing_unique_keys'):
            self.assertEqual(report[key], 0, key)
        self.assertEqual(set(connection.introspection.table_names()), before)
        self.assertIn('sources_sourceclaim', expected_tables())
        self.assertIn('auth_user_groups', expected_tables())
        self.assertIn('django_migrations', expected_tables())

    def test_catalog_query_is_one_statement_and_succeeds_in_read_only_transaction(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('SET TRANSACTION READ ONLY')
            with CaptureQueriesContext(connection) as queries:
                report = inspect_schema(expected_tables(), expected_foreign_keys())
            self.assertEqual(len(queries), 1)
            self.assertEqual(report['status'], 'no_selected_issues')

    def test_relation_names_are_bound_values_not_sql(self):
        name = "absent'); DROP TABLE auth_user; --"
        report = inspect_schema([name])
        self.assertEqual(report['unresolved_tables'], 1)
        self.assertNotIn(name, json.dumps(report))
        self.assertIn('auth_user', connection.introspection.table_names())

    def test_missing_and_wrong_relation_kinds(self):
        with connection.cursor() as cursor:
            cursor.execute('CREATE VIEW synthetic_inspection_view AS SELECT 1 AS id')
        try:
            report = inspect_schema(['sources_sourceclaim', 'synthetic_inspection_view', 'synthetic_absent_canary'])
            self.assertEqual(report['expected_tables'], 3)
            self.assertEqual(report['unresolved_tables'], 1)
            self.assertEqual(report['non_table_relations'], 1)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn('synthetic_absent_canary', json.dumps(report))
        finally:
            with connection.cursor() as cursor:
                cursor.execute('DROP VIEW synthetic_inspection_view')

    def test_missing_managed_table_is_a_nonzero_command_without_names(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim RENAME TO synthetic_shadow_claim')
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['unresolved_tables'], 1)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn('sources_sourceclaim', output.getvalue())
            transaction.set_rollback(True)
        self.assertIn('sources_sourceclaim', connection.introspection.table_names())

    def test_missing_expected_foreign_key_is_counted_without_its_name(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('''SELECT conname FROM pg_catalog.pg_constraint
                    WHERE conrelid = 'sources_sourceclaimreview'::regclass AND contype = 'f' LIMIT 1''')
                name = cursor.fetchone()[0]
                cursor.execute('ALTER TABLE sources_sourceclaimreview DROP CONSTRAINT ' + connection.ops.quote_name(name))
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['missing_foreign_keys'], 1)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn(name, output.getvalue())
            transaction.set_rollback(True)
        self.assertEqual(inspect_schema(expected_tables(), expected_foreign_keys())['missing_foreign_keys'], 0)

    def test_foreign_key_wrong_target_is_not_an_expected_match(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('''SELECT c.conname FROM pg_catalog.pg_constraint c
                    JOIN pg_catalog.pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
                    WHERE c.conrelid='sources_sourceclaimreview'::regclass AND c.contype='f'
                    AND a.attname='reviewer_id' ''')
                name = cursor.fetchone()[0]
                cursor.execute('ALTER TABLE sources_sourceclaimreview DROP CONSTRAINT ' + connection.ops.quote_name(name))
                cursor.execute('ALTER TABLE sources_sourceclaimreview ADD CONSTRAINT synthetic_wrong_fk FOREIGN KEY (reviewer_id) REFERENCES auth_group(id) NOT VALID')
            report = inspect_schema(expected_tables(), expected_foreign_keys())
            self.assertEqual(report['missing_foreign_keys'], 1)
            self.assertEqual(report['unvalidated_constraints'], 1)
            transaction.set_rollback(True)

    def test_foreign_key_deferrability_mismatch_is_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('''SELECT c.conname FROM pg_catalog.pg_constraint c
                    JOIN pg_catalog.pg_attribute a ON a.attrelid=c.conrelid AND a.attnum=c.conkey[1]
                    WHERE c.conrelid='sources_sourceclaimreview'::regclass AND c.contype='f'
                    AND a.attname='reviewer_id' ''')
                name = cursor.fetchone()[0]
                cursor.execute('ALTER TABLE sources_sourceclaimreview DROP CONSTRAINT ' + connection.ops.quote_name(name))
                cursor.execute('ALTER TABLE sources_sourceclaimreview ADD CONSTRAINT synthetic_fk_immediate FOREIGN KEY (reviewer_id) REFERENCES auth_user(id) NOT DEFERRABLE')
            report = inspect_schema(expected_tables(), expected_foreign_keys())
            self.assertEqual(report['missing_foreign_keys'], 0)
            self.assertEqual(report['nondeferred_foreign_keys'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_extra_immediate_constraint_is_reported_despite_deferred_match(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaimreview ADD CONSTRAINT synthetic_duplicate_fk FOREIGN KEY (reviewer_id) REFERENCES auth_user(id) NOT DEFERRABLE')
            report = inspect_schema(expected_tables(), expected_foreign_keys())
            self.assertEqual(report['missing_foreign_keys'], 0)
            self.assertEqual(report['nondeferred_foreign_keys'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_unexpected_foreign_key_database_action_is_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaimreview ADD CONSTRAINT synthetic_cascade_fk FOREIGN KEY (reviewer_id) REFERENCES auth_user(id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED')
            report = inspect_schema(expected_tables(), expected_foreign_keys())
            self.assertEqual(report['missing_foreign_keys'], 0)
            self.assertEqual(report['nondefault_action_foreign_keys'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_missing_composite_unique_is_reported_despite_nonunique_index(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT unique_source_claim_revision')
                cursor.execute('CREATE INDEX synthetic_nonunique ON sources_sourceclaim (source_url, payload_sha256)')
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['missing_unique_keys'], 1)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn('synthetic_nonunique', output.getvalue())
            transaction.set_rollback(True)

    def test_partial_unique_index_does_not_replace_full_unique(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT unique_source_claim_revision')
                cursor.execute('CREATE UNIQUE INDEX synthetic_partial ON sources_sourceclaim (source_url, payload_sha256) WHERE claims_collection')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys())
            self.assertEqual(report['missing_unique_keys'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_reordered_unique_index_is_conservatively_reported_missing(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT unique_source_claim_revision')
                cursor.execute('CREATE UNIQUE INDEX synthetic_reordered ON sources_sourceclaim (payload_sha256, source_url)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys())
            self.assertEqual(report['missing_unique_keys'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_unique_null_semantics_are_deliberately_not_compared(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT unique_source_claim_revision')
                cursor.execute('CREATE UNIQUE INDEX synthetic_null_semantics ON sources_sourceclaim (source_url, payload_sha256) NULLS NOT DISTINCT')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys())
            self.assertEqual(report['missing_unique_keys'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            transaction.set_rollback(True)

    def test_missing_primary_key_is_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaimreview DROP CONSTRAINT sources_sourceclaimreview_pkey')
                cursor.execute('CREATE UNIQUE INDEX synthetic_no_primary ON sources_sourceclaimreview (id)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys())
            self.assertEqual(report['missing_unique_keys'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_out_of_scope_catalog_issues_are_not_reported(self):
        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE synthetic_unscoped (id integer)')
            cursor.execute('ALTER TABLE synthetic_unscoped ADD CONSTRAINT synthetic_unscoped_check CHECK (id > 0) NOT VALID')
        try:
            report = inspect_schema(expected_tables())
            self.assertEqual(report['unvalidated_constraints'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
        finally:
            with connection.cursor() as cursor:
                cursor.execute('DROP TABLE synthetic_unscoped')

    def test_unvalidated_constraint_and_disabled_trigger(self):
        with connection.cursor() as cursor:
            cursor.execute('ALTER TABLE sources_sourceclaim ADD CONSTRAINT synthetic_unvalidated CHECK (id > 0) NOT VALID')
            cursor.execute('CREATE FUNCTION synthetic_trigger_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$')
            cursor.execute('CREATE TRIGGER synthetic_disabled BEFORE INSERT ON sources_sourceclaim FOR EACH ROW EXECUTE FUNCTION synthetic_trigger_fn()')
            cursor.execute('ALTER TABLE sources_sourceclaim DISABLE TRIGGER synthetic_disabled')
        try:
            report = inspect_schema(expected_tables())
            self.assertEqual(report['unvalidated_constraints'], 1)
            self.assertEqual(report['disabled_triggers'], 1)
            self.assertEqual(report['status'], 'attention')
            out = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=out)
            self.assertEqual(json.loads(out.getvalue())['status'], 'attention')
            self.assertNotIn('synthetic_unvalidated', out.getvalue())
            self.assertNotIn('synthetic_disabled', out.getvalue())
        finally:
            with connection.cursor() as cursor:
                cursor.execute('DROP TRIGGER synthetic_disabled ON sources_sourceclaim')
                cursor.execute('DROP FUNCTION synthetic_trigger_fn()')
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT synthetic_unvalidated')

    def test_failed_concurrent_index_is_detected(self):
        from django.contrib.auth import get_user_model
        get_user_model().objects.create_user('synthetic-index-one')
        get_user_model().objects.create_user('synthetic-index-two')
        try:
            with connection.cursor() as cursor:
                with self.assertRaises(DatabaseError):
                    cursor.execute('CREATE UNIQUE INDEX CONCURRENTLY synthetic_invalid_index ON auth_user(first_name)')
            report = inspect_schema(expected_tables())
            self.assertEqual(report['invalid_indexes'], 1)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn('synthetic_invalid_index', json.dumps(report))
        finally:
            with connection.cursor() as cursor:
                cursor.execute('DROP INDEX IF EXISTS synthetic_invalid_index')

    def test_disabled_outside_debug_and_generic_database_errors(self):
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command('inspect_postgresql_schema', stdout=io.StringIO())
        with patch('catalog.management.commands.inspect_postgresql_schema.inspect_schema',
                   side_effect=DatabaseError('credential-canary')), self.assertRaises(CommandError) as raised:
            call_command('inspect_postgresql_schema', stdout=io.StringIO())
        self.assertNotIn('credential-canary', str(raised.exception))
        with patch.object(connection, 'vendor', 'sqlite'), self.assertRaises(CommandError):
            call_command('inspect_postgresql_schema', stdout=io.StringIO())
