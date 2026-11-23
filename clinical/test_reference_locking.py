"""Selected PostgreSQL interleavings for synthetic supplementary reference locks."""
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event, current_thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import OperationalError, close_old_connections, connection, transaction
from django.db.transaction import TransactionManagementError
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from .evidence import MAX_REFERENCES, add_reference, evidence_state, reference_fingerprint
from .models import ClinicalDraft, ClinicalDraftReview, ClinicalReferenceAssertion
from .services import DraftConflict, create_draft, review_draft, valid_draft


class ClinicalReferenceLockingTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user('ref-lock-author', is_staff=True)
        self.recorder = User.objects.create_user('ref-lock-recorder', is_staff=True)
        self.reviewer = User.objects.create_user('ref-lock-reviewer', is_staff=True)
        perms = list(Permission.objects.filter(content_type__app_label='clinical',
            codename__in=['view_clinicaldraft', 'add_clinicaldraft', 'review_clinicaldraft']))
        for user in (self.author, self.recorder, self.reviewer):
            user.user_permissions.add(*perms)
        self.data = dict(subject='موضوع ساختگی', audience='patient', title='عنوان فرضی',
            statement='این متن صرفاً برای آزمایش ساختگی است.', reference_title='ارجاع اصلی',
            reference_url='https://example.org/main', reference_location='بخش ساختگی', reference_author='',
            reference_version='', reference_published_on=None, reference_accessed_on=None)
        self.ref = dict(reference_title='ارجاع ساختگی', reference_url='https://example.org/ref',
            reference_location='مکان فرضی', reference_author='', reference_version='',
            reference_published_on=None, reference_accessed_on=None, relation='supports')
        self.draft = create_draft(actor=self.author, data=self.data)
        self.initial = evidence_state(self.draft)['fingerprint']
        self.reference, _ = self.add(self.ref, self.initial)
        self.current = evidence_state(self.draft)['fingerprint']

    def add(self, data, expected):
        return add_reference(actor=self.recorder, draft_id=self.draft.pk, data=data,
            expected_draft_hash=self.draft.payload_sha256, expected_evidence_hash=expected)

    def review(self, *, draft=None, expected=None):
        draft = draft or self.draft
        return review_draft(actor=self.reviewer, draft_id=draft.pk, decision='defer',
            reason='این ارجاع ساختگی نیازمند بررسی بیشتر است.', expected_review=0,
            expected_hash=draft.payload_sha256, expected_evidence_hash=expected or self.current)

    def change(self, reference=None, title='عنوان تغییر یافته'):
        reference = reference or self.reference
        changed = {**self.ref, 'reference_title': title}
        return ClinicalReferenceAssertion.objects.filter(pk=reference.pk).update(
            reference_title=title, payload_sha256=reference_fingerprint(changed, self.draft.pk, self.draft.payload_sha256))

    def worker(self, fn, timeout='3s'):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('lock_timeout', %s, false)", [timeout])
                cursor.execute("SET statement_timeout = '12s'")
            return fn()
        finally:
            connection.close()

    def test_reference_writer_before_review_causes_wait_then_stale_conflict(self):
        def review():
            self.reviewer = get_user_model().objects.get(pk=self.reviewer.pk)
            return self.review()
        with transaction.atomic():
            self.change()
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(OperationalError):
                    pool.submit(self.worker, review, '300ms').result(timeout=10)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with self.assertRaises(DraftConflict):
                pool.submit(self.worker, review).result(timeout=10)
        self.assertEqual(evidence_state(self.draft)['status'], 'available')
        self.assertFalse(ClinicalDraftReview.objects.exists())

    def test_waiting_review_and_addition_observe_committed_reference_change(self):
        for operation in ('review', 'add'):
            with self.subTest(operation=operation):
                expected = evidence_state(self.draft)['fingerprint']
                pid_queue = Queue()
                def attempt():
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_backend_pid()')
                        pid_queue.put(cursor.fetchone()[0])
                    if operation == 'review':
                        self.reviewer = get_user_model().objects.get(pk=self.reviewer.pk)
                        return self.review(expected=expected)
                    self.recorder = get_user_model().objects.get(pk=self.recorder.pk)
                    return self.add({**self.ref, 'reference_title': 'ارجاع دیگر'}, expected)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with transaction.atomic():
                        self.change(title=f'به‌روزرسانی ساختگی {operation}')
                        future = pool.submit(self.worker, attempt, '5s')
                        pid = pid_queue.get(timeout=8)
                        deadline = time.monotonic() + 4
                        blocked = False
                        while time.monotonic() < deadline:
                            with connection.cursor() as cursor:
                                cursor.execute('SELECT cardinality(pg_blocking_pids(%s)) > 0', [pid])
                                blocked = cursor.fetchone()[0]
                            if blocked or future.done():
                                break
                            time.sleep(0.05)
                        self.assertTrue(blocked, f'{operation} did not wait for the reference update')
                    with self.assertRaises(DraftConflict):
                        future.result(timeout=10)
                self.assertEqual(evidence_state(self.draft)['status'], 'available')
                self.assertFalse(ClinicalDraftReview.objects.exists())
                self.assertEqual(ClinicalReferenceAssertion.objects.count(), 1)

    def test_addition_locks_existing_rows_then_releases_them(self):
        ready, resume = Event(), Event()
        thread = []
        def pause(draft, *, lock=False):
            result = evidence_state(draft, lock=lock)
            if thread and current_thread() is thread[0]:
                self.assertTrue(lock)
                ready.set()
                if not resume.wait(8):
                    raise TimeoutError('Synthetic add did not resume')
            return result
        def add():
            thread.append(current_thread())
            self.recorder = get_user_model().objects.get(pk=self.recorder.pk)
            return self.add({**self.ref, 'reference_title': 'ارجاع دوم ساختگی'}, self.current)[1]
        with patch('clinical.evidence.evidence_state', side_effect=pause):
            with ThreadPoolExecutor(max_workers=2) as pool:
                addition = pool.submit(self.worker, add)
                try:
                    self.assertTrue(ready.wait(8))
                    with self.assertRaises(OperationalError):
                        pool.submit(self.worker, self.change, '300ms').result(timeout=10)
                finally:
                    resume.set()
                self.assertTrue(addition.result(timeout=10))
                self.assertEqual(pool.submit(self.worker, self.change).result(timeout=10), 1)
        self.assertEqual(ClinicalReferenceAssertion.objects.count(), 2)
        self.assertEqual(evidence_state(self.draft)['status'], 'available')

    def test_read_only_observation_does_not_lock_or_wait_for_writer(self):
        with transaction.atomic():
            self.change()
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(self.worker, lambda: evidence_state(self.draft), '300ms').result(timeout=10)
                self.assertEqual(result['fingerprint'], self.current)
        self.assertNotEqual(evidence_state(self.draft)['fingerprint'], self.current)

    def test_writer_lock_is_transactional_and_read_query_count_unchanged(self):
        with CaptureQueriesContext(connection) as reads:
            self.assertEqual(evidence_state(self.draft)['status'], 'available')
        self.assertEqual(len(reads), 2)
        self.assertNotIn('FOR UPDATE', reads[0]['sql'].upper())
        with transaction.atomic(), CaptureQueriesContext(connection) as writes:
            self.assertEqual(evidence_state(self.draft, lock=True)['status'], 'available')
        self.assertEqual(len(writes), 2)
        self.assertIn('FOR UPDATE', writes[0]['sql'].upper())
        self.assertIn('LIMIT 11', writes[0]['sql'].upper())
        with self.assertRaises(TransactionManagementError):
            evidence_state(self.draft, lock=True)

    def test_reference_lock_survives_inner_service_until_outer_commit(self):
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                event = self.review()
                self.assertEqual(event.review_snapshot['evidence_fingerprint'], self.current)
                with self.assertRaises(OperationalError):
                    pool.submit(self.worker, self.change, '300ms').result(timeout=10)
            self.assertEqual(pool.submit(self.worker, self.change, '300ms').result(timeout=10), 1)
        self.assertEqual(ClinicalDraftReview.objects.count(), 1)
        self.assertNotEqual(evidence_state(self.draft)['fingerprint'], self.current)

    def test_existing_reference_delete_waits_for_review_transaction(self):
        def delete():
            return ClinicalReferenceAssertion.objects.filter(pk=self.reference.pk).delete()[0]
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                event = self.review()
                with self.assertRaises(OperationalError):
                    pool.submit(self.worker, delete, '300ms').result(timeout=10)
                self.assertEqual(ClinicalReferenceAssertion.objects.count(), 1)
            self.assertEqual(pool.submit(self.worker, delete, '300ms').result(timeout=10), 1)
        self.assertEqual(len(event.review_snapshot['evidence_snapshot']), 1)
        self.assertEqual(evidence_state(self.draft)['snapshot'], [])

    def test_failed_review_or_add_rolls_back_and_releases_reference_lock(self):
        with patch('clinical.services.ClinicalDraftReview.objects.create', side_effect=RuntimeError('synthetic review error')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic review error'):
                self.review()
        with patch('clinical.evidence.ClinicalReferenceAssertion.objects.create', side_effect=RuntimeError('synthetic add error')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic add error'):
                self.add({**self.ref, 'reference_title': 'دومین ارجاع ساختگی'}, self.current)
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(pool.submit(self.worker, self.change, '300ms').result(timeout=10), 1)
        self.assertFalse(ClinicalDraftReview.objects.exists())
        self.assertEqual(ClinicalReferenceAssertion.objects.count(), 1)

    def test_over_limit_locks_first_eleven_not_twelfth(self):
        refs = [self.reference]
        for i in range(1, MAX_REFERENCES + 2):
            data = {**self.ref, 'reference_title': f'ارجاع فرضی {i}'}
            refs.append(ClinicalReferenceAssertion.objects.create(draft=self.draft,
                draft_payload_sha256=self.draft.payload_sha256, recorded_by=self.recorder,
                payload_sha256=reference_fingerprint(data, self.draft.pk, self.draft.payload_sha256), **data))
        self.assertEqual(len(refs), 12)
        ready, resume = Event(), Event()
        def hold():
            with transaction.atomic():
                status = evidence_state(self.draft, lock=True)['status']
                ready.set()
                if not resume.wait(8):
                    raise TimeoutError('Synthetic bounded scan did not resume')
                return status
        def touch(ref):
            return ClinicalReferenceAssertion.objects.filter(pk=ref.pk).update(reference_title='تغییر فرضی')
        with ThreadPoolExecutor(max_workers=2) as pool:
            locked = pool.submit(self.worker, hold)
            try:
                self.assertTrue(ready.wait(8))
                with self.assertRaises(OperationalError):
                    pool.submit(self.worker, lambda: touch(refs[10]), '300ms').result(timeout=10)
                self.assertEqual(pool.submit(self.worker, lambda: touch(refs[11]), '300ms').result(timeout=10), 1)
            finally:
                resume.set()
            self.assertEqual(locked.result(timeout=10), 'over_limit')
        self.assertFalse(ClinicalDraftReview.objects.exists())

    def test_deferred_insert_can_be_pending_during_review_then_commit_later(self):
        ready, resume, inserted, allow_commit = Event(), Event(), Event(), Event()
        review_thread = []
        def pause(draft, *, lock=False):
            state = evidence_state(draft, lock=lock)
            if review_thread and current_thread() is review_thread[0]:
                ready.set()
                if not resume.wait(8):
                    raise TimeoutError('Synthetic review did not resume')
            return state
        def review():
            review_thread.append(current_thread())
            self.reviewer = get_user_model().objects.get(pk=self.reviewer.pk)
            return self.review().pk
        def bypass_insert():
            changed = {**self.ref, 'reference_title': 'ارجاع جدید غیرهمکار'}
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute('SET CONSTRAINTS ALL DEFERRED')
                item = ClinicalReferenceAssertion.objects.create(
                    draft_id=self.draft.pk, draft_payload_sha256=self.draft.payload_sha256,
                    recorded_by_id=self.recorder.pk,
                    payload_sha256=reference_fingerprint(changed, self.draft.pk, self.draft.payload_sha256), **changed)
                inserted.set()
                if not allow_commit.wait(8):
                    raise TimeoutError('Synthetic insertion did not resume')
            return item.pk
        with patch('clinical.evidence.evidence_state', side_effect=pause):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.worker, review)
                second = None
                try:
                    self.assertTrue(ready.wait(8))
                    second = pool.submit(self.worker, bypass_insert, '5s')
                    self.assertTrue(inserted.wait(8), 'Deferred insert did not reach the uncommitted state')
                    self.assertEqual(evidence_state(self.draft)['fingerprint'], self.current)
                    resume.set()
                    event = ClinicalDraftReview.objects.get(pk=first.result(timeout=10))
                    self.assertEqual(event.review_snapshot['evidence_fingerprint'], self.current)
                finally:
                    resume.set()
                    allow_commit.set()
                self.assertIsNotNone(second.result(timeout=10))
        new_state = evidence_state(self.draft)
        self.assertEqual(new_state['status'], 'available')
        self.assertNotEqual(new_state['fingerprint'], self.current)
        self.assertEqual(len(new_state['items']), 2)

    def test_review_locks_immediate_parent_but_later_bypass_can_change_it(self):
        child = create_draft(actor=self.author, data=self.data, parent_id=self.draft.pk,
            expected_parent_hash=self.draft.payload_sha256, change_reason='اصلاح ساختگی برای بررسی بیشتر')
        child_evidence = evidence_state(child)['fingerprint']
        ready, resume = Event(), Event()
        review_thread = []
        def pause(draft):
            result = valid_draft(draft)
            if review_thread and current_thread() is review_thread[0]:
                ready.set()
                if not resume.wait(8):
                    raise TimeoutError('Synthetic review did not resume')
            return result
        def review():
            review_thread.append(current_thread())
            self.reviewer = get_user_model().objects.get(pk=self.reviewer.pk)
            return self.review(draft=child, expected=child_evidence).pk
        def change_parent():
            return ClinicalDraft.objects.filter(pk=self.draft.pk).update(title='تغییر ساختگی والد با bypass')
        with patch('clinical.services.valid_draft', side_effect=pause):
            with ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(self.worker, review)
                try:
                    self.assertTrue(ready.wait(8))
                    with self.assertRaises(OperationalError):
                        pool.submit(self.worker, change_parent, '300ms').result(timeout=10)
                finally:
                    resume.set()
                event = ClinicalDraftReview.objects.get(pk=future.result(timeout=10))
                self.assertEqual(pool.submit(self.worker, change_parent, '300ms').result(timeout=10), 1)
        self.assertEqual(event.draft_id, child.pk)
        fresh = ClinicalDraft.objects.select_related('parent').get(pk=child.pk)
        self.assertFalse(valid_draft(fresh))
