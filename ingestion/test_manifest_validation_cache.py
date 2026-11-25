"""Synthetic operation-count and safety tests for request-local receipt validation reuse."""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from catalog.comparisons import valid_candidate as valid_product
from catalog.models import ProductCandidate
from catalog.test_intake import make_csv
from pricing.comparisons import valid_candidate as valid_price
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes
from .manifest_inspection import BATCH_SIZE, inspect_manifest
from .models import ImportReceiptItem
from .receipts import manifest_context, manifest_item_safe, stage_price_with_receipt, stage_product_with_receipt


class ManifestValidationCacheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.actor = User.objects.create_user('receipt-cache-stager', is_staff=True)
        for app, names in [('catalog', ['view_productcandidate', 'add_productcandidate']),
                           ('pricing', ['view_pricecandidate', 'add_pricecandidate'])]:
            cls.actor.user_permissions.add(*Permission.objects.filter(content_type__app_label=app, codename__in=names))
        cls.product_row = dict(source_record_id='sample-product', name_fa='فرآورده ساختگی', name_en='Synthetic',
            manufacturer='سازنده فرضی', strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        cls.price_row = dict(source_record_id='sample-price', irc='001', manufacturer='سازنده فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
            unit='package', effective_date='', source_published_date='')

    def create(self, kind, rows):
        if kind == 'product':
            return stage_product_with_receipt(io.BytesIO(make_csv(rows)), 'منبع ساختگی', 'https://example.org/product',
                                              actor=self.actor, rights_attested=True)[1]
        return stage_price_with_receipt(io.BytesIO(csv_bytes(rows)), 'منبع ساختگی', 'https://example.org/price',
                                        actor=self.actor, rights_attested=True)[1]

    def scan(self, receipt, **kwargs):
        return inspect_manifest(actor=self.actor, receipt_id=receipt.pk, **kwargs)

    def test_duplicate_rows_reuse_candidate_checks_but_not_item_comparisons(self):
        for kind, row, validator in [('product', self.product_row, valid_product), ('price', self.price_row, valid_price)]:
            with self.subTest(kind=kind):
                receipt = self.create(kind, [row] * (BATCH_SIZE + 6))
                self.assertEqual((receipt.created, receipt.duplicates), (1, BATCH_SIZE + 5))
                # First item's mismatch must not poison other items, even when
                # they all point to the same candidate.
                ImportReceiptItem.objects.filter(receipt=receipt, ordinal__in=[1, 3]).update(payload_sha256='0' * 64)
                before = list(receipt.items.values())
                patch_name = f'ingestion.receipts.valid_{kind}'
                self.actor.has_perm(f'{"catalog" if kind == "product" else "pricing"}.view_{kind}candidate')
                with patch(patch_name, wraps=validator) as validate, CaptureQueriesContext(connection) as queries:
                    result = self.scan(receipt)
                self.assertEqual(len(queries), 3)
                self.assertEqual(validate.call_count, 1)
                self.assertEqual(result['rows'][0]['status'], 'inconsistent')
                self.assertEqual(result['rows'][2]['status'], 'inconsistent')
                self.assertTrue(all(item['status'] == 'consistent' for i, item in enumerate(result['rows']) if i not in (0, 2)))
                with patch(patch_name, wraps=validator) as validate, CaptureQueriesContext(connection) as queries:
                    detail = manifest_context(receipt, 1)
                self.assertEqual(len(queries), 3)  # aggregate, paginator count, page join
                self.assertEqual(validate.call_count, 1)
                self.assertFalse(detail['page'].object_list[0].safe)
                self.assertFalse(detail['page'].object_list[2].safe)
                self.assertTrue(all(item.safe for i, item in enumerate(detail['page'].object_list) if i not in (0, 2)))
                with patch(patch_name, wraps=validator) as validate:
                    second = self.scan(receipt, after=BATCH_SIZE)
                self.assertEqual(validate.call_count, 1)  # a new request never shares the cache
                self.assertEqual(second['scanned'], 6)
                self.assertEqual(before, list(receipt.items.values()))

    def test_inconsistent_candidate_and_validator_errors_reused_only_in_one_page(self):
        for kind, row, model, validator, field in [('product', self.product_row, ProductCandidate, valid_product, 'product_candidate_id'),
                                                    ('price', self.price_row, PriceCandidate, valid_price, 'price_candidate_id')]:
            with self.subTest(kind=kind):
                receipt = self.create(kind, [row] * 51)
                item = receipt.items.first()
                patch_name = f'ingestion.receipts.valid_{kind}'
                with patch(patch_name, wraps=validator) as validate:
                    first = self.scan(receipt)
                self.assertEqual(validate.call_count, 1)
                self.assertTrue(all(row['status'] == 'consistent' for row in first['rows']))
                model.objects.filter(pk=getattr(item, field)).update(source_fields={'bad': 'private'})
                with patch(patch_name, wraps=validator) as validate:
                    second = self.scan(receipt, after=BATCH_SIZE)
                self.assertEqual(validate.call_count, 1)
                self.assertEqual(second['rows'], [{'ordinal': 51, 'status': 'inconsistent'}])
                with patch(patch_name, side_effect=ValueError('synthetic invalid candidate')) as validate:
                    failed = self.scan(receipt)
                self.assertEqual(validate.call_count, 1)
                self.assertTrue(all(row['status'] == 'inconsistent' for row in failed['rows']))

    def test_distinct_candidates_are_checked_separately_and_lookahead_not_validated(self):
        for kind, row, validator in [('product', self.product_row, valid_product), ('price', self.price_row, valid_price)]:
            with self.subTest(kind=kind):
                rows = [{**row, 'source_record_id': f'distinct-{kind}-{i}'} for i in range(BATCH_SIZE + 1)]
                receipt = self.create(kind, rows)
                cache_sizes = []
                def tracking(receipt, item, *, _candidate_cache):
                    result = manifest_item_safe(receipt, item, _candidate_cache=_candidate_cache)
                    cache_sizes.append(len(_candidate_cache))
                    return result
                with patch(f'ingestion.receipts.valid_{kind}', wraps=validator) as validate, \
                     patch('ingestion.manifest_inspection.manifest_item_safe', side_effect=tracking):
                    result = self.scan(receipt)
                self.assertEqual(validate.call_count, BATCH_SIZE)
                self.assertEqual(max(cache_sizes), BATCH_SIZE)
                self.assertEqual((result['scanned'], result['next_after']), (BATCH_SIZE, BATCH_SIZE))
                self.assertTrue(all(row['status'] == 'consistent' for row in result['rows']))

    def test_standalone_single_item_checks_never_share_state(self):
        receipt = self.create('product', [self.product_row])
        item = receipt.items.select_related('product_candidate').first()
        with patch('ingestion.receipts.valid_product', wraps=valid_product) as validate:
            self.assertTrue(manifest_item_safe(receipt, item))
            self.assertTrue(manifest_item_safe(receipt, item))
        self.assertEqual(validate.call_count, 2)
