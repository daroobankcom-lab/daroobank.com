"""Selected synthetic database-level publication/date invariant tests."""
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.db import IntegrityError, connection, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from .models import ProductPresentation
from .test_constraint_helpers import omit_publication_date_constraint_for_test


class PublishedDateConstraintTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='فرآورده ساختگی', manufacturer='سازنده ساختگی', strength='1 mg',
            dosage_form='قرص', package_description='10 عدد', source_name='منبع مصنوعی',
            source_url='https://example.org/synthetic', published=False, verified_at=None)

    def test_database_rejects_invalid_publication_even_when_model_save_is_bypassed(self):
        for writer in ('update', 'sql', 'bulk_create'):
            with self.subTest(writer=writer), transaction.atomic():
                with self.assertRaises(IntegrityError) as error, transaction.atomic():
                    if writer == 'update':
                        ProductPresentation.objects.filter(pk=self.product.pk).update(published=True)
                    elif writer == 'sql':
                        with connection.cursor() as cursor:
                            cursor.execute('UPDATE catalog_productpresentation SET published = true WHERE id = %s',
                                           [self.product.pk])
                    else:
                        ProductPresentation.objects.bulk_create([ProductPresentation(
                            name_fa='ساختگی', manufacturer='ساختگی', strength='1 mg', dosage_form='قرص',
                            package_description='10 عدد', source_name='ساختگی', source_url='https://example.org',
                            published=True, verified_at=None)])
                self.assertEqual(getattr(error.exception.__cause__, 'sqlstate', None), '23514')
                self.product.refresh_from_db()
                self.assertFalse(self.product.published)
                self.assertIsNone(self.product.verified_at)
                self.assertEqual(ProductPresentation.objects.count(), 1)

    def test_all_other_boolean_date_combinations_are_permitted(self):
        date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for published, verified_at in ((False, None), (False, date), (True, date)):
            with self.subTest(published=published, verified_at=verified_at):
                ProductPresentation.objects.filter(pk=self.product.pk).update(published=published, verified_at=verified_at)
                self.product.refresh_from_db()
                self.assertEqual((self.product.published, self.product.verified_at), (published, verified_at))


class ConstraintOmissionGuardTests(SimpleTestCase):
    def test_missing_isolation_or_transaction_fails_before_ddl(self):
        valid = dict(vendor='postgresql', in_atomic_block=True,
                     settings_dict={'ENGINE': 'daroobank.isolated_postgresql',
                                    'NAME': 'test_daroobank_synthetic_' + 'a' * 32})
        for override in ({'vendor': 'sqlite'}, {'in_atomic_block': False},
                         {'settings_dict': {'ENGINE': 'django.db.backends.postgresql', 'NAME': valid['settings_dict']['NAME']}},
                         {'settings_dict': {'ENGINE': 'daroobank.isolated_postgresql', 'NAME': 'production'}}):
            fake = SimpleNamespace(**{**valid, **override}, cursor=Mock())
            with self.subTest(override=override), patch('catalog.test_constraint_helpers.connection', fake):
                with self.assertRaises(RuntimeError):
                    omit_publication_date_constraint_for_test()
                fake.cursor.assert_not_called()


class ConstraintOmissionRollbackTests(TransactionTestCase):
    def test_test_only_ddl_and_invalid_row_roll_back_together(self):
        with transaction.atomic():
            omit_publication_date_constraint_for_test()
            ProductPresentation.objects.bulk_create([ProductPresentation(
                name_fa='مصنوعی', manufacturer='مصنوعی', strength='1 mg', dosage_form='قرص',
                package_description='10 عدد', source_name='مصنوعی', source_url='https://example.org',
                published=True, verified_at=None)])
            self.assertEqual(ProductPresentation.objects.count(), 1)
            transaction.set_rollback(True)
        self.assertEqual(ProductPresentation.objects.count(), 0)
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, 'catalog_productpresentation')
        self.assertTrue(constraints['catalog_published_requires_verified']['check'])
