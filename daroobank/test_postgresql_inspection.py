"""Read-only PostgreSQL catalog inspection on a disposable synthetic database."""
import io
import json
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import DatabaseError, connection, transaction
from django.db.models import Deferrable, F, Q, UniqueConstraint
from django.test import TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext

from .postgresql_inspection import (expected_check_constraints, expected_columns, expected_field_indexes,
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
        self.assertEqual(report['expected_field_indexes'], len(expected_field_indexes()))
        self.assertGreater(report['expected_field_indexes'], 0)
        self.assertEqual(report['expected_named_indexes'], len(expected_named_indexes()))
        self.assertGreater(report['expected_named_indexes'], 0)
        for key in ('unresolved_tables', 'non_table_relations', 'unvalidated_constraints', 'invalid_indexes', 'disabled_triggers',
                    'missing_foreign_keys', 'nondeferred_foreign_keys', 'nondefault_action_foreign_keys', 'missing_unique_keys',
                    'unsupported_unique_constraints', 'missing_check_constraints', 'missing_columns', 'column_nullability_mismatches',
                    'column_type_mismatches', 'unsupported_column_types', 'missing_field_indexes',
                    'unsupported_named_indexes', 'missing_named_indexes'):
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
                                        expected_named_indexes(), unsupported_unique_constraints())
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
                cursor.execute('ALTER TABLE sources_sourceclaim ADD CONSTRAINT source_claim_scope_present CHECK (true)')
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(), expected_check_constraints())
            self.assertEqual(report['missing_check_constraints'], 0)
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
