"""PostgreSQL concurrent evidence and triage checks with synthetic data."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from .evidence import MAX_REFERENCES, add_reference, evidence_state
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
