"""Historical presentation projection upgrade on a disposable test database only."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from unittest.mock import patch

from django.db import OperationalError, close_old_connections, connection, transaction
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
                verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc) if number % 2 else None,
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

    def test_atomic_backfill_holds_table_lock_until_commit(self):
        paused, resume = Event(), Event()

        def migrate_on_another_connection():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '15s'")
                executor = MigrationExecutor(connection)
                operation = executor.loader.graph.nodes[self.after[0]].operations[1]
                original = operation.code

                def pause_after_backfill(apps, schema_editor):
                    original(apps, schema_editor)
                    paused.set()
                    if not resume.wait(10):
                        raise TimeoutError('Synthetic migration was not resumed')

                with patch.object(operation, 'code', pause_after_backfill):
                    executor.migrate(self.after)
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            migration = pool.submit(migrate_on_another_connection)
            try:
                self.assertTrue(paused.wait(8), 'Migration did not reach synthetic pause')
                with self.assertRaises(OperationalError) as error, transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '300ms'")
                        cursor.execute('SELECT count(*) FROM catalog_productpresentation')
                self.assertEqual(getattr(error.exception.__cause__, 'sqlstate', None), '55P03')
            finally:
                resume.set()
            migration.result(timeout=15)
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM catalog_productpresentation')
            self.assertEqual(cursor.fetchone(), (len(self.expected),))
        self.assertIn(self.after[0], MigrationRecorder(connection).applied_migrations())

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
