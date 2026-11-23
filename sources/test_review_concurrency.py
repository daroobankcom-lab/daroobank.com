"""Selected PostgreSQL races for synthetic source-claim triage."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, current_thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TransactionTestCase

from .models import SourceClaim, SourceClaimReview
from .services import ReviewConflict, record_claim, review_claim, valid_claim


class SourceReviewConcurrencyTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user('race-source-author', is_staff=True)
        self.reviewers = [User.objects.create_user(f'race-source-reviewer-{i}', is_staff=True) for i in range(2)]
        perms = Permission.objects.filter(content_type__app_label='sources',
                                          codename__in=['view_sourceclaim', 'add_sourceclaim', 'review_sourceclaim'])
        for user in [self.author, *self.reviewers]:
            user.user_permissions.add(*perms)
        self.claim, _ = record_claim(actor=self.author, data=dict(source_name='منبع ساختگی',
            source_url='https://example.org/source', owner='مالک فرضی', evidence_url='https://example.org/evidence',
            evidence_note='مدرک ساختگی', claims_collection=True, claims_storage=True, claims_publication=False,
            starts_on=None, expires_on=None))

    def review(self, actor, **changes):
        args = dict(actor=actor, claim_id=self.claim.pk, decision='defer',
                    reason='این ادعای ساختگی به بررسی بیشتر نیاز دارد.', expected_review=0,
                    expected_hash=self.claim.payload_sha256)
        args.update(changes)
        return review_claim(**args)

    def worker(self, operation, lock_timeout='5s'):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('lock_timeout', %s, false)", [lock_timeout])
                cursor.execute("SET statement_timeout = '12s'")
            return operation()
        finally:
            connection.close()

    def test_two_reviewers_of_same_version_record_one_and_one_conflicts(self):
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
            self.assertCountEqual([future.result(timeout=15) for future in futures], ['created', 'conflict'])
        event = SourceClaimReview.objects.get()
        self.assertEqual(event.review_snapshot['owner'], self.claim.owner)
        self.assertEqual(event.claim_payload_sha256, self.claim.payload_sha256)

    def test_competing_claim_write_waits_and_changed_claim_is_rejected(self):
        def attempt():
            return self.review(get_user_model().objects.get(pk=self.reviewers[0].pk))
        with transaction.atomic():
            SourceClaim.objects.select_for_update().get(pk=self.claim.pk)
            SourceClaim.objects.filter(pk=self.claim.pk).update(owner='مالک ساختگی تغییر یافته')
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(OperationalError):
                    pool.submit(self.worker, attempt, '300ms').result(timeout=10)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaises(ReviewConflict):
                pool.submit(self.worker, attempt).result(timeout=10)
        self.assertFalse(SourceClaimReview.objects.exists())

    def test_review_lock_blocks_write_but_later_bypass_still_changes_claim(self):
        ready, resume = Event(), Event()
        review_thread = []
        def pause_validation(claim):
            result = valid_claim(claim)
            if review_thread and current_thread() is review_thread[0]:
                ready.set()
                if not resume.wait(8):
                    raise TimeoutError('Synthetic review did not resume')
            return result
        def attempt():
            review_thread.append(current_thread())
            return self.review(get_user_model().objects.get(pk=self.reviewers[0].pk)).pk
        def change():
            SourceClaim.objects.filter(pk=self.claim.pk).update(owner='مالک تغییر یافته با bypass')
        with patch('sources.services.valid_claim', side_effect=pause_validation):
            with ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(self.worker, attempt)
                try:
                    self.assertTrue(ready.wait(8), 'Review did not reach claim validation')
                    with self.assertRaises(OperationalError):
                        pool.submit(self.worker, change, '300ms').result(timeout=10)
                finally:
                    resume.set()
                event = SourceClaimReview.objects.get(pk=future.result(timeout=10))
        self.assertEqual(event.review_snapshot['owner'], 'مالک فرضی')
        change()
        self.assertFalse(valid_claim(SourceClaim.objects.get(pk=self.claim.pk)))
        self.assertEqual(SourceClaimReview.objects.get(pk=event.pk).review_snapshot['owner'], 'مالک فرضی')
        with self.assertRaises(ReviewConflict):
            self.review(self.reviewers[1], expected_review=event.pk)

    def test_failed_review_write_rolls_back_and_allows_subsequent_review(self):
        with self.assertRaises(PermissionDenied):
            self.review(self.author)
        with patch('sources.services.SourceClaimReview.objects.create', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                self.review(self.reviewers[0])
        self.assertFalse(SourceClaimReview.objects.exists())
        self.review(self.reviewers[1])
        self.assertEqual(SourceClaimReview.objects.count(), 1)
