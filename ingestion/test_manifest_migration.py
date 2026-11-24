"""Synthetic PostgreSQL migration check for pre-manifest intake receipts."""
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from .models import ImportReceipt
from .receipts import manifest_structure


class ReceiptManifestMigrationTests(TransactionTestCase):
    migrate_from = [('ingestion', '0001_initial')]
    migrate_to = [('ingestion', '0002_importreceiptitem_importreceipt_manifest_version_and_more')]

    def setUp(self):
        super().setUp()
        # Register before migration so a setup failure still attempts to restore
        # the test database's normal migration graph. Never run on real data.
        self.addCleanup(self.restore_migrations)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        actor = old_apps.get_model('auth', 'User').objects.create(username='synthetic-receipt-migration')
        Receipt = old_apps.get_model('ingestion', 'ImportReceipt')
        self.product = Receipt.objects.create(
            kind='product', source_name='منبع ساختگی', source_url='https://example.org/product',
            actor_id=actor.pk, rows=3, created=2, duplicates=1)
        self.price = Receipt.objects.create(
            kind='price', source_name='منبع قیمت ساختگی', source_url='https://example.org/price',
            actor_id=actor.pk, rows=4, created=3, duplicates=1, suggested=1, ambiguous=2, unmatched=1)
        self.actor_id = actor.pk
        self.old_product = Receipt.objects.values().get(pk=self.product.pk)
        self.old_price = Receipt.objects.values().get(pk=self.price.pk)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def restore_migrations(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_receipts_survive_as_legacy_without_fabricated_rows(self):
        Receipt = self.apps.get_model('ingestion', 'ImportReceipt')
        Item = self.apps.get_model('ingestion', 'ImportReceiptItem')
        for before, pk in ((self.old_product, self.product.pk), (self.old_price, self.price.pk)):
            with self.subTest(pk=pk):
                after = Receipt.objects.values().get(pk=pk)
                self.assertIsNone(after.pop('manifest_version'))
                self.assertEqual(after, before)
                self.assertEqual(after['actor_id'], self.actor_id)
                current = ImportReceipt.objects.get(pk=pk)
                self.assertEqual(manifest_structure(current), 'legacy')
        self.assertEqual(Item.objects.count(), 0)

    def test_added_version_constraint_rejects_unsupported_values(self):
        Receipt = self.apps.get_model('ingestion', 'ImportReceipt')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Receipt.objects.filter(pk=self.product.pk).update(manifest_version=2)
        self.assertIsNone(Receipt.objects.get(pk=self.product.pk).manifest_version)
        item_table = self.apps.get_model('ingestion', 'ImportReceiptItem')._meta.db_table
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, item_table)
        for name in ('receipt_item_unique_ordinal', 'receipt_item_bounded_ordinal', 'receipt_item_single_domain'):
            self.assertIn(name, constraints, item_table)
