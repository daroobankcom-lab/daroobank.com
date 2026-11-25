"""Synthetic bounded candidate JSON under the existing review-writer row lock."""
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog import test_comparisons as product_fixtures
from catalog.intake import ReviewConflict as ProductConflict, review_product
from catalog.models import ProductCandidate, ProductCandidateReview
from pricing import test_comparisons as price_fixtures
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import ReviewConflict as PriceConflict, record_preliminary_review


def assert_bounded_lock(test, queries, table):
    sql = next(q['sql'] for q in queries if f'FROM "{table}"' in q['sql'] and 'FOR UPDATE' in q['sql'])
    selection = sql.split(' FROM ', 1)[0].lower()
    test.assertIn('case', selection)
    test.assertNotRegex(selection, rf'(?:^select |, )"{table}"\."source_fields"(?:,|$)')


class ProductLockedCandidateBoundsTests(TestCase):
    stage = product_fixtures.ProductComparisonTests.stage

    @classmethod
    def setUpTestData(cls):
        product_fixtures.ProductComparisonTests.setUpTestData.__func__(cls)

    def test_oversized_is_rejected_before_validation_under_lock(self):
        candidate = self.stage()
        ProductCandidate.objects.filter(pk=candidate.pk).update(source_fields={'writer-canary': 'آ' * 1_000_000})
        args = dict(candidate_id=candidate.pk, actor=self.reviewer, decision='defer',
                    reason='توضیح ساختگی برای بررسی بیشتر', expected_review=0, expected_hash=candidate.payload_sha256)
        self.reviewer.has_perm('catalog.review_productcandidate')
        with patch('catalog.intake.valid_fields', side_effect=AssertionError('must not validate oversized data')):
            with CaptureQueriesContext(connection) as queries:
                with self.assertRaises(ProductConflict):
                    review_product(**args)
        assert_bounded_lock(self, queries, 'catalog_productcandidate')
        self.assertFalse(ProductCandidateReview.objects.exists())
        self.client.force_login(self.reviewer)
        with CaptureQueriesContext(connection) as requests:
            response = self.client.post(reverse('staff_product_review', args=[candidate.pk]), {
                'decision': 'defer', 'reason': args['reason'], 'expected_review': 0, 'expected_hash': args['expected_hash']})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'نامزد بیش از حد بررسی است؛ سازگاری بررسی نشد', status_code=409)
        self.assertNotContains(response, 'writer-canary', status_code=409)
        assert_bounded_lock(self, requests, 'catalog_productcandidate')
        self.assertEqual(len(ProductCandidate.objects.get(pk=candidate.pk).source_fields['writer-canary']), 1_000_000)
        # Existing self-review permission denial must still take precedence.
        self.stager.user_permissions.add(*self.reviewer.user_permissions.all())
        with self.assertRaises(PermissionDenied):
            review_product(**{**args, 'actor': self.stager})


class PriceLockedCandidateBoundsTests(TestCase):
    stage = price_fixtures.PriceComparisonTests.stage

    @classmethod
    def setUpTestData(cls):
        price_fixtures.PriceComparisonTests.setUpTestData.__func__(cls)

    def test_oversized_is_rejected_before_validation_under_lock(self):
        candidate = self.stage()
        PriceCandidate.objects.filter(pk=candidate.pk).update(source_fields={'writer-canary': 'آ' * 1_000_000})
        args = dict(candidate_id=candidate.pk, actor=self.reviewer, decision='defer',
                    reason='توضیح ساختگی برای بررسی بیشتر', expected_review=0,
                    expected_product=0, expected_product_hash='')
        self.reviewer.has_perm('pricing.review_pricecandidate')
        with patch('pricing.reviews.ensure_candidate_integrity', side_effect=AssertionError('must not validate oversized data')):
            with CaptureQueriesContext(connection) as queries:
                with self.assertRaises(PriceConflict):
                    record_preliminary_review(**args)
        assert_bounded_lock(self, queries, 'pricing_pricecandidate')
        self.assertFalse(PriceCandidateReview.objects.exists())
        self.client.force_login(self.reviewer)
        with CaptureQueriesContext(connection) as requests:
            response = self.client.post(reverse('staff_price_review', args=[candidate.pk]), {
                'decision': 'defer', 'reason': args['reason'], 'expected_review': 0, 'expected_product': 0, 'expected_product_hash': ''})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'نامزد بیش از حد بررسی است؛ سازگاری بررسی نشد', status_code=409)
        self.assertNotContains(response, 'writer-canary', status_code=409)
        assert_bounded_lock(self, requests, 'pricing_pricecandidate')
        self.assertEqual(len(PriceCandidate.objects.get(pk=candidate.pk).source_fields['writer-canary']), 1_000_000)
        self.stager.user_permissions.add(*self.reviewer.user_permissions.all())
        with self.assertRaises(PermissionDenied):
            record_preliminary_review(**{**args, 'actor': self.stager})


