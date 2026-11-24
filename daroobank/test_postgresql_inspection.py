"""Read-only PostgreSQL catalog inspection on a disposable synthetic database."""
import io
import json
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import AutoField, Deferrable, F, Q, UniqueConstraint
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from .postgresql_inspection import (expected_auto_fields, expected_check_constraints, expected_columns, expected_field_indexes,
                                     expected_foreign_keys, expected_named_indexes, expected_tables, expected_unique_keys,
                                     inspect_schema, unsupported_unique_constraints)


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
        self.assertEqual(report['expected_check_constraints'], len(expected_check_constraints()))
        self.assertGreater(report['expected_check_constraints'], 0)
        self.assertEqual(report['expected_columns'], len(expected_columns()))
        self.assertGreater(report['expected_columns'], 0)
        self.assertEqual(report['skipped_migration_pk_types'], 1)
        self.assertEqual(report['expected_auto_fields'], len(expected_auto_fields()))
        self.assertGreater(report['expected_auto_fields'], 0)
        self.assertEqual(report['expected_field_indexes'], len(expected_field_indexes()))
        self.assertGreater(report['expected_field_indexes'], 0)
        self.assertEqual(report['expected_named_indexes'], len(expected_named_indexes()))
        self.assertGreater(report['expected_named_indexes'], 0)
        for key in ('unresolved_tables', 'non_table_relations', 'unvalidated_constraints', 'invalid_indexes', 'disabled_triggers',
                    'trigger_session_mismatches', 'session_replication_role_replica', 'nonpositive_or_cycling_auto_sequences',
                    'missing_foreign_keys', 'nondeferred_foreign_keys', 'nondefault_action_foreign_keys', 'missing_unique_keys',
                    'unsupported_unique_constraints', 'missing_check_constraints', 'canonical_accept_all_named_checks',
                    'missing_columns', 'column_nullability_mismatches',
                    'column_type_mismatches', 'unsupported_column_types', 'missing_field_indexes',
                    'unsupported_named_indexes', 'missing_named_indexes', 'unsupported_auto_fields', 'missing_auto_generation'):
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
                report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                                        expected_check_constraints(), expected_columns(), expected_field_indexes(),
                                        expected_named_indexes(), unsupported_unique_constraints(), expected_auto_fields())
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

    def test_unsupported_model_unique_declarations_require_attention(self):
        from sources.models import SourceClaim
        declarations = [
            UniqueConstraint(fields=['owner'], condition=Q(claims_collection=True), name='synthetic_partial_unique'),
            UniqueConstraint(F('owner'), name='synthetic_expression_unique'),
            UniqueConstraint(fields=['owner'], include=['source_name'], name='synthetic_included_unique'),
            UniqueConstraint(fields=['owner'], opclasses=['varchar_pattern_ops'], name='synthetic_opclass_unique'),
            UniqueConstraint(fields=['owner'], nulls_distinct=False, name='synthetic_null_unique'),
            UniqueConstraint(fields=['owner'], deferrable=Deferrable.DEFERRED, name='synthetic_deferred_unique'),
        ]
        for declaration in declarations:
            with self.subTest(name=declaration.name), patch.object(
                    SourceClaim._meta, 'constraints', [*SourceClaim._meta.constraints, declaration]):
                output = io.StringIO()
                with self.assertRaises(CommandError):
                    call_command('inspect_postgresql_schema', stdout=output)
                report = json.loads(output.getvalue())
                self.assertEqual(report['unsupported_unique_constraints'], 1)
                self.assertEqual(report['missing_unique_keys'], 0)
                self.assertEqual(report['status'], 'attention')
                self.assertNotIn(declaration.name, output.getvalue())

    def test_unsupported_unique_subclass_is_counted_without_names(self):
        from sources.models import SourceClaim

        class CustomUnique(UniqueConstraint):
            pass

        declarations = [CustomUnique(fields=['owner'], name='synthetic_custom_unique'),
                        UniqueConstraint(fields=['owner'], nulls_distinct=True, name='synthetic_true_unique')]
        with patch.object(SourceClaim._meta, 'constraints', [*SourceClaim._meta.constraints, *declarations]):
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['unsupported_unique_constraints'], 2)
            self.assertEqual(report['missing_unique_keys'], 0)
            self.assertEqual(report['status'], 'attention')
            for declaration in declarations:
                self.assertNotIn(declaration.name, output.getvalue())

    def test_unsupported_unique_is_reported_in_single_read_only_statement(self):
        from sources.models import SourceClaim
        constraint = UniqueConstraint(fields=['owner'], nulls_distinct=False, name='synthetic_readonly_unique')
        with patch.object(SourceClaim._meta, 'constraints', [*SourceClaim._meta.constraints, constraint]):
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('SET TRANSACTION READ ONLY')
                with CaptureQueriesContext(connection) as queries:
                    report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                        expected_check_constraints(), expected_columns(), expected_field_indexes(),
                        expected_named_indexes(), unsupported_unique_constraints())
                self.assertEqual(len(queries), 1)
                self.assertEqual(report['unsupported_unique_constraints'], 1)
                self.assertEqual(report['status'], 'attention')

    def test_partial_unique_index_does_not_replace_full_unique(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT unique_source_claim_revision')
                cursor.execute('CREATE UNIQUE INDEX synthetic_partial ON sources_sourceclaim (source_url, payload_sha256) WHERE claims_collection')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys())
            self.assertEqual(report['missing_unique_keys'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_deferred_or_deferrable_unique_is_not_a_simple_unique_match(self):
        for timing in ('INITIALLY DEFERRED', 'INITIALLY IMMEDIATE'):
            with self.subTest(timing=timing), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT unique_source_claim_revision')
                    cursor.execute('ALTER TABLE sources_sourceclaim ADD CONSTRAINT synthetic_unique '
                                   'UNIQUE (source_url, payload_sha256) DEFERRABLE ' + timing)
                report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys())
                self.assertEqual(report['missing_unique_keys'], 1)
                self.assertEqual(report['status'], 'attention')
                transaction.set_rollback(True)

    def test_standalone_immediate_unique_index_still_matches(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT unique_source_claim_revision')
                cursor.execute('CREATE UNIQUE INDEX synthetic_plain_unique ON sources_sourceclaim (source_url, payload_sha256)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys())
            self.assertEqual(report['missing_unique_keys'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            transaction.set_rollback(True)

    def test_unique_nondefault_operator_class_is_reported(self):
        for keys in ('source_url varchar_pattern_ops, payload_sha256',
                     'source_url, payload_sha256 varchar_pattern_ops'):
            with self.subTest(keys=keys), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT unique_source_claim_revision')
                    cursor.execute('CREATE UNIQUE INDEX synthetic_unique_pattern ON sources_sourceclaim (' + keys + ')')
                report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys())
                self.assertEqual(report['missing_unique_keys'], 1)
                self.assertEqual(report['status'], 'attention')
                transaction.set_rollback(True)

    def test_unique_index_collation_different_from_column_is_reported(self):
        cases = [('source_url COLLATE "C", payload_sha256', 'source_url', 0),
                 ('source_url, payload_sha256 COLLATE "C"', 'payload_sha256', 1)]
        for keys, column, ordinal in cases:
            with self.subTest(column=column), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT unique_source_claim_revision')
                    cursor.execute('CREATE UNIQUE INDEX synthetic_unique_collation ON sources_sourceclaim (' + keys + ')')
                    cursor.execute('''SELECT i.indcollation[%s] <> a.attcollation
                                      FROM pg_catalog.pg_index i JOIN pg_catalog.pg_attribute a
                                      ON a.attrelid = i.indrelid AND a.attname = %s
                                      WHERE i.indexrelid = 'synthetic_unique_collation'::regclass''', [ordinal, column])
                    self.assertTrue(cursor.fetchone()[0])
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

    def test_unique_nulls_not_distinct_is_conservatively_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT unique_source_claim_revision')
                cursor.execute('CREATE UNIQUE INDEX synthetic_null_semantics ON sources_sourceclaim (source_url, payload_sha256) NULLS NOT DISTINCT')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys())
            self.assertEqual(report['missing_unique_keys'], 1)
            self.assertEqual(report['status'], 'attention')
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

    def test_missing_named_check_constraint_is_reported_even_with_different_name(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT source_claim_scope_present')
                cursor.execute('ALTER TABLE sources_sourceclaim ADD CONSTRAINT synthetic_equivalent CHECK (claims_collection OR claims_storage OR claims_publication)')
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['missing_check_constraints'], 1)
            self.assertNotIn('source_claim_scope_present', output.getvalue())
            self.assertNotIn('synthetic_equivalent', output.getvalue())
            transaction.set_rollback(True)

    def test_same_named_wrong_check_expression_is_not_detected(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT source_claim_scope_present')
                cursor.execute('ALTER TABLE sources_sourceclaim ADD CONSTRAINT source_claim_scope_present CHECK (1 = 1)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(), expected_check_constraints())
            self.assertEqual(report['missing_check_constraints'], 0)
            self.assertEqual(report['canonical_accept_all_named_checks'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            transaction.set_rollback(True)

    def test_matching_but_unvalidated_named_check_is_still_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT source_claim_scope_present')
                cursor.execute('ALTER TABLE sources_sourceclaim ADD CONSTRAINT source_claim_scope_present CHECK (true) NOT VALID')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(), expected_check_constraints())
            self.assertEqual(report['missing_check_constraints'], 0)
            self.assertEqual(report['unvalidated_constraints'], 1)
            self.assertEqual(report['canonical_accept_all_named_checks'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_wrong_constraint_type_with_expected_name_is_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT source_claim_scope_present')
                cursor.execute('ALTER TABLE sources_sourceclaim ADD CONSTRAINT source_claim_scope_present UNIQUE (owner)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(), expected_check_constraints())
            self.assertEqual(report['missing_check_constraints'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_canonical_always_accepting_named_check_constraints_are_flagged(self):
        from django.contrib.auth import get_user_model
        from sources.models import SourceClaim
        user = get_user_model().objects.create_user('synthetic-check-probe')
        fields = dict(source_name='منبع مصنوعی', source_url='https://example.org/check-probe',
                      owner='مالک ساختگی', evidence_url='https://example.org/check-evidence', evidence_note='',
                      claims_collection=False, claims_storage=False, claims_publication=False,
                      payload_sha256='a' * 64, recorded_by=user)
        # The real model constraint rejects a claim with no asserted scope.
        with self.assertRaises(IntegrityError), transaction.atomic():
            SourceClaim.objects.create(**fields)
        for expression, flagged in [('true', True), ('NULL', True), ('1 = 1', False)]:
            with self.subTest(expression=expression), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE sources_sourceclaim DROP CONSTRAINT source_claim_scope_present')
                    cursor.execute('ALTER TABLE sources_sourceclaim ADD CONSTRAINT source_claim_scope_present CHECK (' + expression + ')')
                SourceClaim.objects.create(**fields)
                report = inspect_schema(expected_tables(), check_constraints=expected_check_constraints())
                self.assertEqual(report['missing_check_constraints'], 0)
                self.assertEqual(report['canonical_accept_all_named_checks'], int(flagged))
                self.assertEqual(report['status'], 'attention' if flagged else 'no_selected_issues')
                output = io.StringIO()
                if flagged:
                    with self.assertRaises(CommandError):
                        call_command('inspect_postgresql_schema', stdout=output)
                    self.assertEqual(json.loads(output.getvalue())['canonical_accept_all_named_checks'], 1)
                    self.assertNotIn('source_claim_scope_present', output.getvalue())
                else:
                    call_command('inspect_postgresql_schema', stdout=output)
                    self.assertEqual(json.loads(output.getvalue())['status'], 'no_selected_issues')
                # 1 = 1 is also tautological, but deliberately outside the exact
                # deparsed constant subset. No semantic-equivalence claim.
                transaction.set_rollback(True)

    def test_unexpected_canonical_true_check_is_outside_the_selected_scope(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim ADD CONSTRAINT synthetic_extra_true CHECK (true)')
            report = inspect_schema(expected_tables(), check_constraints=expected_check_constraints())
            self.assertEqual(report['canonical_accept_all_named_checks'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            transaction.set_rollback(True)

    def test_migration_recorder_missing_column_is_reported(self):
        for column in ('id', 'app', 'name', 'applied'):
            with self.subTest(column=column), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE django_migrations DROP COLUMN ' + connection.ops.quote_name(column))
                output = io.StringIO()
                with self.assertRaises(CommandError):
                    call_command('inspect_postgresql_schema', stdout=output)
                report = json.loads(output.getvalue())
                self.assertEqual(report['missing_columns'], 1)
                self.assertEqual(report['status'], 'attention')
                self.assertNotIn('django_migrations', output.getvalue())
                self.assertNotIn(json.dumps(column), output.getvalue())
                transaction.set_rollback(True)

    def test_migration_recorder_column_nullability_and_type_are_reported(self):
        for sql, finding in [('ALTER TABLE django_migrations ALTER COLUMN app DROP NOT NULL', 'column_nullability_mismatches'),
                             ('ALTER TABLE django_migrations ALTER COLUMN name TYPE varchar(100)', 'column_type_mismatches')]:
            with self.subTest(finding=finding), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                output = io.StringIO()
                with self.assertRaises(CommandError):
                    call_command('inspect_postgresql_schema', stdout=output)
                report = json.loads(output.getvalue())
                self.assertEqual(report[finding], 1)
                self.assertEqual(report['status'], 'attention')
                transaction.set_rollback(True)

    def test_missing_or_always_auto_generation_is_reported(self):
        cases = [('sources_sourceclaim', 'DROP IDENTITY'), ('sources_sourceclaim', 'SET GENERATED ALWAYS'),
                 ('django_migrations', 'DROP IDENTITY'), ('auth_user_groups', 'DROP IDENTITY')]
        for table, alteration in cases:
            with self.subTest(table=table, alteration=alteration), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE ' + connection.ops.quote_name(table) + ' ALTER COLUMN id ' + alteration)
                output = io.StringIO()
                with self.assertRaises(CommandError):
                    call_command('inspect_postgresql_schema', stdout=output)
                report = json.loads(output.getvalue())
                self.assertEqual(report['missing_auto_generation'], 1)
                self.assertEqual(report['status'], 'attention')
                self.assertNotIn(table, output.getvalue())
                transaction.set_rollback(True)

    def test_unsupported_auto_field_metadata_requires_attention(self):
        with patch('catalog.management.commands.inspect_postgresql_schema.expected_auto_fields',
                   return_value=[('synthetic_private_table', 'private_key', False)]):
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['expected_auto_fields'], 1)
            self.assertEqual(report['unsupported_auto_fields'], 1)
            self.assertEqual(report['missing_auto_generation'], 0)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn('synthetic_private_table', output.getvalue())
            self.assertNotIn('private_key', output.getvalue())

    def test_custom_auto_field_subclass_is_counted_as_unsupported(self):
        from sources.models import SourceClaim

        class CustomAutoField(AutoField):
            pass

        custom = CustomAutoField(primary_key=True)
        custom.set_attributes_from_name('synthetic_id')
        with patch.object(SourceClaim._meta, 'local_fields', [custom]):
            self.assertIn(('sources_sourceclaim', 'synthetic_id', False), expected_auto_fields())

    def test_legacy_owned_serial_with_default_is_accepted(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim ALTER COLUMN id DROP IDENTITY')
                cursor.execute('CREATE SEQUENCE synthetic_serial OWNED BY sources_sourceclaim.id')
                cursor.execute("ALTER TABLE sources_sourceclaim ALTER COLUMN id SET DEFAULT nextval('synthetic_serial')")
            output = io.StringIO()
            call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['missing_auto_generation'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            transaction.set_rollback(True)

    def test_legacy_serial_with_quoted_sequence_name_is_accepted(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim ALTER COLUMN id DROP IDENTITY')
                quoted_name = '"' + 'synthetic odd\'" sequence'.replace('"', '""') + '"'
                cursor.execute('CREATE SEQUENCE ' + quoted_name + ' OWNED BY sources_sourceclaim.id')
                literal = "'" + quoted_name.replace("'", "''") + "'"
                cursor.execute('ALTER TABLE sources_sourceclaim ALTER COLUMN id SET DEFAULT nextval(' + literal + '::regclass)')
                cursor.execute('SET LOCAL search_path TO pg_catalog, public')
            output = io.StringIO()
            call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['missing_auto_generation'], 0)
            self.assertEqual(report['nonpositive_or_cycling_auto_sequences'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            with connection.cursor() as cursor:
                cursor.execute('ALTER SEQUENCE ' + quoted_name + ' CYCLE')
            report = inspect_schema(expected_tables(), auto_fields=expected_auto_fields())
            self.assertEqual(report['nonpositive_or_cycling_auto_sequences'], 1)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn('synthetic odd', json.dumps(report))
            transaction.set_rollback(True)

    def test_serial_requires_an_owned_sequence_and_a_default(self):
        for owned, default in ((False, True), (True, False)):
            with self.subTest(owned=owned, default=default), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE sources_sourceclaim ALTER COLUMN id DROP IDENTITY')
                    cursor.execute('CREATE SEQUENCE synthetic_serial' + (' OWNED BY sources_sourceclaim.id' if owned else ''))
                    if default:
                        cursor.execute("ALTER TABLE sources_sourceclaim ALTER COLUMN id SET DEFAULT nextval('synthetic_serial')")
                output = io.StringIO()
                with self.assertRaises(CommandError):
                    call_command('inspect_postgresql_schema', stdout=output)
                report = json.loads(output.getvalue())
                self.assertEqual(report['missing_auto_generation'], 1)
                self.assertEqual(report['status'], 'attention')
                transaction.set_rollback(True)

    def test_serial_default_must_reference_owned_sequence(self):
        for expression in ('42', "nextval('synthetic_other')"):
            with self.subTest(expression=expression), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('ALTER TABLE sources_sourceclaim ALTER COLUMN id DROP IDENTITY')
                    cursor.execute('CREATE SEQUENCE synthetic_serial OWNED BY sources_sourceclaim.id')
                    cursor.execute('CREATE SEQUENCE synthetic_other')
                    cursor.execute('ALTER TABLE sources_sourceclaim ALTER COLUMN id SET DEFAULT ' + expression)
                output = io.StringIO()
                with self.assertRaises(CommandError):
                    call_command('inspect_postgresql_schema', stdout=output)
                report = json.loads(output.getvalue())
                self.assertEqual(report['missing_auto_generation'], 1)
                self.assertEqual(report['status'], 'attention')
                transaction.set_rollback(True)

    def test_shadowed_nextval_function_is_not_an_accepted_serial_default(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim ALTER COLUMN id DROP IDENTITY')
                cursor.execute('CREATE SEQUENCE synthetic_serial OWNED BY sources_sourceclaim.id')
                cursor.execute("CREATE FUNCTION public.nextval(regclass) RETURNS bigint LANGUAGE sql AS 'SELECT 42::bigint'")
                cursor.execute('SET LOCAL search_path TO public, pg_catalog')
                cursor.execute("ALTER TABLE sources_sourceclaim ALTER COLUMN id SET DEFAULT public.nextval('synthetic_serial'::regclass)")
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['missing_auto_generation'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_equivalent_but_noncanonical_serial_default_is_flagged(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim ALTER COLUMN id DROP IDENTITY')
                cursor.execute('CREATE SEQUENCE synthetic_serial OWNED BY sources_sourceclaim.id')
                cursor.execute("ALTER TABLE sources_sourceclaim ALTER COLUMN id SET DEFAULT nextval('synthetic_serial') + 0")
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['missing_auto_generation'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_migration_recorder_primary_key_constraint_is_required(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE django_migrations DROP CONSTRAINT django_migrations_pkey')
                cursor.execute('CREATE UNIQUE INDEX synthetic_recorder_unique ON django_migrations (id)')
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['missing_unique_keys'], 1)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn('django_migrations', output.getvalue())
            self.assertNotIn('synthetic_recorder_unique', output.getvalue())
            transaction.set_rollback(True)

    def test_migration_recorder_primary_key_type_is_skipped(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE django_migrations ALTER COLUMN id TYPE integer')
            output = io.StringIO()
            call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['skipped_migration_pk_types'], 1)
            self.assertEqual(report['skipped_auto_m2m_pk_types'], 3)
            self.assertEqual(report['column_type_mismatches'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            transaction.set_rollback(True)

    def test_missing_managed_column_is_reported_without_names(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE sources_sourceclaim DROP COLUMN evidence_note')
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['missing_columns'], 1)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn('evidence_note', output.getvalue())
            transaction.set_rollback(True)

    def test_changed_column_nullability_is_reported_in_both_directions(self):
        for sql in ('ALTER TABLE sources_sourceclaim ALTER COLUMN owner DROP NOT NULL',
                    'ALTER TABLE sources_sourceclaim ALTER COLUMN starts_on SET NOT NULL'):
            with self.subTest(sql=sql), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                output = io.StringIO()
                with self.assertRaises(CommandError):
                    call_command('inspect_postgresql_schema', stdout=output)
                report = json.loads(output.getvalue())
                self.assertEqual(report['missing_columns'], 0)
                self.assertEqual(report['column_nullability_mismatches'], 1)
                self.assertEqual(report['status'], 'attention')
                transaction.set_rollback(True)

    def test_existing_column_with_wrong_type_is_reported(self):
        for sql in ('ALTER TABLE sources_sourceclaim ALTER COLUMN owner TYPE text',
                    'ALTER TABLE sources_sourceclaim ALTER COLUMN owner TYPE varchar(100)',
                    'ALTER TABLE catalog_formulationcomponent ALTER COLUMN numerator TYPE numeric(10,3)',
                    "ALTER TABLE sources_sourceclaim ALTER COLUMN recorded_at TYPE timestamp without time zone USING recorded_at AT TIME ZONE 'UTC'"):
            with self.subTest(sql=sql), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(sql)
                report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                                        expected_check_constraints(), expected_columns())
                self.assertEqual(report['missing_columns'], 0)
                self.assertEqual(report['column_type_mismatches'], 1)
                self.assertEqual(report['status'], 'attention')
                transaction.set_rollback(True)

    def test_type_mapping_is_small_and_fails_closed_for_other_types(self):
        from .postgresql_inspection import _catalog_type
        self.assertEqual(_catalog_type('varchar(200)'), 'character varying(200)')
        self.assertEqual(_catalog_type('numeric(12, 4)'), 'numeric(12,4)')
        self.assertEqual(_catalog_type('timestamp with time zone'), 'timestamp with time zone')
        for bad in ('numeric', 'varchar(0)', 'uuid', 'integer[]', 'numeric(12,-1)', '', None):
            with self.subTest(db_type=bad):
                self.assertIsNone(_catalog_type(bad))

    def test_auto_created_m2m_primary_key_type_is_explicitly_skipped(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE auth_user_groups ALTER COLUMN id TYPE integer')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                                    expected_check_constraints(), expected_columns())
            self.assertGreater(report['skipped_auto_m2m_pk_types'], 0)
            self.assertEqual(report['column_type_mismatches'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            transaction.set_rollback(True)

    def test_unknown_model_type_is_reported_as_incomplete_not_clean(self):
        with patch('catalog.management.commands.inspect_postgresql_schema.expected_columns',
                   return_value=[('sources_sourceclaim', 'owner', True, None, False)]):
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['unsupported_column_types'], 1)
            self.assertEqual(report['column_type_mismatches'], 0)
            self.assertEqual(report['status'], 'attention')

    def test_missing_db_index_and_partial_or_hash_replacements_are_reported(self):
        for replacement in ('',
                            "CREATE INDEX synthetic_partial_irc ON catalog_productcandidate (irc_normalized) WHERE irc_normalized <> ''",
                            'CREATE INDEX synthetic_hash_irc ON catalog_productcandidate USING hash (irc_normalized)'):
            with self.subTest(replacement=replacement), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('''SELECT idx.relname FROM pg_catalog.pg_index i
                        JOIN pg_catalog.pg_class idx ON idx.oid=i.indexrelid
                        JOIN pg_catalog.pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=i.indkey[0]
                        WHERE i.indrelid='catalog_productcandidate'::regclass AND a.attname='irc_normalized' ''')
                    names = [row[0] for row in cursor.fetchall()]
                    self.assertGreaterEqual(len(names), 1)
                    for name in names:
                        cursor.execute('DROP INDEX ' + connection.ops.quote_name(name))
                    if replacement:
                        cursor.execute(replacement)
                output = io.StringIO()
                with self.assertRaises(CommandError):
                    call_command('inspect_postgresql_schema', stdout=output)
                report = json.loads(output.getvalue())
                self.assertEqual(report['missing_field_indexes'], 1)
                self.assertNotIn('irc_normalized', output.getvalue())
                transaction.set_rollback(True)

    def test_longer_index_with_same_leading_field_satisfies_selected_check(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('''SELECT idx.relname FROM pg_catalog.pg_index i
                    JOIN pg_catalog.pg_class idx ON idx.oid=i.indexrelid
                    JOIN pg_catalog.pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=i.indkey[0]
                    WHERE i.indrelid='catalog_productcandidate'::regclass AND a.attname='irc_normalized' ''')
                names = [row[0] for row in cursor.fetchall()]
                self.assertGreaterEqual(len(names), 1)
                for name in names:
                    cursor.execute('DROP INDEX ' + connection.ops.quote_name(name))
                cursor.execute('CREATE INDEX synthetic_composite_irc ON catalog_productcandidate (irc_normalized, id)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                                    expected_check_constraints(), expected_columns(), expected_field_indexes())
            self.assertEqual(report['missing_field_indexes'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            transaction.set_rollback(True)

    def test_missing_and_wrong_key_order_named_indexes_are_reported(self):
        for replacement in ('CREATE INDEX synthetic_receipt_index ON ingestion_importreceipt (kind, id DESC)',
                            'CREATE INDEX receipt_kind_id_idx ON ingestion_importreceipt (id, kind)'):
            with self.subTest(replacement=replacement), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('DROP INDEX receipt_kind_id_idx')
                    cursor.execute(replacement)
                output = io.StringIO()
                with self.assertRaises(CommandError):
                    call_command('inspect_postgresql_schema', stdout=output)
                report = json.loads(output.getvalue())
                self.assertEqual(report['missing_named_indexes'], 1)
                self.assertNotIn('receipt_kind_id_idx', output.getvalue())
                transaction.set_rollback(True)

    def test_named_index_sort_direction_mismatch_is_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('DROP INDEX receipt_kind_id_idx')
                cursor.execute('CREATE INDEX receipt_kind_id_idx ON ingestion_importreceipt (kind, id ASC)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                expected_check_constraints(), expected_columns(), expected_field_indexes(), expected_named_indexes())
            self.assertEqual(report['missing_named_indexes'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_named_index_first_key_direction_mismatch_is_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('DROP INDEX receipt_kind_id_idx')
                cursor.execute('CREATE INDEX receipt_kind_id_idx ON ingestion_importreceipt (kind DESC, id DESC)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                expected_check_constraints(), expected_columns(), expected_field_indexes(), expected_named_indexes())
            self.assertEqual(report['missing_named_indexes'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_named_index_descending_null_order_mismatch_is_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('DROP INDEX receipt_kind_id_idx')
                cursor.execute('CREATE INDEX receipt_kind_id_idx ON ingestion_importreceipt (kind, id DESC NULLS LAST)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                expected_check_constraints(), expected_columns(), expected_field_indexes(), expected_named_indexes())
            self.assertEqual(report['missing_named_indexes'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_named_index_nondefault_operator_class_is_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('DROP INDEX receipt_kind_id_idx')
                cursor.execute('CREATE INDEX receipt_kind_id_idx ON ingestion_importreceipt (kind varchar_pattern_ops, id DESC)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                expected_check_constraints(), expected_columns(), expected_field_indexes(), expected_named_indexes())
            self.assertEqual(report['missing_named_indexes'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_named_index_collation_different_from_column_is_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('DROP INDEX receipt_kind_id_idx')
                cursor.execute('CREATE INDEX receipt_kind_id_idx ON ingestion_importreceipt (kind COLLATE "C", id DESC)')
                cursor.execute('''SELECT i.indcollation[0] <> a.attcollation
                                  FROM pg_catalog.pg_index i
                                  JOIN pg_catalog.pg_attribute a ON a.attrelid = i.indrelid AND a.attname = 'kind'
                                  WHERE i.indexrelid = 'receipt_kind_id_idx'::regclass''')
                self.assertTrue(cursor.fetchone()[0])
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                expected_check_constraints(), expected_columns(), expected_field_indexes(), expected_named_indexes())
            self.assertEqual(report['missing_named_indexes'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_named_index_storage_options_are_not_checked(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('ALTER INDEX receipt_kind_id_idx SET (fillfactor = 42)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                expected_check_constraints(), expected_columns(), expected_field_indexes(), expected_named_indexes())
            self.assertEqual(report['missing_named_indexes'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            transaction.set_rollback(True)

    def test_named_index_extra_included_column_is_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('DROP INDEX receipt_kind_id_idx')
                cursor.execute('CREATE INDEX receipt_kind_id_idx ON ingestion_importreceipt (kind, id DESC) INCLUDE (source_name)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                expected_check_constraints(), expected_columns(), expected_field_indexes(), expected_named_indexes())
            self.assertEqual(report['missing_named_indexes'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_named_index_ascending_null_order_mismatch_is_reported(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('DROP INDEX receipt_kind_id_idx')
                cursor.execute('CREATE INDEX receipt_kind_id_idx ON ingestion_importreceipt (kind ASC NULLS FIRST, id DESC)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                expected_check_constraints(), expected_columns(), expected_field_indexes(), expected_named_indexes())
            self.assertEqual(report['missing_named_indexes'], 1)
            self.assertEqual(report['status'], 'attention')
            transaction.set_rollback(True)

    def test_unsupported_named_index_does_not_report_clean(self):
        with patch('catalog.management.commands.inspect_postgresql_schema.expected_named_indexes',
                   return_value=[('ingestion_importreceipt', 'synthetic', (), (), False)]):
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            report = json.loads(output.getvalue())
            self.assertEqual(report['unsupported_named_indexes'], 1)
            self.assertEqual(report['missing_named_indexes'], 0)
            self.assertEqual(report['status'], 'attention')

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

    def test_selected_auto_sequences_with_nonpositive_or_cycling_settings_are_flagged(self):
        # Roll back each synthetic DDL change; the check is about static catalog
        # settings, not the mutable next value or all insert behavior.
        cases = [('sources_sourceclaim', 'CYCLE'), ('sources_sourceclaim', 'INCREMENT BY -1 MINVALUE -100'),
                 ('sources_sourceclaim', 'MINVALUE 0'), ('auth_user_groups', 'CYCLE'), ('django_migrations', 'CYCLE')]
        for table, option in cases:
            with self.subTest(table=table, option=option), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('''SELECT pg_catalog.quote_ident(n.nspname) || '.' || pg_catalog.quote_ident(c.relname)
                        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                        WHERE c.oid = pg_catalog.pg_get_serial_sequence(%s, 'id')::regclass''', [table])
                    sequence = cursor.fetchone()[0]
                    cursor.execute('ALTER SEQUENCE ' + sequence + ' ' + option)
                report = inspect_schema(expected_tables(), auto_fields=expected_auto_fields())
                self.assertEqual(report['nonpositive_or_cycling_auto_sequences'], 1)
                self.assertEqual(report['status'], 'attention')
                output = io.StringIO()
                with self.assertRaises(CommandError):
                    call_command('inspect_postgresql_schema', stdout=output)
                self.assertEqual(json.loads(output.getvalue())['nonpositive_or_cycling_auto_sequences'], 1)
                self.assertNotIn(table, output.getvalue())
                transaction.set_rollback(True)
        # The selected check permits a positive, noncycling nonunit increment;
        # it is not an exact migration-default comparison.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('''SELECT pg_catalog.quote_ident(n.nspname) || '.' || pg_catalog.quote_ident(c.relname)
                    FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    WHERE c.oid = pg_catalog.pg_get_serial_sequence('sources_sourceclaim', 'id')::regclass''')
                sequence = cursor.fetchone()[0]
                cursor.execute('ALTER SEQUENCE ' + sequence + ' INCREMENT BY 2')
            report = inspect_schema(expected_tables(), auto_fields=expected_auto_fields())
            self.assertEqual(report['nonpositive_or_cycling_auto_sequences'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            transaction.set_rollback(True)

    def test_selected_auto_sequence_settings_truth_table(self):
        # All 12 combinations of selected sign, minimum and cycle settings;
        # the Python oracle is independent of the SQL predicate.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('CREATE TABLE synthetic_auto_matrix (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY)')
            for increment in (-1, 1, 7):
                for minimum in (0, 1):
                    for cycling in (False, True):
                        with self.subTest(increment=increment, minimum=minimum, cycling=cycling):
                            with connection.cursor() as cursor:
                                cursor.execute('ALTER SEQUENCE synthetic_auto_matrix_id_seq INCREMENT BY '
                                    + str(increment) + ' MINVALUE ' + str(minimum)
                                    + (' CYCLE' if cycling else ' NO CYCLE'))
                            report = inspect_schema(['synthetic_auto_matrix'],
                                                    auto_fields=[('synthetic_auto_matrix', 'id', True)])
                            expected = increment < 1 or minimum < 1 or cycling
                            self.assertEqual(report['nonpositive_or_cycling_auto_sequences'], int(expected))
                            self.assertEqual(report['status'], 'attention' if expected else 'no_selected_issues')
            transaction.set_rollback(True)

    def test_selected_cycling_sequence_can_reissue_a_value(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('CREATE TABLE synthetic_auto_probe (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY)')
                cursor.execute('ALTER SEQUENCE synthetic_auto_probe_id_seq MAXVALUE 2 CYCLE')
                cursor.execute("SELECT nextval('synthetic_auto_probe_id_seq'), nextval('synthetic_auto_probe_id_seq'), nextval('synthetic_auto_probe_id_seq')")
                self.assertEqual(cursor.fetchone(), (1, 2, 1))
            report = inspect_schema(['synthetic_auto_probe'], auto_fields=[('synthetic_auto_probe', 'id', True)])
            self.assertEqual(report['nonpositive_or_cycling_auto_sequences'], 1)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn('synthetic_auto_probe', json.dumps(report))
            transaction.set_rollback(True)

    def test_selected_sequence_settings_do_not_detect_rewound_value(self):
        # This negative control documents a blind spot, not a guarantee that a
        # clean report permits inserts or a recommendation to modify sequences.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('CREATE TABLE synthetic_auto_rewind (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY)')
                cursor.execute('INSERT INTO synthetic_auto_rewind DEFAULT VALUES')
                cursor.execute("SELECT setval('synthetic_auto_rewind_id_seq', 1, false)")
            report = inspect_schema(['synthetic_auto_rewind'], auto_fields=[('synthetic_auto_rewind', 'id', True)])
            self.assertEqual(report['nonpositive_or_cycling_auto_sequences'], 0)
            self.assertEqual(report['missing_auto_generation'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
            with self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('INSERT INTO synthetic_auto_rewind DEFAULT VALUES')
            transaction.set_rollback(True)

    def test_sequence_cache_can_make_committed_ids_nonchronological(self):
        # Separate live PostgreSQL sessions reserve different cached ranges.
        # A clean selected settings report does not imply commit-time ordering.
        self.assertTrue(connection.get_autocommit())
        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE synthetic_cached_ids (id bigint GENERATED BY DEFAULT AS IDENTITY (CACHE 3) PRIMARY KEY)')
        other = connection.copy()
        try:
            other.ensure_connection()
            self.assertTrue(other.get_autocommit())
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO synthetic_cached_ids DEFAULT VALUES RETURNING id')
                first = cursor.fetchone()[0]
            with other.cursor() as cursor:
                cursor.execute('INSERT INTO synthetic_cached_ids DEFAULT VALUES RETURNING id')
                second = cursor.fetchone()[0]
            with connection.cursor() as cursor:
                cursor.execute('INSERT INTO synthetic_cached_ids DEFAULT VALUES RETURNING id')
                third = cursor.fetchone()[0]
            self.assertEqual((first, second, third), (1, 4, 2))
            report = inspect_schema(['synthetic_cached_ids'], auto_fields=[('synthetic_cached_ids', 'id', True)])
            self.assertEqual(report['nonpositive_or_cycling_auto_sequences'], 0)
            self.assertEqual(report['status'], 'no_selected_issues')
        finally:
            other.close()
            with connection.cursor() as cursor:
                cursor.execute('DROP TABLE synthetic_cached_ids')

    def test_default_sequence_ids_do_not_establish_commit_order(self):
        # Even with cache one, an earlier reservation may commit later.
        self.assertTrue(connection.get_autocommit())
        with connection.cursor() as cursor:
            cursor.execute('CREATE TABLE synthetic_commit_order (id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY)')
        other = connection.copy()
        try:
            other.ensure_connection()
            self.assertTrue(other.get_autocommit())
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('INSERT INTO synthetic_commit_order DEFAULT VALUES RETURNING id')
                    first = cursor.fetchone()[0]
                with other.cursor() as cursor:
                    cursor.execute('INSERT INTO synthetic_commit_order DEFAULT VALUES RETURNING id')
                    second = cursor.fetchone()[0]
                    cursor.execute('SELECT id FROM synthetic_commit_order ORDER BY id')
                    self.assertEqual(cursor.fetchall(), [(second,)])
            with other.cursor() as cursor:
                cursor.execute('SELECT id FROM synthetic_commit_order ORDER BY id')
                self.assertEqual(cursor.fetchall(), [(first,), (second,)])
            self.assertEqual((first, second), (1, 2))
            report = inspect_schema(['synthetic_commit_order'], auto_fields=[('synthetic_commit_order', 'id', True)])
            self.assertEqual(report['status'], 'no_selected_issues')
        finally:
            other.close()
            with connection.cursor() as cursor:
                cursor.execute('DROP TABLE synthetic_commit_order')

    def test_replica_only_trigger_is_inactive_for_origin_session(self):
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('CREATE TABLE synthetic_trigger_probe (id integer)')
                cursor.execute('CREATE FUNCTION synthetic_trigger_probe_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NULL; END $$')
                cursor.execute('CREATE TRIGGER synthetic_trigger_probe_row BEFORE INSERT ON synthetic_trigger_probe FOR EACH ROW EXECUTE FUNCTION synthetic_trigger_probe_fn()')
                cursor.execute('ALTER TABLE synthetic_trigger_probe ENABLE REPLICA TRIGGER synthetic_trigger_probe_row')
                cursor.execute('INSERT INTO synthetic_trigger_probe VALUES (1)')
                self.assertEqual(cursor.rowcount, 1)  # replica-only trigger did not fire
            report = inspect_schema(['synthetic_trigger_probe'])
            self.assertEqual(report['disabled_triggers'], 0)
            self.assertEqual(report['trigger_session_mismatches'], 1)
            self.assertEqual(report['session_replication_role_replica'], 0)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn('synthetic_trigger_probe', json.dumps(report))
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE synthetic_trigger_probe ENABLE ALWAYS TRIGGER synthetic_trigger_probe_row')
                cursor.execute('INSERT INTO synthetic_trigger_probe VALUES (2)')
                self.assertEqual(cursor.rowcount, 0)
            self.assertEqual(inspect_schema(['synthetic_trigger_probe'])['trigger_session_mismatches'], 0)
            with connection.cursor() as cursor:
                cursor.execute('ALTER TABLE synthetic_trigger_probe DISABLE TRIGGER synthetic_trigger_probe_row')
            report = inspect_schema(['synthetic_trigger_probe'])
            self.assertEqual((report['disabled_triggers'], report['trigger_session_mismatches']), (1, 0))
            with connection.cursor() as cursor:
                cursor.execute('CREATE TRIGGER synthetic_managed_replica BEFORE INSERT ON sources_sourceclaim FOR EACH ROW EXECUTE FUNCTION synthetic_trigger_probe_fn()')
                cursor.execute('ALTER TABLE sources_sourceclaim ENABLE REPLICA TRIGGER synthetic_managed_replica')
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            self.assertEqual(json.loads(output.getvalue())['trigger_session_mismatches'], 1)
            self.assertNotIn('synthetic_managed_replica', output.getvalue())
            self.assertNotIn('sources_sourceclaim', output.getvalue())
            transaction.set_rollback(True)

    def test_replica_session_skips_origin_fk_triggers_and_is_reported(self):
        # Changing this GUC is privileged; only run the actual bypass probe when
        # the disposable test role has PostgreSQL's SET privilege.
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_catalog.has_parameter_privilege(current_user, 'session_replication_role', 'SET')")
            if not cursor.fetchone()[0]:
                self.skipTest('Synthetic role cannot change session_replication_role')
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('CREATE TABLE synthetic_replica_parent (id integer PRIMARY KEY)')
                cursor.execute('CREATE TABLE synthetic_replica_child (parent_id integer REFERENCES synthetic_replica_parent(id))')
            with self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('INSERT INTO synthetic_replica_child VALUES (42)')
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL session_replication_role = 'replica'")
                cursor.execute('INSERT INTO synthetic_replica_child VALUES (42)')
                self.assertEqual(cursor.rowcount, 1)
            report = inspect_schema(['synthetic_replica_parent', 'synthetic_replica_child'])
            self.assertEqual(report['session_replication_role_replica'], 1)
            self.assertGreaterEqual(report['trigger_session_mismatches'], 2)
            self.assertEqual(report['status'], 'attention')
            self.assertNotIn('synthetic_replica_child', json.dumps(report))
            self.assertEqual(inspect_schema([])['session_replication_role_replica'], 1)
            output = io.StringIO()
            with self.assertRaises(CommandError):
                call_command('inspect_postgresql_schema', stdout=output)
            self.assertEqual(json.loads(output.getvalue())['session_replication_role_replica'], 1)
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL session_replication_role = 'local'")
            report = inspect_schema(['synthetic_replica_parent', 'synthetic_replica_child'])
            self.assertEqual((report['session_replication_role_replica'], report['trigger_session_mismatches']), (0, 0))
            transaction.set_rollback(True)

    def test_replica_only_internal_fk_triggers_do_not_enforce_in_origin_mode(self):
        # Altering internal RI triggers requires a superuser and is strictly a
        # disposable, rolled-back test; never do this as a repair operation.
        with connection.cursor() as cursor:
            cursor.execute('SELECT rolsuper FROM pg_catalog.pg_roles WHERE rolname = current_user')
            if not cursor.fetchone()[0]:
                self.skipTest('Synthetic role cannot alter internal FK triggers')
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute('CREATE TABLE synthetic_origin_fk_parent (id integer PRIMARY KEY)')
                cursor.execute('CREATE TABLE synthetic_origin_fk_child (parent_id integer REFERENCES synthetic_origin_fk_parent(id))')
            with self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('INSERT INTO synthetic_origin_fk_child VALUES (11)')
            with connection.cursor() as cursor:
                cursor.execute("SELECT tgname FROM pg_catalog.pg_trigger WHERE tgrelid = 'synthetic_origin_fk_child'::regclass AND tgisinternal ORDER BY tgname")
                names = [row[0] for row in cursor.fetchall()]
                self.assertEqual(len(names), 2)
                for name in names:
                    quoted = '"' + name.replace('"', '""') + '"'
                    cursor.execute('ALTER TABLE synthetic_origin_fk_child ENABLE REPLICA TRIGGER ' + quoted)
                cursor.execute('INSERT INTO synthetic_origin_fk_child VALUES (11)')
                self.assertEqual(cursor.rowcount, 1)
            report = inspect_schema(['synthetic_origin_fk_child'])
            self.assertEqual(report['disabled_triggers'], 0)
            self.assertEqual(report['session_replication_role_replica'], 0)
            self.assertGreaterEqual(report['trigger_session_mismatches'], 2)
            self.assertEqual(report['status'], 'attention')
            with connection.cursor() as cursor:
                for name in names:
                    quoted = '"' + name.replace('"', '""') + '"'
                    cursor.execute('ALTER TABLE synthetic_origin_fk_child ENABLE ALWAYS TRIGGER ' + quoted)
            self.assertEqual(inspect_schema(['synthetic_origin_fk_child'])['trigger_session_mismatches'], 0)
            with self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('INSERT INTO synthetic_origin_fk_child VALUES (12)')
            # Re-enabling triggers does not validate previously inserted rows.
            with connection.cursor() as cursor:
                cursor.execute('SELECT count(*) FROM synthetic_origin_fk_child')
                self.assertEqual(cursor.fetchone()[0], 1)
            transaction.set_rollback(True)

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
