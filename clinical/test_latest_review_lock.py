"""Selected clinical review-token races on synthetic PostgreSQL data."""
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
from .models import ClinicalDraftReview
from .services import DraftConflict, create_draft, review_draft

REASON = 'دلیل ساختگی برای بازبینی داخلی'


class ClinicalLatestReviewLockTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user('clinical-latest-author', is_staff=True)
        self.reviewer = User.objects.create_user('clinical-latest-reviewer', is_staff=True)
        permissions = Permission.objects.filter(content_type__app_label='clinical',
            codename__in=['view_clinicaldraft', 'add_clinicaldraft', 'review_clinicaldraft'])
        self.author.user_permissions.add(*permissions)
        self.reviewer.user_permissions.add(*permissions)
        self.draft = create_draft(actor=self.author, data={
            'subject': 'موضوع فرضی', 'audience': 'patient', 'title': 'عنوان ساختگی',
            'statement': 'متن ساختگی برای بررسی هم‌زمانی', 'reference_title': 'مرجع فرضی',
            'reference_url': 'https://example.org/synthetic', 'reference_location': 'بخش فرضی',
            'reference_author': '', 'reference_version': '', 'reference_published_on': None,
            'reference_accessed_on': None,
        })
        self.latest = review_draft(actor=self.reviewer, draft_id=self.draft.pk, decision='defer', reason=REASON,
                                   expected_review=0, expected_hash=self.draft.payload_sha256)

    def review(self, pids=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '12s'")
                publish_backend_pid(cursor, pids)
            actor = get_user_model().objects.get(pk=self.reviewer.pk)
            return review_draft(actor=actor, draft_id=self.draft.pk, decision='defer', reason=REASON,
                                expected_review=self.latest.pk, expected_hash=self.draft.payload_sha256)
        finally:
            connection.close()

    def _assert_latest_lock(self, operation):
        create = ClinicalDraftReview.objects.create
        paused, resume = Event(), Event()
        def pause_create(**kwargs):
            paused.set()
            if not resume.wait(8):
                raise TimeoutError('Synthetic review did not resume')
            return create(**kwargs)
        with patch('clinical.services.ClinicalDraftReview.objects.create', side_effect=pause_create):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.review)
                try:
                    self.assertTrue(paused.wait(8))
                    with self.assertRaises(DatabaseError) as caught:
                        with transaction.atomic():
                            with connection.cursor() as cursor:
                                cursor.execute("SET LOCAL lock_timeout = '300ms'")
                            rows = ClinicalDraftReview.objects.filter(pk=self.latest.pk)
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
        self.assertEqual(ClinicalDraftReview.objects.filter(pk=self.latest.pk).update(reason=REASON), 1)

    def test_review_locks_latest_against_bulk_update(self):
        self._assert_latest_lock('update')

    def test_review_locks_latest_against_bulk_delete(self):
        self._assert_latest_lock('delete')

    def test_helper_is_atomic_scoped_and_uses_one_bounded_lock_query(self):
        from .services import _lock_latest_review
        with self.assertRaises(TransactionManagementError):
            _lock_latest_review(self.draft)
        with transaction.atomic(), CaptureQueriesContext(connection) as queries:
            latest = _lock_latest_review(self.draft)
        self.assertEqual(latest.pk, self.latest.pk)
        self.assertEqual(len(queries), 1)
        sql = queries[0]['sql'].upper()
        self.assertIn('FOR UPDATE', sql)
        self.assertIn('ORDER BY', sql)
        self.assertIn('LIMIT 1', sql)

    def test_prior_uncommitted_deletion_is_reread_as_conflict(self):
        from .services import _lock_latest_review
        waiting, pids = Event(), Queue()
        def signal(draft):
            waiting.set()
            return _lock_latest_review(draft)
        with patch('clinical.services._lock_latest_review', side_effect=signal):
            with ThreadPoolExecutor(max_workers=1) as pool:
                with transaction.atomic():
                    ClinicalDraftReview.objects.filter(pk=self.latest.pk).delete()
                    future = pool.submit(self.review, pids)
                    self.assertTrue(waiting.wait(8))
                    assert_blocked_by_current_transaction(self, pids.get(timeout=5))
                    self.assertFalse(future.done())
                with self.assertRaises(DraftConflict):
                    future.result(timeout=10)
        self.assertFalse(ClinicalDraftReview.objects.filter(draft=self.draft).exists())

    def test_latest_row_is_locked_until_the_outer_transaction_ends(self):
        ready, resume = Event(), Event()
        def writer():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.reviewer.pk)
                with transaction.atomic():
                    event = review_draft(actor=actor, draft_id=self.draft.pk, decision='defer', reason=REASON,
                        expected_review=self.latest.pk, expected_hash=self.draft.payload_sha256)
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
                        ClinicalDraftReview.objects.filter(pk=self.latest.pk).update(reason='تغییر ساختگی')
                self.assertEqual(getattr(caught.exception.__cause__, 'sqlstate', None), '55P03')
            finally:
                resume.set()
            self.assertTrue(future.result(timeout=10))
        self.assertEqual(ClinicalDraftReview.objects.filter(pk=self.latest.pk).update(reason=REASON), 1)

    def test_no_latest_review_and_previous_id_only_semantics(self):
        from .services import _lock_latest_review
        # Corruption of the old review is not checked by this particular writer;
        # its existing optimistic token intentionally uses only the previous ID.
        ClinicalDraftReview.objects.filter(pk=self.latest.pk).update(reason='bad')
        event = review_draft(actor=self.reviewer, draft_id=self.draft.pk, decision='defer', reason=REASON,
                             expected_review=self.latest.pk, expected_hash=self.draft.payload_sha256)
        self.assertNotEqual(event.pk, self.latest.pk)
        ClinicalDraftReview.objects.filter(draft=self.draft).delete()
        with transaction.atomic():
            self.assertIsNone(_lock_latest_review(self.draft))
        event = review_draft(actor=self.reviewer, draft_id=self.draft.pk, decision='defer', reason=REASON,
                             expected_review=0, expected_hash=self.draft.payload_sha256)
        self.assertTrue(event.pk)

    def test_deferred_bypass_can_insert_later_review_after_writer_commit(self):
        ready, resume_writer, inserted, resume_inserter = Event(), Event(), Event(), Event()
        def writer():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.reviewer.pk)
                with transaction.atomic():
                    event = review_draft(actor=actor, draft_id=self.draft.pk, decision='defer', reason=REASON,
                        expected_review=self.latest.pk, expected_hash=self.draft.payload_sha256)
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
                    event = ClinicalDraftReview.objects.create(draft_id=self.draft.pk, reviewer_id=self.reviewer.pk,
                        decision='defer', reason=REASON, draft_payload_sha256=self.latest.draft_payload_sha256,
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
        self.assertEqual(ClinicalDraftReview.objects.filter(draft=self.draft).order_by('-pk').first().pk, bypass_pk)

    def test_older_review_remains_unlocked(self):
        self.latest = review_draft(actor=self.reviewer, draft_id=self.draft.pk, decision='defer', reason=REASON,
                                   expected_review=self.latest.pk, expected_hash=self.draft.payload_sha256)
        older = ClinicalDraftReview.objects.filter(draft=self.draft).order_by('pk').first()
        create = ClinicalDraftReview.objects.create
        ready, resume = Event(), Event()
        def pause_create(**kwargs):
            ready.set()
            if not resume.wait(8):
                raise TimeoutError('Synthetic review did not resume')
            return create(**kwargs)
        with patch('clinical.services.ClinicalDraftReview.objects.create', side_effect=pause_create):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.review)
                try:
                    self.assertTrue(ready.wait(8))
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL lock_timeout = '300ms'")
                        self.assertEqual(ClinicalDraftReview.objects.filter(pk=older.pk).update(reason='تغییر ساختگی'), 1)
                finally:
                    resume.set()
                self.assertTrue(future.result(timeout=10))
