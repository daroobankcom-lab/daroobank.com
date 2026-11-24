"""Synthetic bounds for selected related-candidate comparison reads."""
from unittest.mock import patch

from django.db import connection
from django.db.models import TextField, JSONField, Value
from django.db.models.functions import Cast, Length
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog.comparisons import product_comparison_context
from catalog.models import ProductCandidate
from catalog import test_comparisons as product_fixtures
from pricing.comparisons import price_revision_context
from pricing.models import PriceCandidate
from pricing import test_comparisons as price_fixtures


class ProductRelatedCandidateBoundsTests(TestCase):
    stage = product_fixtures.ProductComparisonTests.stage

    @classmethod
    def setUpTestData(cls):
        product_fixtures.ProductComparisonTests.setUpTestData.__func__(cls)

    def test_oversized_related_candidate_is_uninspected_and_not_linked(self):
        current = self.stage()
        revision = self.stage({**self.row, 'strength': '10 mg'})
        other = self.stage({**self.row, 'source_record_id': 'other-secret'})
        ProductCandidate.objects.filter(pk__in=[revision.pk, other.pk]).update(source_fields={'canary': 'آ' * 1_000_000})
        from catalog.comparisons import valid_candidate
        def validate(candidate):
            self.assertNotIn(candidate.pk, (revision.pk, other.pk), 'oversized candidate must not reach validator')
            return valid_candidate(candidate)
        with patch('catalog.comparisons.valid_candidate', side_effect=validate):
            with CaptureQueriesContext(connection) as queries:
                context = product_comparison_context(current)
            self.assertEqual(context['revisions'][0]['status'], 'oversized')
            self.assertFalse(context['revisions'][0]['valid'])
            self.assertEqual(context['candidate_oversized'], 2)
            self.assertEqual(context['candidate_skipped'], 0)
            for query in queries:
                if 'FROM "catalog_productcandidate"' in query['sql']:
                    select = query['sql'].split(' FROM ', 1)[0].lower()
                    self.assertIn('case', select)
                    self.assertNotRegex(select, r'(?:^select |, )"catalog_productcandidate"\."source_fields"(?:,|$)')
            self.client.force_login(self.viewer)
            response = self.client.get(reverse('staff_product_detail', args=[current.pk]))
            self.assertContains(response, 'بیش از حد بررسی است؛ مقایسه نشد')
            self.assertNotContains(response, 'canary')
            self.assertNotContains(response, reverse('staff_product_detail', args=[revision.pk]))
            self.assertNotContains(response, reverse('staff_product_detail', args=[other.pk]))
            self.assertIn('no-store', response['Cache-Control'])

    def test_json_text_boundaries_and_null_remain_distinct(self):
        current = self.stage()
        other = self.stage({**self.row, 'strength': '10 mg'})
        for length in (65536, 65537):
            ProductCandidate.objects.filter(pk=other.pk).update(source_fields={'x': 'آ' * (length - len('{"x": ""}'))})
            self.assertEqual(ProductCandidate.objects.annotate(n=Length(Cast('source_fields', TextField()))).get(pk=other.pk).n, length)
            context = product_comparison_context(current)
            self.assertEqual(context['revisions'][0]['status'], 'invalid' if length == 65536 else 'oversized')
            self.assertEqual(context['candidate_skipped'], int(length == 65536))
            self.assertEqual(context['candidate_oversized'], int(length == 65537))
        ProductCandidate.objects.filter(pk=other.pk).update(source_fields=Value(None, output_field=JSONField()))
        self.assertEqual(product_comparison_context(current)['revisions'][0]['status'], 'invalid')

    def test_sentinel_is_bounded_without_changing_limit(self):
        current = self.stage()
        sentinel = self.stage({**self.row, 'strength': '1 mg'})
        for i in range(10):
            self.stage({**self.row, 'strength': f'{i+2} mg'})
        ProductCandidate.objects.filter(pk=sentinel.pk).update(source_fields={'canary': 'آ' * 1_000_000})
        from daroobank.candidate_content_bounds import bounded_candidates
        with CaptureQueriesContext(connection) as queries:
            batch = list(bounded_candidates(ProductCandidate.objects.filter(source_url=current.source_url,
                source_record_id=current.source_record_id).exclude(pk=current.pk).order_by('-pk'))[:11])
        self.assertEqual(len(queries), 1)
        self.assertEqual(batch[-1].pk, sentinel.pk)
        self.assertIsNone(batch[-1]._bounded_candidate_json)
        self.assertIn('source_fields', batch[-1].get_deferred_fields())
        context = product_comparison_context(current)
        self.assertEqual(len(context['revisions']), 10)
        self.assertTrue(context['revisions_limited'])
        self.assertTrue(all(item['valid'] for item in context['revisions']))