class CandidateOversizeLockRaceTests(TransactionTestCase):
    """A writer waiting on a candidate observes the committed oversized row."""
    def test_waiting_review_rechecks_committed_candidate_for_both_domains(self):
        import io
        from concurrent.futures import ThreadPoolExecutor
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Permission
        from django.db import close_old_connections, transaction
        from catalog.intake import stage_products
        from catalog.test_intake import make_csv
        from pricing.importer import stage_csv
        from pricing.test_workflow import csv_bytes

        user = get_user_model()
        stager = user.objects.create_user('bound-race-stager', is_staff=True)
        reviewer = user.objects.create_user('bound-race-reviewer', is_staff=True)
        for app, entity in [('catalog', 'productcandidate'), ('pricing', 'pricecandidate')]:
            permissions = Permission.objects.filter(content_type__app_label=app)
            stager.user_permissions.add(*permissions.filter(codename__in=[f'view_{entity}', f'add_{entity}']))
            reviewer.user_permissions.add(*permissions.filter(codename__in=[f'view_{entity}', f'review_{entity}']))
        product = dict(source_record_id='race-product', name_fa='نام ساختگی', name_en='', manufacturer='سازنده',
                       strength='1 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        price = dict(source_record_id='race-price', irc='001', manufacturer='سازنده', strength='1 mg',
                     dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
                     category='retail', unit='package', effective_date='', source_published_date='')
        stage_products(io.BytesIO(make_csv([product])), 'منبع ساختگی', 'https://example.org/product',
                       actor=stager, commit=True, rights_attested=True)
        stage_csv(io.BytesIO(csv_bytes([price])), 'منبع ساختگی', 'https://example.org/price',
                  staged_by=stager, commit=True, rights_attested=True)
        product_obj, price_obj = ProductCandidate.objects.get(), PriceCandidate.objects.get()
        cases = [
            (product_obj, ProductCandidate, ProductConflict, ProductCandidateReview, review_product,
             dict(candidate_id=product_obj.pk, decision='defer', reason='توضیح ساختگی برای بررسی بیشتر',
                  expected_review=0, expected_hash=product_obj.payload_sha256)),
            (price_obj, PriceCandidate, PriceConflict, PriceCandidateReview, record_preliminary_review,
             dict(candidate_id=price_obj.pk, decision='defer', reason='توضیح ساختگی برای بررسی بیشتر',
                  expected_review=0, expected_product=0, expected_product_hash='')),
        ]
        for obj, model, conflict, review_model, service, args in cases:
            with self.subTest(model=model.__name__):
                def worker():
                    close_old_connections()
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute("SET lock_timeout = '300ms'")
                            cursor.execute("SET statement_timeout = '5s'")
                        actor = user.objects.get(pk=reviewer.pk)
                        try:
                            service(actor=actor, **args)
                        except conflict as exc:
                            return exc
                        return None
                    finally:
                        connection.close()
                with transaction.atomic():
                    model.objects.select_for_update().get(pk=obj.pk)
                    model.objects.filter(pk=obj.pk).update(source_fields={'race-canary': 'آ' * 100_000})
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        locked = pool.submit(worker).result(timeout=10)
                    driver = locked.__cause__.__cause__
                    self.assertEqual(getattr(driver, 'sqlstate', None) or getattr(driver, 'pgcode', None), '55P03')
                with ThreadPoolExecutor(max_workers=1) as pool:
                    rejected = pool.submit(worker).result(timeout=10)
                self.assertIsInstance(rejected, conflict)
                self.assertIn('بیش از حد بررسی', str(rejected))
                self.assertFalse(review_model.objects.exists())
