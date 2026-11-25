"""Synthetic bound for candidate queue JSON transferred to the staff UI."""
from unittest.mock import patch

from django.db import connection
from django.db.models import JSONField, Value
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog import test_comparisons as product_fixtures
from catalog.models import ProductCandidate
from pricing import test_comparisons as price_fixtures
from pricing.models import PriceCandidate


class ProductQueueBoundedTests(TestCase):
    stage = product_fixtures.ProductComparisonTests.stage

    @classmethod
    def setUpTestData(cls):
        product_fixtures.ProductComparisonTests.setUpTestData.__func__(cls)

    def test_small_malformed_and_json_null_stay_inconsistent(self):
        candidate = self.stage()
        self.client.force_login(self.viewer)
        for value in ({'bad': 'small-private'}, Value(None, output_field=JSONField())):
            ProductCandidate.objects.filter(pk=candidate.pk).update(source_fields=value)
            response = self.client.get(reverse('staff_products'))
            item = list(response.context['page'].object_list)[0]
            self.assertFalse(item.content_oversized)
            self.assertFalse(item.display_consistent)
            self.assertContains(response, 'مشخصات نامزد ناسازگار نمایش داده نمی‌شوند')
            self.assertNotContains(response, 'small-private')

    def test_bounded_queue_preserves_pagination_and_distinguishes_uninspected(self):
        candidates = [self.stage({**self.row, 'source_record_id': f'product-{i}'}) for i in range(22)]
        ProductCandidate.objects.filter(pk__in=[candidates[0].pk, candidates[-1].pk]).update(
            source_fields={'product-queue-canary': 'آ' * 1_000_000})
        from catalog.comparisons import valid_candidate
        def validate(item):
            self.assertNotIn(item.pk, (candidates[0].pk, candidates[-1].pk))
            return valid_candidate(item)
        self.client.force_login(self.viewer)
        with patch('catalog.staff_views.valid_candidate', side_effect=validate):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse('staff_products'))
            self.assertContains(response, 'نامزد بیش از حد بررسی است؛ مشخصات بررسی نشد')
            self.assertNotContains(response, 'product-queue-canary')
            self.assertNotContains(response, reverse('staff_product_detail', args=[candidates[-1].pk]))
            self.assertEqual(response.context['page'].paginator.count, 22)
            self.assertEqual(len(response.context['page'].object_list), 20)
            self.assertIn('no-store', response['Cache-Control'])
            sql = next(q['sql'] for q in queries if 'FROM "catalog_productcandidate"' in q['sql'] and 'LIMIT 20' in q['sql'])
            select = sql.rsplit(' FROM "catalog_productcandidate"', 1)[0].lower()
            self.assertIn('case', select)
            self.assertNotRegex(select, r'(?:^select |, )"catalog_productcandidate"\."source_fields"(?:,|$)')
            page2 = self.client.get(reverse('staff_products'), {'page': 2})
            self.assertContains(page2, 'نامزد بیش از حد بررسی است؛ مشخصات بررسی نشد')
            self.assertNotContains(page2, reverse('staff_product_detail', args=[candidates[0].pk]))
            self.assertEqual(len(page2.context['page'].object_list), 2)


class PriceQueueBoundedTests(TestCase):
    stage = price_fixtures.PriceComparisonTests.stage

    @classmethod
    def setUpTestData(cls):
        price_fixtures.PriceComparisonTests.setUpTestData.__func__(cls)

    def test_small_malformed_and_json_null_stay_inconsistent(self):
        candidate = self.stage()
        self.client.force_login(self.viewer)
        for value in ({'bad': 'small-private'}, Value(None, output_field=JSONField())):
            PriceCandidate.objects.filter(pk=candidate.pk).update(source_fields=value)
            response = self.client.get(reverse('staff_prices'))
            item = list(response.context['page'].object_list)[0]
            self.assertFalse(item.content_oversized)
            self.assertFalse(item.display_consistent)
            self.assertContains(response, 'مشخصات نامزد ناسازگار نمایش داده نمی‌شوند')
            self.assertNotContains(response, 'small-private')

    def test_bounded_queue_preserves_filters_stats_and_pagination(self):
        candidates = [self.stage({**self.row, 'source_record_id': f'price-{i}'}) for i in range(22)]
        PriceCandidate.objects.filter(pk__in=[candidates[0].pk, candidates[-1].pk]).update(
            source_fields={'price-queue-canary': 'آ' * 1_000_000})
        from pricing.comparisons import valid_candidate
        def validate(item):
            self.assertNotIn(item.pk, (candidates[0].pk, candidates[-1].pk))
            return valid_candidate(item)
        self.client.force_login(self.viewer)
        with patch('pricing.staff_views.valid_candidate', side_effect=validate):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse('staff_prices'), {'status': 'unmatched', 'review': 'pending'})
            self.assertContains(response, 'نامزد بیش از حد بررسی است؛ مشخصات بررسی نشد')
            self.assertNotContains(response, 'price-queue-canary')
            self.assertNotContains(response, reverse('staff_price_detail', args=[candidates[-1].pk]))
            self.assertEqual(response.context['page'].paginator.count, 22)
            self.assertEqual(response.context['total'], 22)
            self.assertEqual(len(response.context['page'].object_list), 20)
            self.assertIn('no-store', response['Cache-Control'])
            sql = next(q['sql'] for q in queries if 'FROM "pricing_pricecandidate"' in q['sql'] and 'LIMIT 20' in q['sql'])
            select = sql.rsplit(' FROM "pricing_pricecandidate"', 1)[0].lower()
            self.assertIn('case', select)
            self.assertNotRegex(select, r'(?:^select |, )"pricing_pricecandidate"\."source_fields"(?:,|$)')
            page2 = self.client.get(reverse('staff_prices'), {'status': 'unmatched', 'review': 'pending', 'page': 2})
            self.assertContains(page2, 'نامزد بیش از حد بررسی است؛ مشخصات بررسی نشد')
            self.assertNotContains(page2, reverse('staff_price_detail', args=[candidates[0].pk]))
            self.assertEqual(len(page2.context['page'].object_list), 2)
