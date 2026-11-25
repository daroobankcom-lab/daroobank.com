"""PostgreSQL interleavings for preliminary price matching, using synthetic data only."""
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TransactionTestCase

from catalog.models import ProductPresentation
from pricing.importer import stage_csv, suggest_product
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import ReviewConflict, product_fingerprint, record_preliminary_review
from pricing.test_workflow import csv_bytes


class PriceConcurrencyTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.stager = User.objects.create_user('price-race-stager', is_staff=True)
        self.reviewers = [User.objects.create_user(f'price-race-reviewer-{i}', is_staff=True) for i in range(2)]
        self.stager.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
                                           codename__in=['view_pricecandidate', 'add_pricecandidate']))
        for reviewer in self.reviewers:
            reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
                                            codename__in=['view_pricecandidate', 'review_pricecandidate']))
        self.product_data = dict(name_fa='فرآورده ساختگی', manufacturer='شرکت فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', irc='123456',
            source_name='منبع ساختگی', source_url='https://example.org/product')
        self.product = ProductPresentation.objects.create(**self.product_data)
        self.row = dict(source_record_id='one', irc='123456', manufacturer='شرکت فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
            unit='package', effective_date='', source_published_date='')
        stage_csv(io.BytesIO(csv_bytes([self.row])), 'منبع ساختگی', 'https://example.org/feed',
                  staged_by=self.stager, commit=True, rights_attested=True)
        self.candidate = PriceCandidate.objects.get()
        self.hash = product_fingerprint(self.product)

    def review(self, actor, **overrides):
        args = dict(candidate_id=self.candidate.pk, actor=actor, decision='accept_suggestion',
                    reason='بررسی صرفاً آزمایشی است.', expected_review=0,
                    expected_product=self.product.pk, expected_product_hash=self.hash)
        args.update(overrides)
        return record_preliminary_review(**args)

    def worker(self, fn, *, lock_timeout='5s'):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('lock_timeout', %s, false)", [lock_timeout])
                cursor.execute("SET statement_timeout = '12s'")
            return fn()
        finally:
            connection.close()

    def test_same_expected_review_serializes_and_rejects_stale_reviewer(self):
        barrier = Barrier(2, timeout=8)
        def attempt(i):
            actor = get_user_model().objects.get(pk=self.reviewers[i].pk)
            barrier.wait()
            try:
                self.review(actor)
                return 'created'
            except ReviewConflict:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.worker, lambda i=i: attempt(i)) for i in range(2)]
            self.assertCountEqual([f.result(timeout=15) for f in futures], ['created', 'conflict'])
        self.assertEqual(PriceCandidateReview.objects.count(), 1)
        self.assertEqual(PriceCandidateReview.objects.get().reviewed_product_id, self.product.pk)

    def test_existing_product_lock_blocks_acceptance_and_changed_product_fails(self):
        def attempt():
            actor = get_user_model().objects.get(pk=self.reviewers[0].pk)
            return self.review(actor)
        with transaction.atomic():
            ProductPresentation.objects.select_for_update().get(pk=self.product.pk)
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(ReviewConflict) as caught:
                    pool.submit(self.worker, attempt, lock_timeout='300ms').result(timeout=10)
                driver = caught.exception.__cause__.__cause__
                self.assertEqual(getattr(driver, 'sqlstate', None) or getattr(driver, 'pgcode', None), '55P03')
            ProductPresentation.objects.filter(pk=self.product.pk).update(strength='different')
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaises(ReviewConflict):
                pool.submit(self.worker, attempt).result(timeout=10)
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_new_duplicate_can_commit_after_locked_query_before_review_commits(self):
        matched, resume = Event(), Event()
        def paused_match(row, *, lock=False):
            result = suggest_product(row, lock=lock)
            self.assertTrue(lock)
            matched.set()
            if not resume.wait(8):
                raise TimeoutError('Test did not resume review')
            return result
        def attempt():
            actor = get_user_model().objects.get(pk=self.reviewers[0].pk)
            return self.review(actor).pk
        with patch('pricing.reviews.suggest_product', side_effect=paused_match):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.worker, attempt)
                try:
                    self.assertTrue(matched.wait(8), 'Review did not finish matching')
                    ProductPresentation.objects.create(**self.product_data)
                finally:
                    resume.set()
                review_pk = future.result(timeout=12)
        self.assertEqual(PriceCandidateReview.objects.get(pk=review_pk).reviewed_product_id, self.product.pk)
        self.assertEqual(suggest_product(self.row), ('ambiguous', None))
        # The earlier acceptance is an observation, not a uniqueness guarantee.

    def test_staging_reuses_old_irc_group_across_committed_concurrent_change(self):
        staged, resume = Event(), Event()
        rows = [{**self.row, 'source_record_id': 'first'},
                {**self.row, 'source_record_id': 'second', 'strength': '10 mg'}]
        def on_staged(candidate_id, source_id, payload, created, status):
            if source_id == 'first':
                staged.set()
                if not resume.wait(8):
                    raise TimeoutError('Test did not resume staging')
        def attempt():
            actor = get_user_model().objects.get(pk=self.stager.pk)
            return stage_csv(io.BytesIO(csv_bytes(rows)), 'منبع ساختگی', 'https://example.org/second-feed',
                             staged_by=actor, commit=True, rights_attested=True, on_staged=on_staged)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.worker, attempt)
            try:
                self.assertTrue(staged.wait(8), 'Stage did not reach first row')
                ProductPresentation.objects.filter(pk=self.product.pk).update(strength='10 mg')
            finally:
                resume.set()
            counts = future.result(timeout=12)
        self.assertEqual((counts['suggested'], counts['unmatched']), (1, 1))
        second = PriceCandidate.objects.get(source_url='https://example.org/second-feed', source_record_id='second')
        self.assertEqual(second.match_status, 'unmatched')
        self.assertEqual(suggest_product(second.source_fields)[0], 'suggested')
        first = PriceCandidate.objects.get(source_url='https://example.org/second-feed', source_record_id='first')
        self.assertEqual(first.match_status, 'suggested')
        with self.assertRaises(ReviewConflict):
            self.review(self.reviewers[0], candidate_id=first.pk)
        self.assertFalse(PriceCandidateReview.objects.exists())
