"""Historical presentation projection upgrade on a disposable test database only."""
from unittest.mock import patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import TransactionTestCase


class PresentationProjectionMigrationTests(TransactionTestCase):
    before = [('catalog', '0001_initial')]
    after = [('catalog', '0002_productpresentation_irc_normalized')]

    def setUp(self):
        super().setUp()
        # This test rolls back schema; restore all leaves even when setup fails.
        self.addCleanup(self.restore_graph)
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        apps = executor.loader.project_state(self.before).apps
        Product = apps.get_model('catalog', 'ProductPresentation')
        self.expected = {}
        examples = [
            ('۰۰۱۲۳۴', '001234'),
            (' ك\u200cي  ۱۲ ', 'ک ی 12'),
            ('ﬃ' * 40, ''),  # NFKC expansion must not be truncated to a false match.
            ('', ''),
        ]
        for number, (raw, normalized) in enumerate(examples):
            item = Product.objects.create(
                name_fa=f'ساختگی {number}', name_en='Synthetic', manufacturer='Synthetic',
                strength='1 mg', dosage_form='tablet', package_description='box',
                irc=raw, source_name='Synthetic', source_url='https://example.org',
                search_text=f'legacy projection {number}', published=bool(number % 2),
            )
            self.expected[item.pk] = (Product.objects.values().get(pk=item.pk), normalized)

    def upgrade(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.after)
        return executor.loader.project_state(self.after).apps

    def restore_graph(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_legacy_fields_survive_and_projection_is_backfilled_without_truncation(self):
        Product = self.upgrade().get_model('catalog', 'ProductPresentation')
        for pk, (before, normalized) in self.expected.items():
            with self.subTest(pk=pk):
                after = Product.objects.values().get(pk=pk)
                self.assertEqual(after.pop('irc_normalized'), normalized)
                self.assertEqual(after, before)
        self.assertEqual(Product.objects.count(), len(self.expected))

    def test_failed_backfill_rolls_back_schema_data_and_migration_record(self):
        executor = MigrationExecutor(connection)
        migration = executor.loader.graph.nodes[self.after[0]]
        operation = migration.operations[1]
        original = operation.code

        def fail_after_backfill(apps, schema_editor):
            original(apps, schema_editor)
            Product = apps.get_model('catalog', 'ProductPresentation')
            observed = dict(Product.objects.values_list('pk', 'irc_normalized'))
            self.assertEqual(observed, {pk: normalized for pk, (_, normalized) in self.expected.items()})
            raise RuntimeError('synthetic failure after projection writes')

        with patch.object(operation, 'code', fail_after_backfill):
            with self.assertRaisesMessage(RuntimeError, 'synthetic failure after projection writes'):
                executor.migrate(self.after)
        self.assertNotIn(self.after[0], MigrationRecorder(connection).applied_migrations())
        with connection.cursor() as cursor:
            columns = {column.name for column in connection.introspection.get_table_description(
                cursor, 'catalog_productpresentation')}
        self.assertNotIn('irc_normalized', columns)
        old_apps = MigrationExecutor(connection).loader.project_state(self.before).apps
        Product = old_apps.get_model('catalog', 'ProductPresentation')
        self.assertEqual({row['id']: row for row in Product.objects.values()},
                         {pk: before for pk, (before, _) in self.expected.items()})
        upgraded = self.upgrade().get_model('catalog', 'ProductPresentation')
        for pk, (_, normalized) in self.expected.items():
            self.assertEqual(upgraded.objects.get(pk=pk).irc_normalized, normalized)
