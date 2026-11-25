"""Upgrade a synthetic database with existing unrelated records."""
from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from catalog.models import ProductPresentation
from .models import StaffLoginWindow


class StaffSecurityMigrationTests(TransactionTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(self.restore_migrations)
        executor = MigrationExecutor(connection)
        executor.migrate([('staff_security', None)])
        self.assertNotIn(StaffLoginWindow._meta.db_table, connection.introspection.table_names())
        self.user = get_user_model().objects.create_user('synthetic-before-security-migration', is_staff=True)
        self.product = ProductPresentation.objects.create(
            name_fa='نام ساختگی', name_en='Synthetic', manufacturer='سازنده ساختگی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', source_name='منبع ساختگی',
            source_url='https://example.org/synthetic')
        MigrationExecutor(connection).migrate([('staff_security', '0001_initial')])

    def restore_migrations(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_new_empty_window_table_preserves_existing_synthetic_records(self):
        self.assertIn(StaffLoginWindow._meta.db_table, connection.introspection.table_names())
        self.assertFalse(StaffLoginWindow.objects.exists())
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk, username=self.user.username).exists())
        self.assertTrue(ProductPresentation.objects.filter(pk=self.product.pk, name_fa=self.product.name_fa).exists())
        self.assertEqual(StaffLoginWindow._meta.default_permissions, ())
