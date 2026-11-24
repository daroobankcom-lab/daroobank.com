"""Selected matching paths must not fetch unused synthetic search projections."""
import io

from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog import test_comparisons as product_fixtures
from catalog.comparisons import product_comparison_context
from catalog.models import ProductPresentation
from pricing import test_workflow as price_fixtures
from pricing.importer import MAX_MATCH_CANDIDATES, stage_csv, suggest_product
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import product_fingerprint, record_preliminary_review


def assert_no_projection(test, queries, *, locked=False):
    sqls = [q['sql'] for q in queries if q['sql'].lstrip().upper().startswith('SELECT')
            and 'FROM "catalog_productpresentation"' in q['sql']]
    test.assertTrue(sqls)
    for sql in sqls:
        select = sql.split(' FROM ', 1)[0].lower()
        test.assertNotIn('"search_text"', select)
    if locked:
        test.assertTrue(any('FOR UPDATE' in sql for sql in sqls))


@override_settings(STAFF_PORTAL_ENABLED=True)
class PriceMatchingProjectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        price_fixtures.PriceWorkflowTests.setUpTestData.__func__(cls)
        ProductPresentation.objects.filter(pk=cls.product.pk).update(
            search_text='private-search-canary' + 'آ' * 1_000_000)

    def test_suggest_stage_detail_and_locked_review_do_not_transfer_projection(self):
        with CaptureQueriesContext(connection) as queries:
            status, match = suggest_product(self.row)
            matched_hash = product_fingerprint(match)
        self.assertEqual(status, 'suggested')
        self.assertEqual(match.pk, self.product.pk)
        self.assertEqual(matched_hash, product_fingerprint(self.product))
        self.assertIn('search_text', match.get_deferred_fields())
        assert_no_projection(self, queries)
        with CaptureQueriesContext(connection) as queries:
            counts = stage_csv(io.BytesIO(price_fixtures.csv_bytes([self.row])), 'منبع ساختگی',
                'https://example.org/feed', commit=True, rights_attested=True, staged_by=self.stager)
        self.assertEqual((counts['created'], counts['suggested']), (1, 1))
        assert_no_projection(self, queries)
        candidate = PriceCandidate.objects.get()
        self.client.force_login(self.reviewer)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('staff_price_detail', args=[candidate.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'فرآورده ساختگی')
        self.assertNotContains(response, 'private-search-canary')
        self.assertIn('no-store', response['Cache-Control'])
        assert_no_projection(self, queries)
        self.reviewer.has_perm('pricing.review_pricecandidate')
        with CaptureQueriesContext(connection) as queries:
            review = record_preliminary_review(actor=self.reviewer, candidate_id=candidate.pk,
                decision='accept_suggestion', reason='توضیح ساختگی برای بررسی بیشتر', expected_review=0,
                expected_product=self.product.pk, expected_product_hash=matched_hash)
        assert_no_projection(self, queries, locked=True)
        self.assertEqual(review.reviewed_product_id, self.product.pk)
        self.assertEqual(review.review_snapshot['product']['id'], self.product.pk)
        self.assertEqual(PriceCandidateReview.objects.count(), 1)

    def test_overflow_sentinel_keeps_ambiguous_result_and_is_not_transferred(self):
        copies = [ProductPresentation(name_fa=f'نمونه {i}', manufacturer=self.product.manufacturer,
            strength=self.product.strength, dosage_form=self.product.dosage_form,
            package_description=self.product.package_description, irc=self.product.irc,
            irc_normalized=self.product.irc_normalized, source_name='نمونه',
            source_url='https://example.org/product', search_text='sentinel-canary' + 'آ' * 100_000)
            for i in range(MAX_MATCH_CANDIDATES)]
        ProductPresentation.objects.bulk_create(copies)
        with transaction.atomic(), CaptureQueriesContext(connection) as queries:
            result = suggest_product(self.row, lock=True)
        self.assertEqual(result, ('ambiguous', None))
        assert_no_projection(self, queries, locked=True)


@override_settings(STAFF_PORTAL_ENABLED=True)
class ProductComparisonProjectionTests(TestCase):
    stage = product_fixtures.ProductComparisonTests.stage
    product = product_fixtures.ProductComparisonTests.product

    @classmethod
    def setUpTestData(cls):
        product_fixtures.ProductComparisonTests.setUpTestData.__func__(cls)

    def test_product_clues_and_sentinel_do_not_transfer_projection(self):
        candidate = self.stage()
        products = [self.product(name=f'فرآورده ساختگی {i}') for i in range(11)]
        ProductPresentation.objects.filter(pk__in=[p.pk for p in products]).update(
            search_text='comparison-projection-canary' + 'آ' * 100_000)
        with CaptureQueriesContext(connection) as queries:
            context = product_comparison_context(candidate)
        self.assertTrue(context['public_matches_limited'])
        self.assertEqual(len(context['public_matches']), 10)
        self.assertTrue(all('search_text' in row['product'].get_deferred_fields() for row in context['public_matches']))
        assert_no_projection(self, queries)
        self.client.force_login(self.viewer)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('staff_product_detail', args=[candidate.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'فرآورده ساختگی 0')
        self.assertNotContains(response, 'comparison-projection-canary')
        self.assertIn('no-store', response['Cache-Control'])
        assert_no_projection(self, queries)
