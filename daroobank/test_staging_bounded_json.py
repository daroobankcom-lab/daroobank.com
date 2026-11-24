"""Synthetic defensive reads for staging replays."""
import io
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog import test_staging_replay_integrity as product_fixtures
from catalog.models import ProductCandidate
from ingestion.exceptions import StagingConflict
from ingestion.models import ImportReceipt, ImportReceiptItem
from pricing import test_staging_replay_integrity as price_fixtures
from pricing.models import PriceCandidate


def inspect_candidate_selects(test, queries, table):
    selects = [q['sql'] for q in queries if f'FROM "{table}"' in q['sql'] and q['sql'].startswith('SELECT')]
    test.assertGreaterEqual(len(selects), 2)
    locked = 0
    for sql in selects:
        select = sql.split(' FROM ', 1)[0].lower()
        test.assertNotRegex(select, rf'(?:^select |, )"{table}"\."source_fields"(?:,|$)')
        if 'FOR UPDATE' in sql:
            locked += 1
            test.assertIn('case', select)
    test.assertGreaterEqual(locked, 1)


@override_settings(STAFF_PORTAL_ENABLED=True)
class ProductStagingBoundsTests(TestCase):
    def setUp(self):
        self.author = product_fixtures.actor('bounded-product-author')
        self.other = product_fixtures.actor('bounded-product-other')
        product_fixtures.stage([product_fixtures.ROW], self.author)
        self.candidate = ProductCandidate.objects.get()
        ProductCandidate.objects.filter(pk=self.candidate.pk).update(source_fields={'private-canary': 'آ' * 1_000_000})

    def test_replay_does_not_transfer_original_and_rolls_back_new_preceding_row(self):
        rows = [{**product_fixtures.ROW, 'source_record_id': 'new-first'}, product_fixtures.ROW]
        with CaptureQueriesContext(connection) as queries:
            with self.assertRaises(StagingConflict):
                product_fixtures.stage(rows, self.other)
        inspect_candidate_selects(self, queries, ProductCandidate._meta.db_table)
        self.assertEqual(ProductCandidate.objects.count(), 1)
        self.assertEqual(ImportReceipt.objects.count(), 1)
        self.assertEqual(ImportReceiptItem.objects.count(), 1)
        self.assertEqual(len(ProductCandidate.objects.get(pk=self.candidate.pk).source_fields['private-canary']), 1_000_000)

    def test_same_request_rechecks_oversized_callback_mutation_and_rolls_back(self):
        row = {**product_fixtures.ROW, 'source_record_id': 'new-in-request'}
        def mutate(candidate_id, source_id, digest, created, status):
            if created:
                ProductCandidate.objects.filter(pk=candidate_id).update(source_fields={'private-canary': 'آ' * 100_000})
        with self.assertRaises(StagingConflict):
            product_fixtures.stage_products(io.BytesIO(product_fixtures.make_csv([row, row])),
                product_fixtures.NAME, product_fixtures.URL, actor=self.author, commit=True,
                rights_attested=True, on_staged=mutate)
        self.assertFalse(ProductCandidate.objects.filter(source_record_id='new-in-request').exists())
        self.assertEqual(ImportReceipt.objects.count(), 1)

    def test_http_conflict_hides_content_and_receipt_unchanged(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse('staff_product_upload'), {'source_name': product_fixtures.NAME,
            'source_url': product_fixtures.URL, 'action': 'stage', 'rights_attested': 'on',
            'csv_file': SimpleUploadedFile('synthetic.csv', product_fixtures.make_csv([product_fixtures.ROW]))})
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, 'private-canary', status_code=409)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(ImportReceipt.objects.count(), 1)


@override_settings(STAFF_PORTAL_ENABLED=True)
class PriceStagingBoundsTests(TestCase):
    def setUp(self):
        self.author = price_fixtures.actor('bounded-price-author')
        self.other = price_fixtures.actor('bounded-price-other')
        price_fixtures.stage([price_fixtures.ROW], self.author)
        self.candidate = PriceCandidate.objects.get()
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(source_fields={'private-canary': 'آ' * 1_000_000})

    def test_replay_does_not_transfer_original_and_rolls_back_new_preceding_row(self):
        rows = [{**price_fixtures.ROW, 'source_record_id': 'new-first'}, price_fixtures.ROW]
        with CaptureQueriesContext(connection) as queries:
            with self.assertRaises(StagingConflict):
                price_fixtures.stage(rows, self.other)
        inspect_candidate_selects(self, queries, PriceCandidate._meta.db_table)
        self.assertEqual(PriceCandidate.objects.count(), 1)
        self.assertEqual(ImportReceipt.objects.count(), 1)
        self.assertEqual(ImportReceiptItem.objects.count(), 1)
        self.assertEqual(len(PriceCandidate.objects.get(pk=self.candidate.pk).source_fields['private-canary']), 1_000_000)

    def test_same_request_rechecks_oversized_callback_mutation_and_rolls_back(self):
        row = {**price_fixtures.ROW, 'source_record_id': 'new-in-request'}
        def mutate(candidate_id, source_id, digest, created, status):
            if created:
                PriceCandidate.objects.filter(pk=candidate_id).update(source_fields={'private-canary': 'آ' * 100_000})
        with self.assertRaises(StagingConflict):
            price_fixtures.stage_direct([row, row], self.author, mutate)
        self.assertFalse(PriceCandidate.objects.filter(source_record_id='new-in-request').exists())
        self.assertEqual(ImportReceipt.objects.count(), 1)

    def test_http_conflict_hides_content_and_receipt_unchanged(self):
        self.client.force_login(self.other)
        response = self.client.post(reverse('staff_price_upload'), {'source_name': price_fixtures.NAME,
            'source_url': price_fixtures.URL, 'action': 'stage', 'rights_attested': 'on',
            'csv_file': SimpleUploadedFile('synthetic.csv', price_fixtures.csv_bytes([price_fixtures.ROW]))})
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, 'private-canary', status_code=409)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(ImportReceipt.objects.count(), 1)
