"""PostgreSQL concurrent evidence and triage checks with synthetic data."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, current_thread
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from .evidence import MAX_REFERENCES, add_reference, evidence_state, reference_fingerprint, reviewed_evidence
from .models import ClinicalDraftReview, ClinicalReferenceAssertion
from .services import DraftConflict, create_draft, review_draft


class ClinicalConcurrentEvidenceTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user('concurrent-evidence-author', is_staff=True)
        self.actors = [User.objects.create_user(f'concurrent-evidence-{i}', is_staff=True) for i in range(2)]
        permissions = list(Permission.objects.filter(content_type__app_label='clinical',
                           codename__in=['view_clinicaldraft', 'add_clinicaldraft', 'review_clinicaldraft']))
        for user in [self.author, *self.actors]:
            user.user_permissions.add(*permissions)
        self.draft = create_draft(actor=self.author, data={
            'subject': 'موضوع فرضی', 'audience': 'patient', 'title': 'عنوان ساختگی',
            'statement': 'متن ساختگی جهت آزمایش هم‌زمانی.', 'reference_title': 'ارجاع اصلی ساختگی',
            'reference_url': 'https://example.org/primary', 'reference_location': 'بخش فرضی',
            'reference_author': '', 'reference_version': '', 'reference_published_on': None, 'reference_accessed_on': None,
        })
        self.ref = {'reference_title': 'ارجاع ساختگی', 'reference_url': 'https://example.org/reference',
                    'reference_location': 'بخش فرضی', 'reference_author': '', 'reference_version': '',
                    'reference_published_on': None, 'reference_accessed_on': None, 'relation': 'supports'}

    def race(self, funcs):
        barrier = Barrier(2, timeout=10)
        def worker(index):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actors[index].pk)
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                barrier.wait()
                try:
                    funcs[index](actor)
                    return 'created'
                except DraftConflict:
                    return 'conflict'
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, range(2)))

    def additions(self, fingerprint, titles):
        def operation(title):
            return lambda actor: add_reference(actor=actor, draft_id=self.draft.pk,
                data={**self.ref, 'reference_title': title}, expected_draft_hash=self.draft.payload_sha256,
                expected_evidence_hash=fingerprint)
        return [operation(title) for title in titles]

    def test_two_stale_additions_create_only_one_assertion(self):
        initial = evidence_state(self.draft)['fingerprint']
        self.assertCountEqual(self.race(self.additions(initial, ['یک ارجاع فرضی', 'ارجاع فرضی دیگر'])),
                              ['created', 'conflict'])
        self.assertEqual(ClinicalReferenceAssertion.objects.filter(draft=self.draft).count(), 1)
        self.assertEqual(evidence_state(self.draft)['status'], 'available')

    def test_cap_is_not_exceeded_by_concurrent_additions(self):
        for i in range(MAX_REFERENCES - 1):
            state = evidence_state(self.draft)
            add_reference(actor=self.actors[0], draft_id=self.draft.pk,
                data={**self.ref, 'reference_title': f'ارجاع ساختگی {i}'}, expected_draft_hash=self.draft.payload_sha256,
                expected_evidence_hash=state['fingerprint'])
        state = evidence_state(self.draft)
        self.assertCountEqual(self.race(self.additions(state['fingerprint'], ['آخرین ارجاع الف', 'آخرین ارجاع ب'])),
                              ['created', 'conflict'])
        self.assertEqual(ClinicalReferenceAssertion.objects.filter(draft=self.draft).count(), MAX_REFERENCES)
        self.assertEqual(evidence_state(self.draft)['status'], 'available')

    def test_two_reviewers_of_same_version_record_one_and_one_conflicts(self):
        initial = evidence_state(self.draft)['fingerprint']
        def review(actor):
            review_draft(actor=actor, draft_id=self.draft.pk, decision='defer',
                reason='این ارجاع ساختگی نیاز به بررسی دارد.', expected_review=0,
                expected_hash=self.draft.payload_sha256, expected_evidence_hash=initial)
        self.assertCountEqual(self.race([review, review]), ['created', 'conflict'])
        event = ClinicalDraftReview.objects.get(draft=self.draft)
        self.assertEqual(event.review_snapshot['evidence_fingerprint'], initial)
        self.assertEqual(event.review_snapshot['evidence_snapshot'], [])

    def test_bypass_mutation_of_reference_can_cross_parent_lock(self):
        initial = evidence_state(self.draft)['fingerprint']
        reference, _ = add_reference(actor=self.actors[0], draft_id=self.draft.pk, data=self.ref,
            expected_draft_hash=self.draft.payload_sha256, expected_evidence_hash=initial)
        current = evidence_state(self.draft)['fingerprint']
        ready, resume = Event(), Event()
        review_thread = []
        def paused_evidence(draft):
            state = evidence_state(draft)
            if review_thread and current_thread() is review_thread[0]:
                ready.set()
                if not resume.wait(8):
                    raise TimeoutError('Synthetic evidence review did not resume')
            return state
        def worker(fn):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '2s'")
                    cursor.execute("SET statement_timeout = '10s'")
                return fn()
            finally:
                connection.close()
        def review():
            review_thread.append(current_thread())
            actor = get_user_model().objects.get(pk=self.actors[1].pk)
            return review_draft(actor=actor, draft_id=self.draft.pk, decision='defer',
                reason='این ارجاع ساختگی نیاز به بررسی دارد.', expected_review=0,
                expected_hash=self.draft.payload_sha256, expected_evidence_hash=current).pk
        def bypass():
            changed = {**self.ref, 'reference_title': 'تغییر ساختگی با bypass'}
            # A bypass writer can make a new coherent payload/hash pair, not
            # merely corrupt an existing one, without locking the draft.
            return ClinicalReferenceAssertion.objects.filter(pk=reference.pk).update(
                reference_title=changed['reference_title'],
                payload_sha256=reference_fingerprint(changed, self.draft.pk, self.draft.payload_sha256))
        with patch('clinical.evidence.evidence_state', side_effect=paused_evidence):
            with ThreadPoolExecutor(max_workers=2) as pool:
                future = pool.submit(worker, review)
                try:
                    self.assertTrue(ready.wait(8), 'Review did not finish reading evidence under lock')
                    self.assertEqual(pool.submit(worker, bypass).result(timeout=10), 1)
                finally:
                    resume.set()
                event = ClinicalDraftReview.objects.get(pk=future.result(timeout=10))
        self.assertEqual(event.review_snapshot['evidence_fingerprint'], current)
        self.assertEqual(event.review_snapshot['evidence_snapshot'][0]['reference']['reference_title'], self.ref['reference_title'])
        after = evidence_state(self.draft)
        self.assertEqual(after['status'], 'available')
        self.assertNotEqual(after['fingerprint'], current)
        self.assertEqual(after['snapshot'][0]['reference']['reference_title'], 'تغییر ساختگی با bypass')
        self.assertEqual(reviewed_evidence(event)['status'], 'available')
        self.assertEqual(ClinicalDraftReview.objects.count(), 1)

    def test_review_and_reference_addition_share_draft_lock(self):
        initial = evidence_state(self.draft)['fingerprint']
        def add(actor):
            add_reference(actor=actor, draft_id=self.draft.pk, data=self.ref,
                          expected_draft_hash=self.draft.payload_sha256, expected_evidence_hash=initial)
        def review(actor):
            review_draft(actor=actor, draft_id=self.draft.pk, decision='defer',
                reason='این ارجاع ساختگی نیاز به بررسی دارد.', expected_review=0,
                expected_hash=self.draft.payload_sha256, expected_evidence_hash=initial)
        add_result, review_result = self.race([add, review])
        self.assertEqual(add_result, 'created')
        self.assertEqual(ClinicalReferenceAssertion.objects.filter(draft=self.draft).count(), 1)
        if review_result == 'created':
            review_event = ClinicalDraftReview.objects.get(draft=self.draft)
            self.assertEqual(review_event.review_snapshot['evidence_snapshot'], [])
            self.assertEqual(review_event.review_snapshot['evidence_fingerprint'], initial)
            self.assertNotEqual(evidence_state(self.draft)['fingerprint'], initial)
        else:
            self.assertEqual(review_result, 'conflict')
            self.assertFalse(ClinicalDraftReview.objects.filter(draft=self.draft).exists())
