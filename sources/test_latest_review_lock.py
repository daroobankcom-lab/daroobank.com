"""Selected source review-token races with synthetic PostgreSQL data."""
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

from catalog.identity_test_utils import assert_blocked_by_backend, assert_blocked_by_current_transaction, publish_backend_pid
from .models import SourceClaim, SourceClaimReview
from .services import ReviewConflict, record_claim, review_claim

REASON = 'دلیل ساختگی برای بازبینی منبع'


class SourceLatestReviewLockTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user('source-latest-author', is_staff=True)
        self.reviewer = User.objects.create_user('source-latest-reviewer', is_staff=True)
        perms = Permission.objects.filter(content_type__app_label='sources',
            codename__in=['view_sourceclaim', 'add_sourceclaim', 'review_sourceclaim'])
        self.author.user_permissions.add(*perms)
        self.reviewer.user_permissions.add(*perms)
        self.claim, _ = record_claim(actor=self.author, data=dict(source_name='منبع ساختگی',
            source_url='https://example.org/source', owner='مالک فرضی', evidence_url='https://example.org/evidence',
            evidence_note='', claims_collection=True, claims_storage=False, claims_publication=False,
            starts_on=None, expires_on=None))
        self.latest = review_claim(actor=self.reviewer, claim_id=self.claim.pk, decision='defer', reason=REASON,
                                   expected_review=0, expected_hash=self.claim.payload_sha256)

    def review(self, pids=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '12s'")
                publish_backend_pid(cursor, pids)
            actor = get_user_model().objects.get(pk=self.reviewer.pk)
            return review_claim(actor=actor, claim_id=self.claim.pk, decision='defer', reason=REASON,
                                expected_review=self.latest.pk, expected_hash=self.claim.payload_sha256)
        finally:
            connection.close()

    def _assert_latest_lock(self, operation):
        create = SourceClaimReview.objects.create
        paused, resume = Event(), Event()
        def pause_create(**kwargs):
            paused.set()
            if not resume.wait(8):
                raise TimeoutError('Synthetic review did not resume')
            return create(**kwargs)
        with patch('sources.services.SourceClaimReview.objects.create', side_effect=pause_create):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.review)
                try:
                    self.assertTrue(paused.wait(8))
                    with self.assertRaises(DatabaseError) as caught:
                        with transaction.atomic():
                            with connection.cursor() as cursor:
                                cursor.execute("SET LOCAL lock_timeout = '300ms'")
                            rows = SourceClaimReview.objects.filter(pk=self.latest.pk)
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
        self.assertEqual(SourceClaimReview.objects.filter(pk=self.latest.pk).update(reason=REASON), 1)

    def test_review_locks_latest_against_bulk_update(self):
        self._assert_latest_lock('update')

    def test_review_locks_latest_against_bulk_delete(self):
        self._assert_latest_lock('delete')

    def test_helper_is_atomic_scoped_and_uses_one_bounded_lock_query(self):
        from .services import _lock_latest_review
        with self.assertRaises(TransactionManagementError):
            _lock_latest_review(self.claim)
        with transaction.atomic(), CaptureQueriesContext(connection) as queries:
            latest = _lock_latest_review(self.claim)
        self.assertEqual(latest.pk, self.latest.pk)
        self.assertEqual(len(queries), 1)
        sql = queries[0]['sql'].upper()
        self.assertIn('FOR UPDATE', sql)
        self.assertIn('ORDER BY', sql)
        self.assertIn('LIMIT 1', sql)

    def test_prior_uncommitted_deletion_is_reread_as_conflict(self):
        from .services import _lock_latest_review
        waiting, pids = Event(), Queue()
        def signal(claim):
            waiting.set()
            return _lock_latest_review(claim)
        with patch('sources.services._lock_latest_review', side_effect=signal):
            with ThreadPoolExecutor(max_workers=1) as pool:
                with transaction.atomic():
                    SourceClaimReview.objects.filter(pk=self.latest.pk).delete()
                    future = pool.submit(self.review, pids)
                    self.assertTrue(waiting.wait(8))
                    assert_blocked_by_current_transaction(self, pids.get(timeout=5))
                    self.assertFalse(future.done())
                with self.assertRaises(ReviewConflict):
                    future.result(timeout=10)
        self.assertFalse(SourceClaimReview.objects.filter(claim=self.claim).exists())

    def test_latest_row_is_locked_until_the_outer_transaction_ends(self):
        ready, resume = Event(), Event()
        def writer():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.reviewer.pk)
                with transaction.atomic():
                    event = review_claim(actor=actor, claim_id=self.claim.pk, decision='defer', reason=REASON,
                        expected_review=self.latest.pk, expected_hash=self.claim.payload_sha256)
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
                        SourceClaimReview.objects.filter(pk=self.latest.pk).update(reason='تغییر ساختگی')
                self.assertEqual(getattr(caught.exception.__cause__, 'sqlstate', None), '55P03')
            finally:
                resume.set()
            self.assertTrue(future.result(timeout=10))
        self.assertEqual(SourceClaimReview.objects.filter(pk=self.latest.pk).update(reason=REASON), 1)

    def test_no_latest_review_and_previous_id_only_semantics(self):
        from .services import _lock_latest_review
        # Corruption of the old review is not checked by this particular writer;
        # its existing optimistic token intentionally uses only the previous ID.
        SourceClaimReview.objects.filter(pk=self.latest.pk).update(reason='bad')
        event = review_claim(actor=self.reviewer, claim_id=self.claim.pk, decision='defer', reason=REASON,
                             expected_review=self.latest.pk, expected_hash=self.claim.payload_sha256)
        self.assertNotEqual(event.pk, self.latest.pk)
        SourceClaimReview.objects.filter(claim=self.claim).delete()
        with transaction.atomic():
            self.assertIsNone(_lock_latest_review(self.claim))
        event = review_claim(actor=self.reviewer, claim_id=self.claim.pk, decision='defer', reason=REASON,
                             expected_review=0, expected_hash=self.claim.payload_sha256)
        self.assertTrue(event.pk)

    def test_deferred_bypass_can_insert_later_review_after_writer_commit(self):
        ready, resume_writer, inserted, resume_inserter = Event(), Event(), Event(), Event()
        def writer():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.reviewer.pk)
                with transaction.atomic():
                    event = review_claim(actor=actor, claim_id=self.claim.pk, decision='defer', reason=REASON,
                        expected_review=self.latest.pk, expected_hash=self.claim.payload_sha256)
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
                    event = SourceClaimReview.objects.create(claim_id=self.claim.pk, reviewer_id=self.reviewer.pk,
                        decision='defer', reason=REASON, claim_payload_sha256=self.latest.claim_payload_sha256,
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
        self.assertEqual(SourceClaimReview.objects.filter(claim=self.claim).order_by('-pk').first().pk, bypass_pk)

    def test_older_review_remains_unlocked(self):
        self.latest = review_claim(actor=self.reviewer, claim_id=self.claim.pk, decision='defer', reason=REASON,
                                   expected_review=self.latest.pk, expected_hash=self.claim.payload_sha256)
        older = SourceClaimReview.objects.filter(claim=self.claim).order_by('pk').first()
        create = SourceClaimReview.objects.create
        ready, resume = Event(), Event()
        def pause_create(**kwargs):
            ready.set()
            if not resume.wait(8):
                raise TimeoutError('Synthetic review did not resume')
            return create(**kwargs)
        with patch('sources.services.SourceClaimReview.objects.create', side_effect=pause_create):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.review)
                try:
                    self.assertTrue(ready.wait(8))
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL lock_timeout = '300ms'")
                        self.assertEqual(SourceClaimReview.objects.filter(pk=older.pk).update(reason='تغییر ساختگی'), 1)
                finally:
                    resume.set()
                self.assertTrue(future.result(timeout=10))

    def test_prior_update_waits_but_same_id_does_not_validate_history(self):
        from .services import _lock_latest_review
        waiting, pids = Event(), Queue()
        def signal(claim):
            waiting.set()
            return _lock_latest_review(claim)
        with patch('sources.services._lock_latest_review', side_effect=signal):
            with ThreadPoolExecutor(max_workers=1) as pool:
                with transaction.atomic():
                    SourceClaimReview.objects.filter(pk=self.latest.pk).update(reason='تغییر قبلی ساختگی')
                    future = pool.submit(self.review, pids)
                    self.assertTrue(waiting.wait(8))
                    assert_blocked_by_current_transaction(self, pids.get(timeout=5))
                    self.assertFalse(future.done())
                event = future.result(timeout=10)
        self.assertNotEqual(event.pk, self.latest.pk)
        self.latest.refresh_from_db()
        self.assertEqual(self.latest.reason, 'تغییر قبلی ساختگی')

    def test_failed_write_rolls_back_and_releases_latest_review_lock(self):
        with patch('sources.services.SourceClaimReview.objects.create', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                review_claim(actor=self.reviewer, claim_id=self.claim.pk, decision='defer', reason=REASON,
                             expected_review=self.latest.pk, expected_hash=self.claim.payload_sha256)
        self.assertEqual(SourceClaimReview.objects.filter(claim=self.claim).count(), 1)
        # Use a separate connection and a timeout to detect a leaked lock.
        def update():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '300ms'")
                    return SourceClaimReview.objects.filter(pk=self.latest.pk).update(reason=REASON)
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(pool.submit(update).result(timeout=10), 1)

    def test_actual_deadlock_with_review_lock_is_translated(self):
        # The uncooperative writer locks in reverse order; the service waits first.
        from .services import _lock_latest_review
        row_locked, waiting, start_cycle = Event(), Event(), Event()
        manual_pid, service_pid = Queue(), Queue()
        def manual():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                        cursor.execute("SET LOCAL statement_timeout = '8s'")
                        publish_backend_pid(cursor, manual_pid)
                    SourceClaimReview.objects.select_for_update().get(pk=self.latest.pk)
                    row_locked.set()
                    if not start_cycle.wait(6):
                        raise TimeoutError('Cycle not started')
                    SourceClaim.objects.select_for_update().get(pk=self.claim.pk)
            finally:
                connection.close()
        def signal(claim):
            waiting.set()
            return _lock_latest_review(claim)
        with patch('sources.services._lock_latest_review', side_effect=signal):
            with ThreadPoolExecutor(max_workers=2) as pool:
                other = pool.submit(manual)
                try:
                    self.assertTrue(row_locked.wait(5))
                    service = pool.submit(self.review, service_pid)
                    self.assertTrue(waiting.wait(5))
                    assert_blocked_by_backend(self, service_pid.get(timeout=5), manual_pid.get(timeout=5))
                    start_cycle.set()
                    with self.assertRaises(ReviewConflict) as caught:
                        service.result(timeout=10)
                    driver = caught.exception.__cause__.__cause__
                    self.assertEqual(getattr(driver, 'sqlstate', None) or getattr(driver, 'pgcode', None), '40P01')
                    other.result(timeout=10)
                finally:
                    start_cycle.set()
        self.assertEqual(SourceClaimReview.objects.filter(claim=self.claim).count(), 1)

    def test_actual_serialization_failure_in_writer_is_translated(self):
        ready, resume = Event(), Event()
        def writer():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.reviewer.pk)
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                        cursor.execute("SET LOCAL statement_timeout = '8s'")
                    SourceClaim.objects.get(pk=self.claim.pk)
                    ready.set()
                    if not resume.wait(6):
                        raise TimeoutError('Serialization test did not resume')
                    try:
                        review_claim(actor=actor, claim_id=self.claim.pk, decision='defer', reason=REASON,
                                     expected_review=self.latest.pk, expected_hash=self.claim.payload_sha256)
                    except ReviewConflict as exc:
                        driver = exc.__cause__.__cause__
                        code = getattr(driver, 'sqlstate', None) or getattr(driver, 'pgcode', None)
                        transaction.set_rollback(True)  # An outer serializable transaction must restart.
                        return code
                    raise AssertionError('Expected serialization conflict')
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(writer)
            try:
                self.assertTrue(ready.wait(5))
                SourceClaim.objects.filter(pk=self.claim.pk).update(owner='مالک ساختگی تغییر یافته')
            finally:
                resume.set()
            self.assertEqual(future.result(timeout=10), '40001')
        self.assertEqual(SourceClaimReview.objects.filter(claim=self.claim).count(), 1)
