import io
from collections import OrderedDict
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from catalog.models import ProductPresentation
from catalog.normalization import normalize_search
from pricing.importer import (IDENTITY_FIELDS, MAX_CACHED_IRCS, MAX_MATCH_CANDIDATES, MAX_ROWS,
                              _load_irc_index, stage_csv, suggest_product)
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes


class PriceIRCMatchCacheTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user('irc-cache-stager', is_staff=True)
        cls.actor.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
                                       codename__in=['view_pricecandidate', 'add_pricecandidate']))
        cls.product_data = {'name_fa': 'فرآورده ساختگی', 'name_en': 'Synthetic', 'manufacturer': 'شرکت فرضی',
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
                         staged_by=self.actor, commit=commit, rights_attested=commit, on_staged=callback)

    def reference_match(self, row):
        # Reference implementation of the pre-optimization matching semantics.
        identity = {key: normalize_search(row[key]) for key in IDENTITY_FIELDS}
        products = list(ProductPresentation.objects.filter(irc_normalized=identity['irc']).order_by('pk')[:101])
        if len(products) > MAX_MATCH_CANDIDATES:
            return 'ambiguous', None
        matches = [p for p in products if normalize_search(p.irc) == identity['irc'] and all(
            normalize_search(getattr(p, field)) == identity[field] for field in IDENTITY_FIELDS[1:])]
        return (('suggested', matches[0].pk) if len(matches) == 1 else
                ('ambiguous', None) if len(matches) > 1 else ('unmatched', None))

    def test_static_equivalence_and_one_query_for_distinct_identities_same_irc(self):
        ProductPresentation.objects.create(**{**self.product_data, 'strength': '20 mg'})
        ProductPresentation.objects.create(**{**self.product_data, 'strength': '20 mg'})
        stale = ProductPresentation.objects.create(**{**self.product_data, 'strength': '30 mg'})
        ProductPresentation.objects.filter(pk=stale.pk).update(irc='غيرمرتبط')  # stale stored index
        rows = [self.row, {**self.row, 'strength': '۲۰ mg'}, {**self.row, 'strength': '30 mg'},
                {**self.row, 'strength': '40 mg'}, {**self.row, 'manufacturer': 'دیگر'}]
        expected = [self.reference_match(row) for row in rows]
        self.assertEqual(expected, [('suggested', self.product.pk), ('ambiguous', None),
                                    ('unmatched', None), ('unmatched', None), ('unmatched', None)])
        for row, (status, pk) in zip(rows, expected):
            actual_status, product = suggest_product(row)
            self.assertEqual((actual_status, product.pk if product else None), (status, pk))
        rows = [{**row, 'source_record_id': f'item-{i}'} for i, row in enumerate(rows)]
        with patch('pricing.importer._load_irc_index', wraps=_load_irc_index) as loads:
            counts = self.stage(rows, commit=True)
        self.assertEqual(loads.call_count, 1)
        self.assertEqual((counts['suggested'], counts['ambiguous'], counts['unmatched']), (1, 1, 3))
        candidates = {c.source_record_id: c for c in PriceCandidate.objects.all()}
        for i, (status, product_id) in enumerate(expected):
            self.assertEqual((candidates[f'item-{i}'].match_status, candidates[f'item-{i}'].suggested_product_id),
                             (status, product_id))

    def test_full_preview_distinct_identities_same_irc_uses_one_catalog_query(self):
        rows = [{**self.row, 'source_record_id': f'id-{i}', 'strength': f'{i} mg'} for i in range(MAX_ROWS)]
        self.assertTrue(self.actor.has_perm('pricing.view_pricecandidate'))
        with CaptureQueriesContext(connection) as queries:
            counts = self.stage(rows)
        selects = [q['sql'] for q in queries if q['sql'].lstrip().upper().startswith('SELECT')]
        self.assertEqual(len(selects), 1)
        self.assertEqual(counts['rows'], MAX_ROWS)
        self.assertEqual(counts['suggested'], 1)
        self.assertEqual(counts['unmatched'], MAX_ROWS - 1)
        self.assertFalse(PriceCandidate.objects.exists())

    def test_exact_cap_and_over_cap_remain_conservative_even_for_stale_index(self):
        for i in range(99):
            ProductPresentation.objects.create(**{**self.product_data, 'strength': f'{i + 100} mg'})
        unmatched = {**self.row, 'strength': '999 mg'}
        self.assertEqual(self.reference_match(self.row), ('suggested', self.product.pk))
        self.assertEqual(self.reference_match(unmatched), ('unmatched', None))
        counts = self.stage([self.row, unmatched])
        self.assertEqual((counts['suggested'], counts['unmatched']), (1, 1))
        stale = ProductPresentation.objects.create(**{**self.product_data, 'strength': '888 mg'})
        ProductPresentation.objects.filter(pk=stale.pk).update(irc='not-the-index')
        self.assertEqual(self.reference_match(self.row), ('ambiguous', None))
        self.assertEqual(self.reference_match(unmatched), ('ambiguous', None))
        with patch('pricing.importer._load_irc_index', wraps=_load_irc_index) as loads:
            counts = self.stage([self.row, unmatched])
        self.assertEqual(loads.call_count, 1)
        self.assertEqual(counts['ambiguous'], 2)

    def test_same_irc_different_identity_reuses_first_candidate_set(self):
        rows = [self.row, {**self.row, 'source_record_id': 'new-strength', 'strength': '10 mg'}]
        def change_catalog(candidate_id, source_id, payload, created, status):
            if source_id == 'synthetic-1':
                ProductPresentation.objects.filter(pk=self.product.pk).update(strength='10 mg')
        with patch('pricing.importer._load_irc_index', wraps=_load_irc_index) as loads:
            counts = self.stage(rows, commit=True, callback=change_catalog)
        self.assertEqual(loads.call_count, 1)
        self.assertEqual((counts['suggested'], counts['unmatched']), (1, 1))
        candidate = PriceCandidate.objects.get(source_record_id='new-strength')
        self.assertEqual(candidate.match_status, 'unmatched')
        self.assertEqual(self.stage([rows[1]])['suggested'], 1)

    def test_lru_bound_eviction_and_reused_identity_across_eviction(self):
        observed_sizes = []
        class TrackingOrderedDict(OrderedDict):
            def __setitem__(self, key, value):
                super().__setitem__(key, value)
                observed_sizes.append(len(self))
        rows = [{**self.row, 'source_record_id': 'a-first'}]
        rows += [{**self.row, 'source_record_id': f'b-{i}', 'irc': str(9000 + i)} for i in range(MAX_CACHED_IRCS)]
        rows += [{**self.row, 'source_record_id': 'a-new', 'strength': '10 mg'},
                 {**self.row, 'source_record_id': 'a-old'}]
        def mutate(candidate_id, source_id, payload, created, status):
            if source_id == 'a-first':
                ProductPresentation.objects.filter(pk=self.product.pk).update(strength='10 mg')
        with patch('pricing.importer.OrderedDict', TrackingOrderedDict), \
             patch('pricing.importer._load_irc_index', wraps=_load_irc_index) as loads:
            result = self.stage(rows, commit=True, callback=mutate)
        self.assertEqual(max(observed_sizes), MAX_CACHED_IRCS)
        self.assertEqual(loads.call_count, MAX_CACHED_IRCS + 2)
        self.assertEqual(result['suggested'], 3)
        self.assertEqual(result['unmatched'], MAX_CACHED_IRCS)
        records = {c.source_record_id: c for c in PriceCandidate.objects.all()}
        self.assertEqual([records[key].match_status for key in ['a-first', 'a-new', 'a-old']], ['suggested'] * 3)
        # The same old identity remains cached even after its IRC bucket is evicted.
        self.assertEqual(self.stage([self.row])['unmatched'], 1)

    def test_lru_recency_on_new_identity_with_existing_irc(self):
        rows = [{**self.row, 'irc': str(8000 + i), 'strength': '1 mg'} for i in range(MAX_CACHED_IRCS)]
        rows += [{**self.row, 'irc': '8000', 'strength': '2 mg'},
                 {**self.row, 'irc': '9000', 'strength': '1 mg'},
                 {**self.row, 'irc': '8000', 'strength': '3 mg'},
                 {**self.row, 'irc': '8001', 'strength': '2 mg'}]
        with patch('pricing.importer._load_irc_index', wraps=_load_irc_index) as loads:
            counts = self.stage(rows)
        self.assertEqual(counts['unmatched'], len(rows))
        self.assertEqual(loads.call_count, MAX_CACHED_IRCS + 2)
        loaded_ircs = [call.args[0] for call in loads.call_args_list]
        self.assertEqual(loaded_ircs.count('8000'), 1)
        self.assertEqual(loaded_ircs.count('8001'), 2)

    def test_unpublished_presentation_remains_only_an_unverified_suggestion(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(published=False, verified_at=None)
        self.assertEqual(self.reference_match(self.row), ('suggested', self.product.pk))
        status, product = suggest_product(self.row)
        self.assertEqual((status, product.pk), ('suggested', self.product.pk))
        counts = self.stage([self.row], commit=True)
        self.assertEqual(counts['suggested'], 1)
        self.assertEqual(PriceCandidate.objects.get().suggested_product_id, self.product.pk)

    def test_locked_fresh_match_still_locks_candidates(self):
        with CaptureQueriesContext(connection) as queries:
            status, product = suggest_product(self.row, lock=True)
        self.assertEqual((status, product.pk), ('suggested', self.product.pk))
        self.assertEqual(len(queries), 1)
        self.assertIn('FOR UPDATE', queries[0]['sql'].upper())
