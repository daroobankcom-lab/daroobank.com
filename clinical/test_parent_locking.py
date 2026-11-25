"""Selected PostgreSQL tests for locking an immediate synthetic draft parent."""
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

from .evidence import add_reference, evidence_state
from .models import ClinicalDraft, ClinicalDraftReview, ClinicalReferenceAssertion
from .services import (DraftConflict, create_draft, draft_data, fingerprint, review_draft, valid_draft,
                       _valid_draft_for_update, valid_payload)


class ClinicalParentLockingTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user('parent-lock-author', is_staff=True)
        self.recorder = User.objects.create_user('parent-lock-recorder', is_staff=True)
        self.reviewer = User.objects.create_user('parent-lock-reviewer', is_staff=True)
        perms = list(Permission.objects.filter(content_type__app_label='clinical',
            codename__in=['view_clinicaldraft', 'add_clinicaldraft', 'review_clinicaldraft']))
        for user in (self.author, self.recorder, self.reviewer):
            user.user_permissions.add(*perms)
        self.data = dict(subject='موضوع ساختگی', audience='patient', title='عنوان فرضی',
            statement='متن ساختگی برای آزمون نسخه‌ها', reference_title='ارجاع فرضی',
            reference_url='https://example.org/reference', reference_location='مکان فرضی',
            reference_author='', reference_version='', reference_published_on=None, reference_accessed_on=None)
        self.ref = dict(reference_title='ارجاع فرضی', reference_url='https://example.org/evidence',
            reference_location='محل فرضی', reference_author='', reference_version='',
            reference_published_on=None, reference_accessed_on=None, relation='supports')
        self.reason = 'تغییر فرضی برای آزمون این نسخه است.'

    def chain(self):
        parent = create_draft(actor=self.author, data=self.data)
        child = create_draft(actor=self.author, data=self.data, parent_id=parent.pk,
            expected_parent_hash=parent.payload_sha256, change_reason=self.reason)
        return parent, child

    def operation(self, kind, child):
        user = get_user_model()
        if kind == 'review':
            actor = user.objects.get(pk=self.reviewer.pk)
            return review_draft(actor=actor, draft_id=child.pk, decision='defer', reason=self.reason,
                expected_review=0, expected_hash=child.payload_sha256,
                expected_evidence_hash=evidence_state(child)['fingerprint'])
        if kind == 'add':
            actor = user.objects.get(pk=self.recorder.pk)
            return add_reference(actor=actor, draft_id=child.pk, data=self.ref,
                expected_draft_hash=child.payload_sha256, expected_evidence_hash=evidence_state(child)['fingerprint'])
        actor = user.objects.get(pk=self.author.pk)
        return create_draft(actor=actor, data=self.data, parent_id=child.pk,
            expected_parent_hash=child.payload_sha256, change_reason=self.reason)

    def update_parent(self, parent):
        changed = {**draft_data(parent), 'title': 'تغییر معتبر ولی هم‌زمان والد'}
        digest = fingerprint(changed, parent.parent_id, parent.parent_payload_sha256, parent.change_reason)
        return ClinicalDraft.objects.filter(pk=parent.pk).update(title=changed['title'], payload_sha256=digest)

    def worker(self, fn, timeout='5s'):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('lock_timeout', %s, false)", [timeout])
                cursor.execute("SET statement_timeout = '12s'")
            return fn()
        finally:
            connection.close()

    def wait_until_blocked(self, pid, future):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            with connection.cursor() as cursor:
                cursor.execute('SELECT cardinality(pg_blocking_pids(%s)) > 0', [pid])
                if cursor.fetchone()[0]:
                    return True
            if future.done():
                return False
            time.sleep(0.05)
        return False

    def test_parent_update_waits_while_each_writer_holds_its_locks(self):
        for kind in ('review', 'add', 'revise'):
            with self.subTest(kind=kind):
                parent, child = self.chain()
                ready, resume = Event(), Event()
                worker_thread = []
                def pause(draft):
                    result = valid_draft(draft)
                    if worker_thread and current_thread() is worker_thread[0] and draft.pk == child.pk:
                        ready.set()
                        if not resume.wait(8):
                            raise TimeoutError('Synthetic writer did not resume')
                    return result
                def perform():
                    worker_thread.append(current_thread())
                    return self.operation(kind, child)
                with patch('clinical.services.valid_draft', side_effect=pause):
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        future = pool.submit(self.worker, perform)
                        try:
                            self.assertTrue(ready.wait(8), f'{kind} did not validate under locks')
                            with self.assertRaises(OperationalError):
                                pool.submit(self.worker, lambda: self.update_parent(parent), '300ms').result(timeout=10)
                        finally:
                            resume.set()
                        self.assertIsNotNone(future.result(timeout=10))
                        self.assertEqual(pool.submit(self.worker, lambda: self.update_parent(parent)).result(timeout=10), 1)
                child.refresh_from_db()
                self.assertFalse(valid_draft(child))  # a later bypass can still invalidate the child

    def test_waiting_writers_recheck_parent_after_a_committed_update(self):
        for kind in ('review', 'add', 'revise'):
            with self.subTest(kind=kind):
                parent, child = self.chain()
                pid_queue = Queue()
                def perform():
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT pg_backend_pid()')
                        pid_queue.put(cursor.fetchone()[0])
                    return self.operation(kind, child)
                before = (ClinicalDraft.objects.count(), ClinicalDraftReview.objects.count(), ClinicalReferenceAssertion.objects.count())
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with transaction.atomic():
                        self.update_parent(parent)
                        future = pool.submit(self.worker, perform)
                        pid = pid_queue.get(timeout=8)
                        self.assertTrue(self.wait_until_blocked(pid, future), f'{kind} did not wait for parent row')
                    with self.assertRaises(DraftConflict):
                        future.result(timeout=10)
                self.assertEqual(before, (ClinicalDraft.objects.count(), ClinicalDraftReview.objects.count(),
                                          ClinicalReferenceAssertion.objects.count()))
                self.assertFalse(valid_draft(ClinicalDraft.objects.select_related('parent').get(pk=child.pk)))

    def test_writer_helper_requires_atomic_even_for_root(self):
        parent, child = self.chain()
        for draft in (parent, child):
            with self.subTest(pk=draft.pk), self.assertRaises(TransactionManagementError):
                _valid_draft_for_update(draft)

    def test_locked_read_discards_stale_preloaded_parent(self):
        parent, child = self.chain()
        with transaction.atomic():
            selected = ClinicalDraft.objects.select_for_update(of=('self',)).select_related('parent').get(pk=child.pk)
            self.assertTrue(valid_draft(selected))
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertEqual(pool.submit(self.worker, lambda: self.update_parent(parent)).result(timeout=10), 1)
            self.assertTrue(valid_draft(selected))  # the joined in-memory parent is now stale
            self.assertFalse(_valid_draft_for_update(selected))
            self.assertFalse(valid_draft(selected))

    def test_sibling_reviews_serialize_on_shared_parent(self):
        parent, first_child = self.chain()
        second_child = create_draft(actor=self.author, data=self.data, parent_id=parent.pk,
            expected_parent_hash=parent.payload_sha256, change_reason=self.reason)
        ready, resume = Event(), Event()
        thread = []
        pid_queue = Queue()
        def pause(draft):
            result = valid_draft(draft)
            if thread and current_thread() is thread[0] and draft.pk == first_child.pk:
                ready.set()
                if not resume.wait(8):
                    raise TimeoutError('Synthetic sibling review did not resume')
            return result
        def first():
            thread.append(current_thread())
            return self.operation('review', first_child)
        def second():
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_backend_pid()')
                pid_queue.put(cursor.fetchone()[0])
            return self.operation('review', second_child)
        with patch('clinical.services.valid_draft', side_effect=pause):
            with ThreadPoolExecutor(max_workers=2) as pool:
                f1 = pool.submit(self.worker, first)
                try:
                    self.assertTrue(ready.wait(8))
                    f2 = pool.submit(self.worker, second)
                    self.assertTrue(self.wait_until_blocked(pid_queue.get(timeout=8), f2), 'Sibling did not wait')
                finally:
                    resume.set()
                self.assertIsNotNone(f1.result(timeout=10))
                self.assertIsNotNone(f2.result(timeout=10))
        self.assertEqual(ClinicalDraftReview.objects.count(), 2)

    def test_parent_lock_survives_inner_write_until_outer_commit(self):
        for kind in ('review', 'add', 'revise'):
            with self.subTest(kind=kind):
                parent, child = self.chain()
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with transaction.atomic():
                        self.assertIsNotNone(self.operation(kind, child))
                        with self.assertRaises(OperationalError):
                            pool.submit(self.worker, lambda: self.update_parent(parent), '300ms').result(timeout=10)
                    self.assertEqual(pool.submit(self.worker, lambda: self.update_parent(parent)).result(timeout=10), 1)

    def test_failed_event_write_releases_parent_lock(self):
        parent, child = self.chain()
        with patch('clinical.services.ClinicalDraftReview.objects.create', side_effect=RuntimeError('synthetic write failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic write failure'):
                self.operation('review', child)
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertEqual(pool.submit(self.worker, lambda: self.update_parent(parent), '300ms').result(timeout=10), 1)
        self.assertFalse(ClinicalDraftReview.objects.exists())

    def test_missing_or_invalid_parent_fails_closed_and_invalid_child_does_not_lock_parent(self):
        gap = create_draft(actor=self.author, data=self.data)
        gap_id = gap.pk
        ClinicalDraft.objects.filter(pk=gap_id).delete()
        parent, child = self.chain()
        old = (child.parent_id, child.payload_sha256)
        digest = fingerprint(draft_data(child), gap_id, child.parent_payload_sha256, child.change_reason)
        with transaction.atomic():
            try:
                ClinicalDraft.objects.filter(pk=child.pk).update(parent_id=gap_id, payload_sha256=digest)
                bad = ClinicalDraft.objects.select_for_update().get(pk=child.pk)
                self.assertTrue(valid_payload(bad))
                self.assertFalse(_valid_draft_for_update(bad))
                with self.assertRaises(DraftConflict):
                    self.operation('review', bad)
            finally:
                ClinicalDraft.objects.filter(pk=child.pk).update(parent_id=old[0], payload_sha256=old[1])
        with transaction.atomic():
            bad = ClinicalDraft.objects.select_for_update().get(pk=child.pk)
            bad.title = 'ناسازگار'
            with CaptureQueriesContext(connection) as queries:
                self.assertFalse(_valid_draft_for_update(bad))
            self.assertEqual(len(queries), 0)
        self.assertFalse(ClinicalDraftReview.objects.exists())
        self.update_parent(parent)
        with self.assertRaises(DraftConflict):
            self.operation('add', child)
        self.assertFalse(ClinicalReferenceAssertion.objects.exists())

    def test_root_requires_no_parent_select_child_requires_one(self):
        parent, child = self.chain()
        self.recorder.has_perm('clinical.add_clinicaldraft')
        for draft, expected_count in ((parent, 1), (child, 2)):
            with self.subTest(expected_count=expected_count):
                with transaction.atomic(), CaptureQueriesContext(connection) as queries:
                    add_reference(actor=self.recorder, draft_id=draft.pk, data=self.ref,
                        expected_draft_hash=draft.payload_sha256, expected_evidence_hash=evidence_state(draft)['fingerprint'])
                draft_locks = [q['sql'].upper() for q in queries if 'FOR UPDATE' in q['sql'].upper()
                               and '"CLINICAL_CLINICALDRAFT"' in q['sql'].upper()]
                self.assertEqual(len(draft_locks), expected_count)
                self.assertTrue(all(' JOIN ' not in query for query in draft_locks))

    def test_read_only_validation_does_not_lock_parent(self):
        parent, child = self.chain()
        with transaction.atomic():
            self.update_parent(parent)
            with ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(self.worker, lambda: valid_draft(
                    ClinicalDraft.objects.select_related('parent').get(pk=child.pk)), '300ms').result(timeout=10)
                self.assertTrue(result)  # previous committed parent, no wait
        self.assertFalse(valid_draft(ClinicalDraft.objects.select_related('parent').get(pk=child.pk)))

    def test_grandparent_is_not_locked_or_certified(self):
        root, child = self.chain()
        grandchild = create_draft(actor=self.author, data=self.data, parent_id=child.pk,
            expected_parent_hash=child.payload_sha256, change_reason=self.reason)
        ready, resume = Event(), Event()
        thread = []
        def pause(draft):
            result = valid_draft(draft)
            if thread and current_thread() is thread[0] and draft.pk == grandchild.pk:
                ready.set()
                if not resume.wait(8):
                    raise TimeoutError('Synthetic review did not resume')
            return result
        def review():
            thread.append(current_thread())
            return self.operation('review', grandchild)
        with patch('clinical.services.valid_draft', side_effect=pause):
            with ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(self.worker, review)
                try:
                    self.assertTrue(ready.wait(8))
                    self.assertEqual(pool.submit(self.worker, lambda: self.update_parent(root), '300ms').result(timeout=10), 1)
                finally:
                    resume.set()
                self.assertIsNotNone(future.result(timeout=10))
        fresh_child = ClinicalDraft.objects.select_related('parent').get(pk=child.pk)
        fresh_grandchild = ClinicalDraft.objects.select_related('parent').get(pk=grandchild.pk)
        self.assertFalse(valid_draft(fresh_child))
        self.assertTrue(valid_draft(fresh_grandchild))  # local check is only one level deep
