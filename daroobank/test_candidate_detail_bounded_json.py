"""Synthetic bounded current-candidate detail and failed-form reads."""
from unittest.mock import patch

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog import test_comparisons as product_fixtures
from catalog.intake import ReviewConflict as ProductConflict, review_product
from catalog.models import ProductCandidate, ProductCandidateReview
from pricing import test_comparisons as price_fixtures
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import ReviewConflict as PriceConflict, record_preliminary_review


class ProductCurrentCandidateBoundsTests(TestCase):
    stage = product_fixtures.ProductComparisonTests.stage

    @classmethod
    def setUpTestData(cls):
        product_fixtures.ProductComparisonTests.setUpTestData.__func__(cls)

    def test_get_and_invalid_post_use_unknown_state_without_classification(self):
        candidate = self.stage()
        ProductCandidate.objects.filter(pk=candidate.pk).update(source_fields={'detail-canary': 'آ' * 1_000_000})
        self.client.force_login(self.reviewer)
        with patch('catalog.comparisons.valid_candidate', side_effect=AssertionError('do not validate oversized candidate')):
            for method, route in [('get', 'staff_product_detail'), ('post', 'staff_product_review')]:
                with self.subTest(method=method), CaptureQueriesContext(connection) as queries:
                    response = getattr(self.client, method)(reverse(route, args=[candidate.pk]), {})
                self.assertEqual(response.status_code, 200 if method == 'get' else 400)
                self.assertContains(response, 'نامزد بیش از حد بررسی است؛ سازگاری بررسی نشد', status_code=response.status_code)
                self.assertNotContains(response, 'detail-canary', status_code=response.status_code)
                self.assertNotContains(response, 'مشخصات ناسازگار نمایش داده نمی‌شوند', status_code=response.status_code)
                self.assertFalse(response.context['can_review'])
                self.assertIn('no-store', response['Cache-Control'])
                selected = [q['sql'] for q in queries if 'FROM "catalog_productcandidate"' in q['sql']]
                self.assertTrue(selected)
                for sql in selected:
                    select = sql.rsplit(' FROM "catalog_productcandidate"', 1)[0].lower()
                    self.assertIn('case', select)
                    self.assertNotRegex(select, r'(?:^select |, )"catalog_productcandidate"\."source_fields"(?:,|$)')
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_review_history_remains_inspected_but_comparison_is_unknown(self):
        candidate = self.stage()
        review_product(candidate_id=candidate.pk, actor=self.reviewer, decision='defer',
            reason='توضیح ساختگی برای بررسی بیشتر', expected_review=0, expected_hash=candidate.payload_sha256)
        ProductCandidate.objects.filter(pk=candidate.pk).update(source_fields={'private-canary': 'آ' * 100_000})
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_product_detail', args=[candidate.pk]))
        self.assertEqual(response.context['reviews'][0].technical_status, 'consistent')
        self.assertEqual(response.context['reviews'][0].candidate_comparison, 'unknown')
        self.assertContains(response, 'مقایسه نامزد نامشخص است')
        self.assertNotContains(response, 'private-canary')

    def test_conflict_refresh_is_also_bounded(self):
        candidate = self.stage()
        self.client.force_login(self.reviewer)
        def conflict(**kwargs):
            ProductCandidate.objects.filter(pk=candidate.pk).update(source_fields={'race-canary': 'آ' * 1_000_000})
            raise ProductConflict('تداخل ساختگی')
        with patch('catalog.staff_views.review_product', side_effect=conflict):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.post(reverse('staff_product_review', args=[candidate.pk]), {
                    'decision': 'defer', 'reason': 'توضیح ساختگی برای بررسی بیشتر',
                    'expected_review': 0, 'expected_hash': candidate.payload_sha256})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'نامزد بیش از حد بررسی است؛ سازگاری بررسی نشد', status_code=409)
        self.assertNotContains(response, 'race-canary', status_code=409)
        selects = [q['sql'] for q in queries if 'FROM "catalog_productcandidate"' in q['sql'] and 'SELECT' in q['sql']]
        self.assertGreaterEqual(len(selects), 2)
        self.assertTrue(all('CASE' in sql for sql in selects))


