"""Reversible synthetic migration probe, never run against a real database."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from unittest.mock import patch

from django.db import IntegrityError, OperationalError, close_old_connections, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import TransactionTestCase


class PublishedDateMigrationTests(TransactionTestCase):
    before = [('catalog', '0007_formulationrevision_ingredientrevision_and_more')]
    after = [('catalog', '0008_presentation_published_date_constraint')]

    def setUp(self):
        super().setUp()
        config = connection.settings_dict
        if (connection.vendor != 'postgresql' or config.get('ENGINE') != 'daroobank.isolated_postgresql'
                or not re.fullmatch(r'test_daroobank_synthetic_[0-9a-f]{32}', str(config.get('NAME', '')))):
            raise RuntimeError('Migration probe requires a disposable isolated synthetic database.')
        self.fixture_ids = []
        self.addCleanup(self.restore_graph)
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        self.Product = executor.loader.project_state(self.before).apps.get_model('catalog', 'ProductPresentation')

    def fixture(self, *, published, verified_at):
        obj = self.Product.objects.create(name_fa='رکورد ساختگی', manufacturer='سازنده فرضی', strength='1 mg',
            dosage_form='قرص', package_description='10 عدد', source_name='منبع فرضی',
            source_url='https://example.org/synthetic', published=published, verified_at=verified_at, search_text='')
        self.fixture_ids.append(obj.pk)
        return obj

    def restore_graph(self):
        # These IDs were created by this test only. Unpublish invalid synthetic
        # fixtures so the graph can be restored before Django flushes test data.
        if self.fixture_ids:
            with connection.cursor() as cursor:
                cursor.execute('UPDATE catalog_productpresentation SET published = false '
                               'WHERE id = ANY(%s) AND published AND verified_at IS NULL', [self.fixture_ids])
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def upgrade(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.after)
        return executor.loader.project_state(self.after).apps.get_model('catalog', 'ProductPresentation')

    def test_valid_legacy_records_survive_unchanged(self):
        date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for published, verified_at in ((False, None), (False, date), (True, date)):
            self.fixture(published=published, verified_at=verified_at)
        before = list(self.Product.objects.order_by('pk').values())
        Product = self.upgrade()
        self.assertEqual(list(Product.objects.order_by('pk').values()), before)
        self.assertIn(self.after[0], MigrationRecorder(connection).applied_migrations())
        with self.assertRaises(IntegrityError), transaction.atomic():
            Product.objects.filter(pk=self.fixture_ids[0]).update(published=True, verified_at=None)

    def test_legacy_invalid_row_fails_without_rewriting_data_or_recording_migration(self):
        item = self.fixture(published=True, verified_at=None)
        before = self.Product.objects.values().get(pk=item.pk)
        with self.assertRaises(IntegrityError) as error:
            self.upgrade()
        self.assertEqual(getattr(error.exception.__cause__, 'sqlstate', None), '23514')
        self.assertNotIn(self.after[0], MigrationRecorder(connection).applied_migrations())
        self.assertEqual(self.Product.objects.values().get(pk=item.pk), before)
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, 'catalog_productpresentation')
        self.assertNotIn('catalog_published_requires_verified', constraints)
        # Only the synthetic fixture is corrected; real data need separate review.
        self.Product.objects.filter(pk=item.pk).update(published=False)
        Product = self.upgrade()
        after = Product.objects.values().get(pk=item.pk)
        self.assertEqual(after, {**before, 'published': False})

    def test_failure_after_constraint_addition_rolls_back_ddl_and_record(self):
        item = self.fixture(published=False, verified_at=None)
        before = self.Product.objects.values().get(pk=item.pk)
        executor = MigrationExecutor(connection)
        operation = executor.loader.graph.nodes[self.after[0]].operations[0]
        original = operation.database_forwards

        def fail_after_add(*args, **kwargs):
            original(*args, **kwargs)
            with connection.cursor() as cursor:
                constraints = connection.introspection.get_constraints(cursor, 'catalog_productpresentation')
            self.assertIn('catalog_published_requires_verified', constraints)
            raise RuntimeError('synthetic failure after constraint addition')

        with patch.object(operation, 'database_forwards', side_effect=fail_after_add):
            with self.assertRaisesMessage(RuntimeError, 'synthetic failure after constraint addition'):
                executor.migrate(self.after)
        self.assertNotIn(self.after[0], MigrationRecorder(connection).applied_migrations())
        self.assertEqual(self.Product.objects.values().get(pk=item.pk), before)
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, 'catalog_productpresentation')
        self.assertNotIn('catalog_published_requires_verified', constraints)
        self.upgrade()

    def test_constraint_lock_persists_until_outer_transaction_commits(self):
        def read_with_timeout():
            close_old_connections()
            try:
                with self.assertRaises(OperationalError) as error, transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '300ms'")
                        cursor.execute('SELECT count(*) FROM catalog_productpresentation')
                return getattr(error.exception.__cause__, 'sqlstate', None)
            finally:
                connection.close()

        with transaction.atomic():
            self.upgrade()
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(read_with_timeout).result(timeout=10), '55P03')
        with connection.cursor() as cursor:
            cursor.execute('SELECT count(*) FROM catalog_productpresentation')
            self.assertEqual(cursor.fetchone()[0], 0)
        self.assertIn(self.after[0], MigrationRecorder(connection).applied_migrations())

    def test_existing_reader_can_block_constraint_migration(self):
        ready, release = Event(), Event()

        def hold_reader():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT count(*) FROM catalog_productpresentation')
                        cursor.fetchone()
                    ready.set()
                    if not release.wait(10):
                        raise TimeoutError('Synthetic reader was not released')
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(hold_reader)
            try:
                self.assertTrue(ready.wait(8))
                with self.assertRaises(OperationalError) as error, transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '300ms'")
                    self.upgrade()
                self.assertEqual(getattr(error.exception.__cause__, 'sqlstate', None), '55P03')
                self.assertNotIn(self.after[0], MigrationRecorder(connection).applied_migrations())
            finally:
                release.set()
            future.result(timeout=10)
        self.upgrade()
        self.assertIn(self.after[0], MigrationRecorder(connection).applied_migrations())