class PriceRelatedCandidateBoundsTests(TestCase):
    stage = price_fixtures.PriceComparisonTests.stage

    @classmethod
    def setUpTestData(cls):
        price_fixtures.PriceComparisonTests.setUpTestData.__func__(cls)

    def test_boundaries_null_and_price_sentinel(self):
        current = self.stage()
        sentinel = self.stage({**self.row, 'amount': '20'})
        for i in range(10):
            self.stage({**self.row, 'amount': str(i + 21)})
        PriceCandidate.objects.filter(pk=sentinel.pk).update(source_fields={'x': 'آ' * 1_000_000})
        from daroobank.candidate_content_bounds import bounded_candidates
        batch = list(bounded_candidates(PriceCandidate.objects.filter(source_url=current.source_url,
            source_record_id=current.source_record_id).exclude(pk=current.pk).order_by('-pk'))[:11])
        self.assertEqual(batch[-1].pk, sentinel.pk)
        self.assertIsNone(batch[-1]._bounded_candidate_json)
        self.assertIn('source_fields', batch[-1].get_deferred_fields())
        ctx = price_revision_context(current)
        self.assertTrue(ctx['limited'])
        self.assertEqual(len(ctx['revisions']), 10)
        self.assertTrue(all(item['valid'] for item in ctx['revisions']))
        other_id = ctx['revisions'][0]['candidate'].pk
        for length in (65536, 65537):
            PriceCandidate.objects.filter(pk=other_id).update(source_fields={'x': 'آ' * (length - len('{"x": ""}'))})
            self.assertEqual(PriceCandidate.objects.annotate(n=Length(Cast('source_fields', TextField()))).get(pk=other_id).n, length)
            self.assertEqual(price_revision_context(current)['revisions'][0]['status'], 'invalid' if length == 65536 else 'oversized')
        PriceCandidate.objects.filter(pk=other_id).update(source_fields=Value(None, output_field=JSONField()))
        self.assertEqual(price_revision_context(current)['revisions'][0]['status'], 'invalid')

    def test_oversized_revision_is_uninspected_no_arithmetic_and_not_linked(self):
        current = self.stage()
        other = self.stage({**self.row, 'amount': '99'})
        PriceCandidate.objects.filter(pk=other.pk).update(source_fields={'canary': 'آ' * 1_000_000})
        from pricing.comparisons import valid_candidate
        def validate(candidate):
            self.assertNotEqual(candidate.pk, other.pk, 'oversized candidate must not reach validator')
            return valid_candidate(candidate)
        with patch('pricing.comparisons.valid_candidate', side_effect=validate):
            with CaptureQueriesContext(connection) as queries:
                context = price_revision_context(current)
            item = context['revisions'][0]
            self.assertEqual(item['status'], 'oversized')
            self.assertFalse(item['valid'])
            self.assertIsNone(item['delta_rial'])
            select = queries[0]['sql'].split(' FROM ', 1)[0].lower()
            self.assertIn('case', select)
            self.assertNotRegex(select, r'(?:^select |, )"pricing_pricecandidate"\."source_fields"(?:,|$)')
            self.client.force_login(self.viewer)
            response = self.client.get(reverse('staff_price_detail', args=[current.pk]))
            self.assertContains(response, 'بیش از حد بررسی است؛ مقایسه نشد')
            self.assertNotContains(response, 'canary')
            self.assertNotContains(response, reverse('staff_price_detail', args=[other.pk]))
            self.assertIn('no-store', response['Cache-Control'])