class PriceCurrentCandidateBoundsTests(TestCase):
    stage = price_fixtures.PriceComparisonTests.stage

    @classmethod
    def setUpTestData(cls):
        price_fixtures.PriceComparisonTests.setUpTestData.__func__(cls)

    def test_get_and_invalid_post_use_unknown_state_without_classification(self):
        candidate = self.stage()
        PriceCandidate.objects.filter(pk=candidate.pk).update(source_fields={'detail-canary': 'آ' * 1_000_000})
        self.client.force_login(self.reviewer)
        with patch('pricing.staff_views.ensure_candidate_integrity', side_effect=AssertionError('do not validate oversized candidate')), \
             patch('pricing.comparisons.valid_candidate', side_effect=AssertionError('do not validate oversized candidate')):
            for method, route in [('get', 'staff_price_detail'), ('post', 'staff_price_review')]:
                with self.subTest(method=method), CaptureQueriesContext(connection) as queries:
                    response = getattr(self.client, method)(reverse(route, args=[candidate.pk]), {})
                self.assertEqual(response.status_code, 200 if method == 'get' else 400)
                self.assertContains(response, 'نامزد بیش از حد بررسی است؛ سازگاری بررسی نشد', status_code=response.status_code)
                self.assertNotContains(response, 'detail-canary', status_code=response.status_code)
                self.assertNotContains(response, 'اطلاعات این رکورد ناسازگار است', status_code=response.status_code)
                self.assertFalse(response.context['can_review'])
                self.assertIn('no-store', response['Cache-Control'])
                selected = [q['sql'] for q in queries if 'FROM "pricing_pricecandidate"' in q['sql']]
                self.assertTrue(selected)
                for sql in selected:
                    select = sql.rsplit(' FROM "pricing_pricecandidate"', 1)[0].lower()
                    self.assertIn('case', select)
                    self.assertNotRegex(select, r'(?:^select |, )"pricing_pricecandidate"\."source_fields"(?:,|$)')
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_review_history_remains_inspected_but_comparison_is_unknown(self):
        candidate = self.stage()
        record_preliminary_review(candidate_id=candidate.pk, actor=self.reviewer, decision='defer',
            reason='توضیح ساختگی برای بررسی بیشتر', expected_review=0, expected_product=0, expected_product_hash='')
        PriceCandidate.objects.filter(pk=candidate.pk).update(source_fields={'private-canary': 'آ' * 100_000})
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_price_detail', args=[candidate.pk]))
        self.assertEqual(response.context['reviews'][0].technical_status, 'consistent')
        self.assertEqual(response.context['reviews'][0].candidate_comparison, 'unknown')
        self.assertContains(response, 'مقایسه نامزد نامشخص است')
        self.assertNotContains(response, 'private-canary')

    def test_conflict_refresh_is_also_bounded(self):
        candidate = self.stage()
        self.client.force_login(self.reviewer)
        def conflict(**kwargs):
            PriceCandidate.objects.filter(pk=candidate.pk).update(source_fields={'race-canary': 'آ' * 1_000_000})
            raise PriceConflict('تداخل ساختگی')
        with patch('pricing.staff_views.record_preliminary_review', side_effect=conflict):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.post(reverse('staff_price_review', args=[candidate.pk]), {
                    'decision': 'defer', 'reason': 'توضیح ساختگی برای بررسی بیشتر',
                    'expected_review': 0, 'expected_product': 0, 'expected_product_hash': ''})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'نامزد بیش از حد بررسی است؛ سازگاری بررسی نشد', status_code=409)
        self.assertNotContains(response, 'race-canary', status_code=409)
        selects = [q['sql'] for q in queries if 'FROM "pricing_pricecandidate"' in q['sql'] and 'SELECT' in q['sql']]
        self.assertGreaterEqual(len(selects), 2)
        self.assertTrue(all('CASE' in sql for sql in selects))
