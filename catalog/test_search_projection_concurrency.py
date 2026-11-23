"""Selected PostgreSQL interleaving for the public search projection recheck."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Event
from unittest.mock import patch

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from .models import ProductPresentation
from .services import is_public_presentation, search_product_page


class SearchProjectionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.product = ProductPresentation.objects.create(
            name_fa='نام ساختگی', name_en='Oldsynthetic', manufacturer='سازنده فرضی',
            strength='5 mg', dosage_form='قرص', package_description='10 عدد',
            source_name='منبع فرضی', source_url='https://example.org/synthetic',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True,
        )

    def _read_with_commit_after_fetch(self, change):
        fetched, resume = Event(), Event()

        def pause_after_fetch(row):
            fetched.set()
            if not resume.wait(8):
                raise TimeoutError('Timed out waiting for synthetic update')
            return is_public_presentation(row)

        def read():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET statement_timeout = '12s'")
                return search_product_page('oldsynthetic')
            finally:
                connection.close()

        with patch('catalog.services.is_public_presentation', side_effect=pause_after_fetch):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(read)
                try:
                    self.assertTrue(fetched.wait(8), 'Search did not fetch its candidate')
                    change(self.product)
                finally:
                    resume.set()
                return future.result(timeout=10)

    def test_committed_change_after_fetch_can_make_returned_observation_stale(self):
        def change(product):
            product.name_en = 'Newsynthetic'
            product.save(update_fields=['name_en'])
        rows, cursor = self._read_with_commit_after_fetch(change)
        # The already-fetched object reflects the earlier SQL statement, even
        # though a normal projection-maintaining update committed before return.
        self.assertEqual([(row.pk, row.name_en) for row in rows], [(self.product.pk, 'Oldsynthetic')])
        self.assertIsNone(cursor)
        self.product.refresh_from_db()
        self.assertEqual(self.product.name_en, 'Newsynthetic')
        self.assertEqual(search_product_page('oldsynthetic')[0], [])
        self.assertEqual([row.pk for row in search_product_page('newsynthetic')[0]], [self.product.pk])

    def test_withdrawal_after_fetch_does_not_retroactively_remove_inflight_result(self):
        def withdraw(product):
            product.published = False
            product.save(update_fields=['published'])
        rows, cursor = self._read_with_commit_after_fetch(withdraw)
        self.assertEqual([row.pk for row in rows], [self.product.pk])
        self.assertTrue(rows[0].published)
        self.assertIsNone(cursor)
        self.product.refresh_from_db()
        self.assertFalse(self.product.published)
        self.assertEqual(search_product_page('oldsynthetic')[0], [])
