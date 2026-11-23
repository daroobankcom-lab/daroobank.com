"""Selected PostgreSQL interleavings for synthetic product-candidate triage."""
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, current_thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TransactionTestCase

from .intake import ReviewConflict, review_product, stage_products, valid_fields
from .models import ProductCandidate, ProductCandidateReview, ProductPresentation
from .test_intake import make_csv


class ProductReviewConcurrencyTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.stager = User.objects.create_user('product-race-stager', is_staff=True)
        self.reviewers = [User.objects.create_user(f'product-race-reviewer-{i}', is_staff=True) for i in range(2)]
        self.stager.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog',
                                           codename__in=['view_productcandidate', 'add_productcandidate', 'review_productcandidate']))
        for reviewer in self.reviewers:
            reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog',
                                            codename__in=['view_productcandidate', 'review_productcandidate']))
        self.row = dict(source_record_id='race-1', name_fa='فرآورده ساختگی', name_en='Synthetic',
            manufacturer='سازنده فرضی', strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        stage_products(io.BytesIO(make_csv([self.row])), 'منبع ساختگی', 'https://example.org/source',
                       actor=self.stager, commit=True, rights_attested=True)
        self.candidate = ProductCandidate.objects.get()

    def review(self, actor, **overrides):
        args = dict(candidate_id=self.candidate.pk, actor=actor, decision='further_review',
                    reason='این نتیجه صرفاً برای بررسی آزمایشی است.', expected_review=0,
                    expected_hash=self.candidate.payload_sha256)
        args.update(overrides)
        return review_product(**args)

    def worker(self, fn, lock_timeout='5s'):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('lock_timeout', %s, false)", [lock_timeout])
                cursor.execute("SET statement_timeout = '12s'")
            return fn()
        finally:
            connection.close()

    def test_two_reviewers_same_version_create_only_one_event(self):
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
        self.assertEqual(ProductCandidateReview.objects.count(), 1)
        self.assertEqual(ProductCandidateReview.objects.get().review_snapshot['source_fields'], self.row)
        self.assertFalse(ProductPresentation.objects.exists())

    def test_competing_candidate_update_blocks_review_then_fails_integrity_check(self):
        def attempt():
            return self.review(get_user_model().objects.get(pk=self.reviewers[0].pk))
        with transaction.atomic():
            ProductCandidate.objects.select_for_update().get(pk=self.candidate.pk)
            ProductCandidate.objects.filter(pk=self.candidate.pk).update(source_fields={'bad': 'synthetic alteration'})
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(ReviewConflict) as caught:
                    pool.submit(self.worker, attempt, '300ms').result(timeout=10)
                driver = caught.exception.__cause__.__cause__
                self.assertEqual(getattr(driver, 'sqlstate', None) or getattr(driver, 'pgcode', None), '55P03')
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaises(ReviewConflict):
                pool.submit(self.worker, attempt).result(timeout=10)
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_review_holds_candidate_lock_until_event_commits(self):
        ready, resume = Event(), Event()
        review_thread = []
        def paused_validation(fields):
            result = valid_fields(fields)
            if review_thread and current_thread() is review_thread[0]:
                ready.set()
                if not resume.wait(8):
                    raise TimeoutError('Test did not resume synthetic review')
            return result
        def attempt():
            review_thread.append(current_thread())
            return self.review(get_user_model().objects.get(pk=self.reviewers[0].pk)).pk
        def change_rights():
            ProductCandidate.objects.filter(pk=self.candidate.pk).update(source_rights_attested=False)
        with patch('catalog.intake.valid_fields', side_effect=paused_validation):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.worker, attempt)
                try:
                    self.assertTrue(ready.wait(8), 'Review did not reach validation under lock')
                    with self.assertRaises(OperationalError):
                        pool.submit(self.worker, change_rights, '300ms').result(timeout=10)
                finally:
                    resume.set()
                event_id = first.result(timeout=10)
        event = ProductCandidateReview.objects.get(pk=event_id)
        self.assertTrue(event.review_snapshot['source_rights_attested'])
        # Subsequent bypass writes remain possible; this is not immutable audit.
        ProductCandidate.objects.filter(pk=self.candidate.pk).update(source_rights_attested=False)
        self.assertTrue(ProductCandidateReview.objects.get(pk=event_id).review_snapshot['source_rights_attested'])
        with self.assertRaises(ReviewConflict):
            self.review(self.reviewers[1], expected_review=event_id)
        self.assertEqual(ProductCandidateReview.objects.count(), 1)

    def test_stager_cannot_review_own_candidate_even_with_permissions(self):
        with self.assertRaises(PermissionDenied): self.review(self.stager)
        self.assertFalse(ProductCandidateReview.objects.exists())
