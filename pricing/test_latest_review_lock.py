"""Selected price review-token races with synthetic PostgreSQL data."""
import io
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.transaction import TransactionManagementError
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from catalog.identity_test_utils import assert_blocked_by_current_transaction, publish_backend_pid
from catalog.models import ProductPresentation
from .models import PriceCandidate, PriceCandidateReview
from .importer import stage_csv
from .test_workflow import csv_bytes
from .reviews import ReviewConflict, product_fingerprint, record_preliminary_review

REASON = 'دلیل ساختگی برای بازبینی قیمت'


class PriceLatestReviewLockTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user('price-latest-author', is_staff=True)
        self.reviewer = User.objects.create_user('price-latest-reviewer', is_staff=True)
        perms = Permission.objects.filter(content_type__app_label='pricing',
            codename__in=['view_pricecandidate', 'add_pricecandidate', 'review_pricecandidate'])
        self.author.user_permissions.add(*perms)
        self.reviewer.user_permissions.add(*perms)
        row = dict(source_record_id='synthetic', irc='123456', manufacturer='شرکت فرضی', strength='5 mg',
                   dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
                   category='retail', unit='package', effective_date='', source_published_date='')
        stage_csv(io.BytesIO(csv_bytes([row])), 'منبع ساختگی', 'https://example.org/feed',
                  staged_by=self.author, commit=True, rights_attested=True)
        self.candidate = PriceCandidate.objects.get()
        self.latest = record_preliminary_review(actor=self.reviewer, candidate_id=self.candidate.pk, decision='defer',
            reason=REASON, expected_review=0, expected_product=0, expected_product_hash='')

    def review(self, pids=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '12s'")
                publish_backend_pid(cursor, pids)
            actor = get_user_model().objects.get(pk=self.reviewer.pk)
            return record_preliminary_review(actor=actor, candidate_id=self.candidate.pk, decision='defer', reason=REASON,
                                expected_review=self.latest.pk, expected_product=0, expected_product_hash='')
        finally:
            connection.close()

    def _assert_latest_lock(self, operation):
        create = PriceCandidateReview.objects.create
        paused, resume = Event(), Event()
        def pause_create(**kwargs):
            paused.set()
            if not resume.wait(8):
                raise TimeoutError('Synthetic review did not resume')
            return create(**kwargs)
        with patch('pricing.reviews.PriceCandidateReview.objects.create', side_effect=pause_create):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.review)
                try:
                    self.assertTrue(paused.wait(8))
                    with self.assertRaises(DatabaseError) as caught:
                        with transaction.atomic():
                            with connection.cursor() as cursor:
                                cursor.execute("SET LOCAL lock_timeout = '300ms'")
                            rows = PriceCandidateReview.objects.filter(pk=self.latest.pk)
                            if operation == 'update':
                                rows.update(reason='تغییر ساختگی')
                            else:
                                rows.delete()
                    cause = caught.exception.__cause__
                    self.assertEqual(getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None), '55P03')
                finally:
                    resume.set()
                event = future.result(timeout=10)
        self.assertNotEqual(event.pk, self.latest.pk)
        self.assertEqual(PriceCandidateReview.objects.filter(pk=self.latest.pk).update(reason=REASON), 1)

    def test_review_locks_latest_against_bulk_update(self):
        self._assert_latest_lock('update')

    def test_review_locks_latest_against_bulk_delete(self):
        self._assert_latest_lock('delete')

    def test_helper_is_atomic_scoped_and_uses_one_bounded_lock_query(self):
        from .reviews import _lock_latest_review
        with self.assertRaises(TransactionManagementError):
            _lock_latest_review(self.candidate)
        with transaction.atomic(), CaptureQueriesContext(connection) as queries:
            latest = _lock_latest_review(self.candidate)
        self.assertEqual(latest.pk, self.latest.pk)
        self.assertEqual(len(queries), 1)
        sql = queries[0]['sql'].upper()
        self.assertIn('FOR UPDATE', sql)
        self.assertIn('ORDER BY', sql)
        self.assertIn('LIMIT 1', sql)

    def test_prior_uncommitted_deletion_is_reread_as_conflict(self):
        from .reviews import _lock_latest_review
        waiting, pids = Event(), Queue()
        def signal(candidate):
            waiting.set()
            return _lock_latest_review(candidate)
        with patch('pricing.reviews._lock_latest_review', side_effect=signal):
            with ThreadPoolExecutor(max_workers=1) as pool:
                with transaction.atomic():
                    PriceCandidateReview.objects.filter(pk=self.latest.pk).delete()
                    future = pool.submit(self.review, pids)
                    self.assertTrue(waiting.wait(8))
                    assert_blocked_by_current_transaction(self, pids.get(timeout=5))
                    self.assertFalse(future.done())
                with self.assertRaises(ReviewConflict):
                    future.result(timeout=10)
        self.assertFalse(PriceCandidateReview.objects.filter(candidate=self.candidate).exists())

    def test_latest_row_is_locked_until_the_outer_transaction_ends(self):
        ready, resume = Event(), Event()
        def writer():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.reviewer.pk)
                with transaction.atomic():
                    event = record_preliminary_review(actor=actor, candidate_id=self.candidate.pk, decision='defer', reason=REASON,
                        expected_review=self.latest.pk, expected_product=0, expected_product_hash='')
                    ready.set()
                    if not resume.wait(8):
                        raise TimeoutError('Outer transaction did not resume')
                return event.pk
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(writer)
            try:
                self.assertTrue(ready.wait(8))
                with self.assertRaises(DatabaseError) as caught:
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL lock_timeout = '300ms'")
                        PriceCandidateReview.objects.filter(pk=self.latest.pk).update(reason='تغییر ساختگی')
                self.assertEqual(getattr(caught.exception.__cause__, 'sqlstate', None), '55P03')
            finally:
                resume.set()
            self.assertTrue(future.result(timeout=10))
        self.assertEqual(PriceCandidateReview.objects.filter(pk=self.latest.pk).update(reason=REASON), 1)

    def test_no_latest_review_and_previous_id_only_semantics(self):
        from .reviews import _lock_latest_review
        # Corruption of the old review is not checked by this particular writer;
        # its existing optimistic token intentionally uses only the previous ID.
        PriceCandidateReview.objects.filter(pk=self.latest.pk).update(reason='bad')
        event = record_preliminary_review(actor=self.reviewer, candidate_id=self.candidate.pk, decision='defer', reason=REASON,
                             expected_review=self.latest.pk, expected_product=0, expected_product_hash='')
        self.assertNotEqual(event.pk, self.latest.pk)
        PriceCandidateReview.objects.filter(candidate=self.candidate).delete()
        with transaction.atomic():
            self.assertIsNone(_lock_latest_review(self.candidate))
        event = record_preliminary_review(actor=self.reviewer, candidate_id=self.candidate.pk, decision='defer', reason=REASON,
                             expected_review=0, expected_product=0, expected_product_hash='')
        self.assertTrue(event.pk)

    def test_deferred_bypass_can_insert_later_review_after_writer_commit(self):
        ready, resume_writer, inserted, resume_inserter = Event(), Event(), Event(), Event()
        def writer():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.reviewer.pk)
                with transaction.atomic():
                    event = record_preliminary_review(actor=actor, candidate_id=self.candidate.pk, decision='defer', reason=REASON,
                        expected_review=self.latest.pk, expected_product=0, expected_product_hash='')
                    ready.set()
                    if not resume_writer.wait(8):
                        raise TimeoutError('Writer did not resume')
                return event.pk
            finally:
                connection.close()
        def bypass():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL statement_timeout = '12s'")
                        cursor.execute('SET CONSTRAINTS ALL DEFERRED')
                    event = PriceCandidateReview.objects.create(candidate_id=self.candidate.pk, reviewer_id=self.reviewer.pk,
                        decision='defer', reason=REASON, candidate_payload_sha256=self.latest.candidate_payload_sha256,
                        review_snapshot=self.latest.review_snapshot)
                    inserted.set()
                    if not resume_inserter.wait(8):
                        raise TimeoutError('Synthetic bypass did not resume')
                return event.pk
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(writer)
            second = None
            try:
                self.assertTrue(ready.wait(8))
                second = pool.submit(bypass)
                self.assertTrue(inserted.wait(8), 'Deferred insertion did not reach the expected boundary')
                resume_writer.set()
                writer_pk = first.result(timeout=10)
            finally:
                resume_writer.set()
                resume_inserter.set()
            bypass_pk = second.result(timeout=10)
        self.assertGreater(bypass_pk, writer_pk)
        self.assertEqual(PriceCandidateReview.objects.filter(candidate=self.candidate).order_by('-pk').first().pk, bypass_pk)

    def test_older_review_remains_unlocked(self):
        self.latest = record_preliminary_review(actor=self.reviewer, candidate_id=self.candidate.pk, decision='defer', reason=REASON,
                                   expected_review=self.latest.pk, expected_product=0, expected_product_hash='')
        older = PriceCandidateReview.objects.filter(candidate=self.candidate).order_by('pk').first()
        create = PriceCandidateReview.objects.create
        ready, resume = Event(), Event()
        def pause_create(**kwargs):
            ready.set()
            if not resume.wait(8):
                raise TimeoutError('Synthetic review did not resume')
            return create(**kwargs)
        with patch('pricing.reviews.PriceCandidateReview.objects.create', side_effect=pause_create):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.review)
                try:
                    self.assertTrue(ready.wait(8))
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL lock_timeout = '300ms'")
                        self.assertEqual(PriceCandidateReview.objects.filter(pk=older.pk).update(reason='تغییر ساختگی'), 1)
                finally:
                    resume.set()
                self.assertTrue(future.result(timeout=10))

    def test_prior_update_waits_but_same_id_does_not_validate_history(self):
        from .reviews import _lock_latest_review
        waiting, pids = Event(), Queue()
        def signal(candidate):
            waiting.set()
            return _lock_latest_review(candidate)
        with patch('pricing.reviews._lock_latest_review', side_effect=signal):
            with ThreadPoolExecutor(max_workers=1) as pool:
                with transaction.atomic():
                    PriceCandidateReview.objects.filter(pk=self.latest.pk).update(reason='تغییر قبلی ساختگی')
                    future = pool.submit(self.review, pids)
                    self.assertTrue(waiting.wait(8))
                    assert_blocked_by_current_transaction(self, pids.get(timeout=5))
                    self.assertFalse(future.done())
                event = future.result(timeout=10)
        self.assertNotEqual(event.pk, self.latest.pk)
        self.latest.refresh_from_db()
        self.assertEqual(self.latest.reason, 'تغییر قبلی ساختگی')

    def test_failed_write_rolls_back_and_releases_latest_review_lock(self):
        with patch('pricing.reviews.PriceCandidateReview.objects.create', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                record_preliminary_review(actor=self.reviewer, candidate_id=self.candidate.pk, decision='defer', reason=REASON,
                             expected_review=self.latest.pk, expected_product=0, expected_product_hash='')
        self.assertEqual(PriceCandidateReview.objects.filter(candidate=self.candidate).count(), 1)
        # Use a separate connection and a timeout to detect a leaked lock.
        def update():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '300ms'")
                    return PriceCandidateReview.objects.filter(pk=self.latest.pk).update(reason=REASON)
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(pool.submit(update).result(timeout=10), 1)

    def test_acceptance_holds_latest_review_and_selected_product_locks(self):
        product = ProductPresentation.objects.create(name_fa='فرآورده فرضی', manufacturer='شرکت فرضی',
            strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='123456',
            source_name='منبع ساختگی', source_url='https://example.org/product')
        ready, resume = Event(), Event()
        create = PriceCandidateReview.objects.create
        def pause_create(**kwargs):
            ready.set()
            if not resume.wait(8):
                raise TimeoutError('Synthetic acceptance did not resume')
            return create(**kwargs)
        def writer():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.reviewer.pk)
                return record_preliminary_review(actor=actor, candidate_id=self.candidate.pk,
                    decision='accept_suggestion', reason=REASON, expected_review=self.latest.pk,
                    expected_product=product.pk, expected_product_hash=product_fingerprint(product)).pk
            finally:
                connection.close()
        with patch('pricing.reviews.PriceCandidateReview.objects.create', side_effect=pause_create):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(writer)
                try:
                    self.assertTrue(ready.wait(8))
                    for model, pk, fields in [(PriceCandidateReview, self.latest.pk, {'reason': REASON}),
                                               (ProductPresentation, product.pk, {'strength': '10 mg'})]:
                        with self.subTest(model=model), self.assertRaises(DatabaseError) as caught:
                            with transaction.atomic():
                                with connection.cursor() as cursor:
                                    cursor.execute("SET LOCAL lock_timeout = '300ms'")
                                model.objects.filter(pk=pk).update(**fields)
                        cause = caught.exception.__cause__
                        self.assertEqual(getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None), '55P03')
                finally:
                    resume.set()
                self.assertEqual(PriceCandidateReview.objects.get(pk=future.result(timeout=10)).reviewed_product_id,
                                 product.pk)
