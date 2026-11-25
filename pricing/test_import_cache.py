import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from catalog.models import ProductPresentation
from ingestion.models import ImportReceipt, ImportReceiptItem
from ingestion.receipts import stage_price_with_receipt
from pricing.importer import ImportValidationError, MAX_ROWS, _match_index, stage_csv, suggest_product
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes


class PriceImportCacheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user('synthetic-cache-stager', is_staff=True)
        cls.actor.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
                                       codename__in=['view_pricecandidate', 'add_pricecandidate']))
        cls.product_data = {'name_fa': 'محصول ساختگی', 'name_en': 'Synthetic', 'manufacturer': 'شرکت فرضی',
                            'strength': '۵ mg', 'dosage_form': 'قرص', 'package_description': '۱۰ عدد',
                            'irc': '001234', 'source_name': 'منبع ساختگی', 'source_url': 'https://example.org/product',
                            'published': True, 'verified_at': timezone.now()}
        cls.product = ProductPresentation.objects.create(**cls.product_data)
        cls.row = {'source_record_id': 'synthetic-1', 'irc': '۰۰۱۲۳۴', 'manufacturer': 'شركت فرضی',
                   'strength': '5 mg', 'dosage_form': 'قرص', 'package_description': '10 عدد',
                   'amount': '100', 'currency': 'RIAL', 'category': 'retail', 'unit': 'package',
                   'effective_date': '', 'source_published_date': ''}

    def stage(self, rows, *, commit=False, callback=None):
        return stage_csv(io.BytesIO(csv_bytes(rows)), 'منبع ساختگی', 'https://example.org/source',
                         commit=commit, rights_attested=commit, staged_by=self.actor, on_staged=callback)

    def test_repeated_normalized_identity_queries_once_preserves_rows_and_receipt(self):
        rows = [self.row, {**self.row, 'irc': '001234', 'manufacturer': 'شرکت فرضی',
                           'strength': '۵ mg', 'package_description': '۱۰ عدد',
                           'source_record_id': 'synthetic-2', 'amount': '200'}, self.row]
        expected = [suggest_product(row)[0] for row in rows]
        with patch('pricing.importer._match_index', wraps=_match_index) as lookup:
            result, receipt = stage_price_with_receipt(io.BytesIO(csv_bytes(rows)), 'منبع ساختگی',
                                    'https://example.org/source', actor=self.actor, rights_attested=True)
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(expected, ['suggested'] * 3)
        self.assertEqual(result, {'rows': 3, 'suggested': 3, 'ambiguous': 0, 'unmatched': 0, 'created': 2, 'duplicates': 1})
        items = list(receipt.items.order_by('ordinal'))
        self.assertEqual([item.match_status for item in items], expected)
        self.assertEqual([item.was_created for item in items], [True, True, False])
        self.assertEqual(items[0].price_candidate_id, items[2].price_candidate_id)
        self.assertEqual(items[1].price_candidate.source_fields['manufacturer'], 'شرکت فرضی')
        self.assertEqual(items[1].price_candidate.amount_rial, 200)
        self.assertTrue(all(item.price_candidate.suggested_product_id == self.product.pk for item in items))
        self.assertEqual(ImportReceiptItem.objects.count(), 3)

    def test_all_statuses_distinct_keys_and_fresh_cache_on_each_call(self):
        ProductPresentation.objects.create(**self.product_data)
        rows = [self.row, {**self.row, 'source_record_id': 'same'},
                {**self.row, 'irc': '9999'}, {**self.row, 'irc': '9999', 'amount': '200'},
                {**self.row, 'manufacturer': 'دیگر'}]
        # An ambiguous IRC with no exact matches is still ambiguous, per the >100 rule only;
        # with two indexed candidates this third identity is simply unmatched.
        expected = [suggest_product(row)[0] for row in rows]
        self.assertEqual(expected, ['ambiguous', 'ambiguous', 'unmatched', 'unmatched', 'unmatched'])
        for _ in range(2):
            with patch('pricing.importer._match_index', wraps=_match_index) as lookup:
                counts = self.stage(rows)
            self.assertEqual(lookup.call_count, 3)
            self.assertEqual([counts[s] for s in ['ambiguous', 'unmatched']], [2, 3])
        self.assertEqual(PriceCandidate.objects.count(), 0)
        self.assertEqual(ImportReceipt.objects.count(), 0)

    def test_each_matching_field_participates_in_cache_key(self):
        rows = [self.row]
        for field, value in [('irc', '333'), ('manufacturer', 'سازنده دیگر'), ('strength', '20 mg'),
                             ('dosage_form', 'شربت'), ('package_description', '20 عدد')]:
            rows.append({**self.row, field: value})
        rows.extend([dict(row) for row in rows])
        with patch('pricing.importer._match_index', wraps=_match_index) as lookup:
            counts = self.stage(rows)
        self.assertEqual(lookup.call_count, 6)
        self.assertEqual(counts['suggested'], 2)
        self.assertEqual(counts['unmatched'], 10)

    def test_full_5000_row_preview_fetches_once_and_writes_nothing(self):
        rows = [{**self.row, 'source_record_id': f'synthetic-{i}'} for i in range(MAX_ROWS)]
        self.actor.has_perm('pricing.view_pricecandidate')
        with CaptureQueriesContext(connection) as queries:
            counts = self.stage(rows)
        reads = [q['sql'] for q in queries if q['sql'].lstrip().upper().startswith('SELECT')]
        self.assertEqual(len(reads), 1)
        self.assertIn('catalog_productpresentation', reads[0])
        self.assertEqual(counts['rows'], MAX_ROWS)
        self.assertEqual(counts['suggested'], MAX_ROWS)
        self.assertEqual(counts['created'], 0)
        self.assertFalse(PriceCandidate.objects.exists())

    def test_many_distinct_keys_have_no_false_cache_hits(self):
        rows = [{**self.row, 'irc': str(i)} for i in range(MAX_ROWS)]
        with patch('pricing.importer._match_index', return_value=('unmatched', None)), \
             patch('pricing.importer._load_irc_index', return_value={}) as lookup:
            counts = self.stage(rows)
        self.assertEqual(lookup.call_count, MAX_ROWS)
        self.assertEqual(counts['unmatched'], MAX_ROWS)

    def test_oversized_ambiguous_set_is_cached_without_false_unique(self):
        for _ in range(100): ProductPresentation.objects.create(**self.product_data)
        rows = [self.row, {**self.row, 'source_record_id': 'other'}]
        with patch('pricing.importer._match_index', wraps=_match_index) as lookup:
            counts = self.stage(rows, commit=True)
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(counts['ambiguous'], 2)
        self.assertTrue(all(c.suggested_product_id is None for c in PriceCandidate.objects.all()))

    def test_replay_preserves_original_candidate_but_receipt_records_request_suggestion(self):
        ProductPresentation.objects.filter(pk=self.product.pk).delete()
        first, _ = stage_price_with_receipt(io.BytesIO(csv_bytes([self.row])), 'منبع ساختگی',
                           'https://example.org/source', actor=self.actor, rights_attested=True)
        candidate = PriceCandidate.objects.get()
        self.assertEqual(first['unmatched'], 1)
        self.assertEqual(candidate.match_status, 'unmatched')
        ProductPresentation.objects.create(**self.product_data)
        with patch('pricing.importer._match_index', wraps=_match_index) as lookup:
            result, receipt = stage_price_with_receipt(io.BytesIO(csv_bytes([self.row, self.row])), 'منبع ساختگی',
                                  'https://example.org/source', actor=self.actor, rights_attested=True)
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual((result['suggested'], result['duplicates'], result['created']), (2, 2, 0))
        candidate.refresh_from_db()
        self.assertEqual(candidate.match_status, 'unmatched')
        self.assertIsNone(candidate.suggested_product_id)
        self.assertEqual(list(receipt.items.values_list('match_status', flat=True)), ['suggested', 'suggested'])
        self.assertEqual(set(receipt.items.values_list('price_candidate_id', flat=True)), {candidate.pk})

    def test_same_request_reuses_first_observation_next_call_refreshes(self):
        rows = [self.row, {**self.row, 'source_record_id': 'synthetic-2'}]
        def mutate_catalog(candidate_id, source_id, payload, created, status):
            if source_id == 'synthetic-1':
                ProductPresentation.objects.filter(pk=self.product.pk).update(manufacturer='تغییر همزمان ساختگی')
        counts = self.stage(rows, commit=True, callback=mutate_catalog)
        self.assertEqual(counts['suggested'], 2)
        self.assertEqual(set(PriceCandidate.objects.values_list('match_status', flat=True)), {'suggested'})
        self.assertEqual(self.stage(rows)['unmatched'], 2)

    def test_failure_rolls_back_and_invalid_file_never_queries_matches(self):
        rows = [self.row, {**self.row, 'source_record_id': 'synthetic-2'}]
        def fail(candidate_id, source_id, payload, created, status):
            if source_id == 'synthetic-2': raise ValueError('synthetic callback failure')
        with self.assertRaises(ValueError): self.stage(rows, commit=True, callback=fail)
        self.assertEqual(PriceCandidate.objects.count(), 0)
        with patch('pricing.importer._match_index', wraps=_match_index) as lookup:
            with self.assertRaises(ImportValidationError):
                self.stage([self.row, {**self.row, 'currency': 'INVALID'}], commit=True)
        self.assertEqual(lookup.call_count, 0)
        self.assertFalse(PriceCandidate.objects.exists())
