from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog.models import ProductPresentation
from pricing.models import PriceCandidate
from .evidence import MAX_REFERENCES, add_reference, evidence_state, reference_fingerprint, valid_reference
from .models import ClinicalDraft, ClinicalDraftReview, ClinicalReferenceAssertion
from .services import DraftConflict, DraftError, create_draft, draft_data, fingerprint, review_draft


class ClinicalEvidenceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.author = U.objects.create_user('evidence-draft-author', password='test-only-password', is_staff=True)
        cls.recorder = U.objects.create_user('evidence-recorder', password='test-only-password', is_staff=True)
        cls.reviewer = U.objects.create_user('evidence-reviewer', password='test-only-password', is_staff=True)
        cls.viewer = U.objects.create_user('evidence-viewer', password='test-only-password', is_staff=True)
        cls.add_only = U.objects.create_user('evidence-add-only', password='test-only-password', is_staff=True)
        cls.regular = U.objects.create_user('evidence-regular', password='test-only-password')
        cls.inactive = U.objects.create_user('evidence-inactive', password='test-only-password', is_staff=True, is_active=False)
        perms = Permission.objects.filter(content_type__app_label='clinical')
        cls.author.user_permissions.add(*perms.filter(codename__in=['view_clinicaldraft', 'add_clinicaldraft', 'review_clinicaldraft']))
        cls.recorder.user_permissions.add(*perms.filter(codename__in=['view_clinicaldraft', 'add_clinicaldraft', 'review_clinicaldraft']))
        cls.reviewer.user_permissions.add(*perms.filter(codename__in=['view_clinicaldraft', 'review_clinicaldraft']))
        cls.viewer.user_permissions.add(perms.get(codename='view_clinicaldraft'))
        cls.add_only.user_permissions.add(perms.get(codename='add_clinicaldraft'))
        cls.regular.user_permissions.add(perms.get(codename='view_clinicaldraft'))
        cls.inactive.user_permissions.add(*perms.filter(codename__in=['view_clinicaldraft', 'add_clinicaldraft']))
        cls.draft_data = {'subject': 'موضوع ساختگی', 'audience': 'patient', 'title': 'عنوان ساختگی',
            'statement': 'این متن صرفاً یک نمونه ساختگی برای آزمون است.', 'reference_title': 'ارجاع اصلی فرضی',
            'reference_url': 'https://example.org/primary', 'reference_location': 'بخش فرضی',
            'reference_author': '', 'reference_version': '', 'reference_published_on': None, 'reference_accessed_on': None}
        cls.ref_data = {'reference_title': 'ارجاع تکمیلی ساختگی', 'reference_url': 'https://example.org/evidence',
            'reference_location': 'بخش فرضی دو', 'reference_author': 'نویسنده فرضی', 'reference_version': 'نسخه ساختگی',
            'reference_published_on': date(2024, 1, 2), 'reference_accessed_on': None, 'relation': 'supports'}

    def draft(self):
        return create_draft(actor=self.author, data=self.draft_data)

    def add(self, draft, actor=None, data=None, expected=None):
        return add_reference(actor=actor or self.recorder, draft_id=draft.pk, data=data or self.ref_data,
            expected_draft_hash=draft.payload_sha256,
            expected_evidence_hash=expected if expected is not None else evidence_state(draft)['fingerprint'])

    def review_data(self, draft, expected_review=0):
        return {'decision': 'further_review', 'reason': 'این ارجاع ساختگی نیاز به بررسی دارد.',
                'expected_review': expected_review, 'expected_hash': draft.payload_sha256,
                'expected_evidence_hash': evidence_state(draft)['fingerprint']}

    def form_data(self, draft, data=None):
        data = dict(data or self.ref_data)
        for key in ['reference_published_on', 'reference_accessed_on']:
            data[key] = data[key].isoformat() if data[key] else ''
        return {**data, 'synthetic_ack': 'on', 'expected_draft_hash': draft.payload_sha256,
                'expected_evidence_hash': evidence_state(draft)['fingerprint']}

    def detail(self, draft):
        return self.client.get(reverse('staff_clinical_detail', args=[draft.pk]))

    def assert_private(self, response):
        self.assertIn('no-store', response['Cache-Control']); self.assertIn('private', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow'); self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_add_form_permissions_duplicate_provenance_and_privacy(self):
        draft = self.draft(); url = reverse('staff_clinical_reference_create', args=[draft.pk])
        response = self.client.get(url); self.assertEqual(response.status_code, 302); self.assert_private(response)
        for user in [self.viewer, self.reviewer, self.add_only, self.regular]:
            self.client.force_login(user); self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, self.form_data(draft)).status_code, 403)
        self.client.force_login(self.inactive); self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.recorder)
        payload = self.form_data(draft); payload.pop('synthetic_ack')
        self.assertEqual(self.client.post(url, payload).status_code, 200); self.assertEqual(ClinicalReferenceAssertion.objects.count(), 0)
        response = self.client.post(url, self.form_data(draft))
        self.assertRedirects(response, reverse('staff_clinical_detail', args=[draft.pk]))
        ref = ClinicalReferenceAssertion.objects.get(); self.assertEqual(ref.recorded_by, self.recorder)
        self.assertEqual(ref.reference_published_on, date(2024, 1, 2)); self.assertTrue(valid_reference(ref, draft))
        self.client.force_login(self.author)
        self.assertEqual(self.client.post(url, self.form_data(draft)).status_code, 302)
        ref.refresh_from_db(); self.assertEqual(ref.recorded_by, self.recorder)
        self.assertEqual(ClinicalReferenceAssertion.objects.count(), 1)
        detail = self.detail(draft); self.assertContains(detail, ref.reference_title)
        self.assertContains(detail, 'پشتیبان ادعایی'); self.assertNotContains(detail, 'href="https://example.org/evidence"')
        self.assert_private(detail)
        for obj in [ref]:
            with self.assertRaises(ValidationError): obj.save()
            with self.assertRaises(ValidationError): obj.delete()

    def test_group_authorization_and_invalid_input_never_fetches(self):
        draft = self.draft()
        group = Group.objects.create(name='evidence-synthetic-writers')
        group.permissions.add(*Permission.objects.filter(content_type__app_label='clinical', codename__in=['view_clinicaldraft', 'add_clinicaldraft']))
        user = get_user_model().objects.create_user('evidence-group', is_staff=True); user.groups.add(group)
        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            ref, created = self.add(draft, actor=user)
        self.assertTrue(created); self.assertEqual(ref.recorded_by, user)
        for user in [self.viewer, self.reviewer, self.add_only, self.regular, self.inactive]:
            with self.subTest(user=user), self.assertRaises(PermissionDenied): self.add(draft, actor=user)
        for changes in [dict(reference_title=''), dict(reference_location='\u200d'), dict(relation='unknown'),
                        dict(reference_url='https://@example.org'), dict(reference_url='https://example.org/?'),
                        dict(reference_url='https://example.org/#'), dict(reference_url='http://example.org'),
                        dict(reference_author='\ud800'), dict(reference_version='a\x00b'),
                        dict(reference_published_on='2024-01-02')]:
            with self.subTest(changes=ascii(changes)), self.assertRaises(DraftError):
                self.add(draft, data={**self.ref_data, **changes})
        self.assertEqual(ClinicalReferenceAssertion.objects.count(), 1)

    def test_optimistic_conflict_for_add_and_stale_review(self):
        draft = self.draft(); initial = evidence_state(draft)['fingerprint']
        old_review = self.review_data(draft)
        self.add(draft)
        with self.assertRaises(DraftConflict): self.add(draft, data={**self.ref_data, 'reference_title': 'منبع دیگر'}, expected=initial)
        with self.assertRaises(DraftConflict): review_draft(actor=self.reviewer, draft_id=draft.pk, **old_review)
        with self.assertRaises(DraftConflict):
            review_draft(actor=self.reviewer, draft_id=draft.pk, **{k: v for k, v in self.review_data(draft).items() if k != 'expected_evidence_hash'})
        self.client.force_login(self.reviewer)
        response = self.client.post(reverse('staff_clinical_review', args=[draft.pk]), old_review)
        self.assertEqual(response.status_code, 409); self.assertContains(response, 'ارجاع‌های تکمیلی تغییر کرده‌اند', status_code=409)
        self.assertEqual(ClinicalDraftReview.objects.count(), 0)
        self.client.force_login(self.recorder)
        data = self.form_data(draft); data['expected_evidence_hash'] = initial; data['reference_title'] = 'ارجاع دیگر'
        response = self.client.post(reverse('staff_clinical_reference_create', args=[draft.pk]), data)
        self.assertEqual(response.status_code, 409); self.assertEqual(ClinicalReferenceAssertion.objects.count(), 1)

    def test_review_separation_snapshot_and_changed_state(self):
        draft = self.draft(); ref, _ = self.add(draft)
        self.client.force_login(self.recorder)
        detail = self.detail(draft)
        self.assertContains(detail, 'ثبت‌کننده ارجاع تکمیلی نمی‌تواند این مجموعه را بازبینی کند')
        self.assertNotContains(detail, 'ثبت بازبینی اولیه')
        self.assertEqual(self.client.post(reverse('staff_clinical_review', args=[draft.pk]), self.review_data(draft)).status_code, 403)
        self.client.force_login(self.author)
        self.assertEqual(self.client.post(reverse('staff_clinical_review', args=[draft.pk]), self.review_data(draft)).status_code, 403)
        self.client.force_login(self.reviewer)
        response = self.client.post(reverse('staff_clinical_review', args=[draft.pk]), self.review_data(draft))
        self.assertEqual(response.status_code, 302)
        event = ClinicalDraftReview.objects.get()
        snap = event.review_snapshot
        self.assertEqual(snap['evidence_version'], 1); self.assertEqual(snap['evidence_fingerprint'], evidence_state(draft)['fingerprint'])
        self.assertEqual(snap['evidence_snapshot'][0]['id'], ref.pk)
        self.assertEqual(snap['evidence_snapshot'][0]['recorded_by_id'], self.recorder.pk)
        self.assertEqual(snap['evidence_snapshot'][0]['reference']['reference_published_on'], '2024-01-02')
        self.assertEqual(snap['evidence_snapshot'][0]['reference']['relation'], 'supports')
        self.assertContains(self.detail(draft), 'شناسه ارجاع‌های ثبت‌شده با فهرست فعلی برابر است')
        self.add(draft, data={**self.ref_data, 'reference_title': 'ارجاع متناقض ساختگی', 'relation': 'contradicts'})
        self.assertContains(self.detail(draft), 'شناسه ارجاع‌های ثبت‌شده با فهرست فعلی متفاوت است')
        self.assertEqual(len(event.review_snapshot['evidence_snapshot']), 1)
        self.assertEqual(self.client.post(reverse('staff_clinical_review', args=[draft.pk]), self.review_data(draft, event.pk)).status_code, 302)
        self.assertEqual(len(ClinicalDraftReview.objects.first().review_snapshot['evidence_snapshot']), 2)

    def test_legacy_review_no_backfill_and_direct_empty_compatibility(self):
        draft = self.draft()
        old = ClinicalDraftReview.objects.create(draft=draft, reviewer=self.reviewer, decision='defer', reason='قدیمی ساختگی',
                                                  draft_payload_sha256=draft.payload_sha256, review_snapshot={'author_id': self.author.pk})
        self.client.force_login(self.viewer)
        self.assertContains(self.detail(draft), 'رکورد بازبینی یا تصویر پیش‌نویس ناسازگار است')
        payload = {k: v for k, v in self.review_data(draft, old.pk).items() if k != 'expected_evidence_hash'}
        event = review_draft(actor=self.reviewer, draft_id=draft.pk, **payload)
        self.assertEqual(event.review_snapshot['evidence_snapshot'], [])
        old.refresh_from_db(); self.assertNotIn('evidence_version', old.review_snapshot)

    def test_historical_snapshot_is_visible_and_corruption_fails_closed(self):
        draft = self.draft(); ref, _ = self.add(draft)
        event = review_draft(actor=self.reviewer, draft_id=draft.pk, **self.review_data(draft))
        self.add(draft, data={**self.ref_data, 'reference_title': 'ارجاع جدید ساختگی', 'relation': 'contradicts'})
        self.client.force_login(self.viewer)
        response = self.detail(draft)
        self.assertContains(response, 'تصویر ارجاع‌های تکمیلی هنگام بازبینی')
        self.assertEqual(len(response.context['reviews'][0].evidence_history['items']), 1)
        self.assertEqual(response.context['reviews'][0].evidence_history['items'][0]['id'], ref.pk)
        self.assertContains(response, 'شناسه ارجاع‌های ثبت‌شده با فهرست فعلی متفاوت است')
        for mutated in [
            [],
            {**event.review_snapshot, 'evidence_snapshot': [{'invalid': 'shape'}]},
            {**event.review_snapshot, 'evidence_fingerprint': '0' * 64},
            {**event.review_snapshot, 'evidence_version': True},
            {**event.review_snapshot, 'evidence_snapshot': [{**event.review_snapshot['evidence_snapshot'][0],
                'reference': {**event.review_snapshot['evidence_snapshot'][0]['reference'], 'reference_title': '\u0001'}}]},
        ]:
            with self.subTest(snapshot=ascii(mutated)):
                ClinicalDraftReview.objects.filter(pk=event.pk).update(review_snapshot=mutated)
                response = self.detail(draft)
                self.assertIn(response.context['reviews'][0].technical_status, ('invalid_record', 'invalid_evidence'))
                self.assertNotContains(response, 'تصویر ارجاع‌های تکمیلی هنگام بازبینی')
        ClinicalDraftReview.objects.filter(pk=event.pk).update(review_snapshot=event.review_snapshot)
        ClinicalDraft.objects.filter(pk=draft.pk).update(statement='متن ناسازگار')
        response = self.detail(draft)
        self.assertNotContains(response, 'تصویر ارجاع‌های تکمیلی هنگام بازبینی')

    def test_detail_distinguishes_draft_and_evidence_comparisons_without_chronology(self):
        draft = self.draft()
        review_draft(actor=self.reviewer, draft_id=draft.pk, **self.review_data(draft))
        self.client.force_login(self.viewer)
        response = self.detail(draft)
        self.assertContains(response, 'اثر انگشت پیش‌نویس و شناسه نویسنده با وضعیت فعلی برابرند')
        self.assertContains(response, 'شناسه ارجاع‌های ثبت‌شده با فهرست فعلی برابر است')
        modified = {**draft_data(draft), 'title': 'عنوان متفاوت ساختگی'}
        ClinicalDraft.objects.filter(pk=draft.pk).update(title=modified['title'],
            payload_sha256=fingerprint(modified, None, '', ''))
        response = self.detail(draft)
        self.assertContains(response, 'اثر انگشت پیش‌نویس یا شناسه نویسنده با وضعیت فعلی متفاوت است')
        self.assertContains(response, 'شناسه ارجاع‌های ثبت‌شده با فهرست فعلی برابر است')
        self.assertNotContains(response, 'ارجاع‌های تکمیلی پس از این بازبینی تغییر کرده‌اند')
        self.assert_private(response)
        ClinicalDraft.objects.filter(pk=draft.pk).update(title=draft.title, payload_sha256=draft.payload_sha256,
                                                         author_id=self.recorder.pk)
        self.assertContains(self.detail(draft), 'اثر انگشت پیش‌نویس یا شناسه نویسنده با وضعیت فعلی متفاوت است')

    def test_detail_rejects_incomplete_or_inconsistent_historical_review(self):
        draft = self.draft(); self.add(draft)
        event = review_draft(actor=self.reviewer, draft_id=draft.pk, **self.review_data(draft))
        self.client.force_login(self.viewer)
        original = event.review_snapshot
        partial = {key: value for key, value in original.items() if key != 'evidence_version'}
        ClinicalDraftReview.objects.filter(pk=event.pk).update(review_snapshot=partial)
        response = self.detail(draft)
        self.assertContains(response, 'رکورد بازبینی یا تصویر پیش‌نویس ناسازگار است')
        self.assertNotContains(response, event.reason)
        self.assertNotContains(response, 'تصویر ارجاع‌های تکمیلی هنگام بازبینی')
        self.assertNotContains(response, 'این بازبینی قدیمی')
        ClinicalDraftReview.objects.filter(pk=event.pk).update(review_snapshot=original, reviewer_id=self.recorder.pk)
        response = self.detail(draft)
        self.assertContains(response, 'تصویر ارجاع‌های بازبینی ناسازگار است')
        self.assertNotContains(response, 'تصویر ارجاع‌های تکمیلی هنگام بازبینی')

    def test_missing_reviewer_does_not_hide_review_or_reset_expected_review(self):
        draft = self.draft()
        event = review_draft(actor=self.reviewer, draft_id=draft.pk, **self.review_data(draft))
        self.client.force_login(self.author)
        missing = 2_147_483_000
        try:
            # PostgreSQL's deferred FK allows this corrupt fixture until rollback/restoration.
            ClinicalDraftReview.objects.filter(pk=event.pk).update(reviewer_id=missing)
            response = self.detail(draft)
            self.assertEqual(len(response.context['reviews']), 1)
            self.assertContains(response, 'حساب بازبین در دسترس نیست')
            self.assertNotContains(response, event.reason)
            self.assertNotContains(response, 'تصویر ارجاع‌های تکمیلی هنگام بازبینی')
            self.assertContains(response, f'پیش‌نویس {draft.pk}')
            self.assert_private(response)
            self.client.force_login(self.reviewer)
            response = self.detail(draft)
            self.assertEqual(response.context['review_form'].initial['expected_review'], event.pk)
        finally:
            ClinicalDraftReview.objects.filter(pk=event.pk).update(reviewer_id=self.reviewer.pk)

    def test_supported_missing_evidence_shape_is_not_called_old(self):
        draft = self.draft()
        event = review_draft(actor=self.reviewer, draft_id=draft.pk, **self.review_data(draft))
        legacy = {key: value for key, value in event.review_snapshot.items() if not key.startswith('evidence_')}
        ClinicalDraftReview.objects.filter(pk=event.pk).update(review_snapshot=legacy)
        self.client.force_login(self.viewer)
        response = self.detail(draft)
        self.assertContains(response, 'در ساختار ثبت‌شده تصویر ارجاع‌های تکمیلی وجود ندارد')
        self.assertContains(response, 'این به‌تنهایی قدمت بازبینی را ثابت نمی‌کند')
        self.assertContains(response, 'اثر انگشت پیش‌نویس و شناسه نویسنده با وضعیت فعلی برابرند')
        self.assertNotContains(response, 'تصویر ارجاع‌های تکمیلی هنگام بازبینی')
        event.refresh_from_db()
        self.assertEqual(event.review_snapshot, legacy)

    def test_unavailable_current_evidence_or_draft_does_not_claim_a_match(self):
        draft = self.draft(); ref, _ = self.add(draft)
        event = review_draft(actor=self.reviewer, draft_id=draft.pk, **self.review_data(draft))
        self.client.force_login(self.viewer)
        ClinicalReferenceAssertion.objects.filter(pk=ref.pk).update(reference_title='ناسازگار')
        response = self.detail(draft)
        self.assertContains(response, 'مقایسه ارجاع‌های این بازبینی نامشخص است')
        self.assertNotContains(response, 'شناسه ارجاع‌های ثبت‌شده با فهرست فعلی برابر است')
        self.assertContains(response, 'تصویر ارجاع‌های تکمیلی هنگام بازبینی')
        ClinicalDraft.objects.filter(pk=draft.pk).update(statement='متن ناسازگار')
        response = self.detail(draft)
        self.assertContains(response, 'مقایسه پیش‌نویس این بازبینی نامشخص است')
        self.assertNotContains(response, event.reason)
        self.assertNotContains(response, 'تصویر ارجاع‌های تکمیلی هنگام بازبینی')

    def test_detail_reads_are_not_a_database_snapshot_and_may_miss_aba(self):
        draft = self.draft()
        event = review_draft(actor=self.reviewer, draft_id=draft.pk, **self.review_data(draft))
        self.client.force_login(self.viewer)
        modified = {**draft_data(draft), 'title': 'تغییر هم‌زمان ساختگی'}
        def update_between_reads(instance):
            ClinicalDraft.objects.filter(pk=draft.pk).update(title=modified['title'],
                payload_sha256=fingerprint(modified, None, '', ''))
            return evidence_state(instance)
        with patch('clinical.staff_views.evidence_state', side_effect=update_between_reads):
            response = self.detail(draft)
        self.assertContains(response, 'اثر انگشت پیش‌نویس و شناسه نویسنده با وضعیت فعلی برابرند')
        self.assertContains(response, 'خوانش‌های جداگانه')
        self.assertNotEqual(ClinicalDraft.objects.get(pk=draft.pk).payload_sha256, event.draft_payload_sha256)
        self.assertContains(self.detail(draft), 'اثر انگشت پیش‌نویس یا شناسه نویسنده با وضعیت فعلی متفاوت است')
        ClinicalDraft.objects.filter(pk=draft.pk).update(title=draft.title, payload_sha256=draft.payload_sha256)
        self.assertContains(self.detail(draft), 'اثر انگشت پیش‌نویس و شناسه نویسنده با وضعیت فعلی برابرند')

    def test_detail_checks_only_25_reviews_without_per_review_queries(self):
        draft = self.draft()
        event = review_draft(actor=self.reviewer, draft_id=draft.pk, **self.review_data(draft))
        self.client.force_login(self.viewer)
        self.detail(draft)  # warm app-level state for a fair request comparison
        with CaptureQueriesContext(connection) as first:
            self.detail(draft)
        ClinicalDraftReview.objects.bulk_create([ClinicalDraftReview(draft=draft, reviewer=self.reviewer,
            decision=event.decision, reason=event.reason, draft_payload_sha256=event.draft_payload_sha256,
            review_snapshot=event.review_snapshot) for _ in range(25)])
        with CaptureQueriesContext(connection) as many:
            response = self.detail(draft)
        self.assertEqual(len(first), len(many))
        self.assertEqual(len(response.context['reviews']), 25)
        self.assertEqual(response.content.decode().count('اثر انگشت پیش‌نویس و شناسه نویسنده با وضعیت فعلی برابرند'), 25)
        self.assertContains(response, 'حداکثر ۲۵ بازبینی اخیر نمایش داده می‌شود')

    def test_new_revision_does_not_inherit_additional_evidence(self):
        draft = self.draft(); self.add(draft)
        child = create_draft(actor=self.author, data=self.draft_data, parent_id=draft.pk, expected_parent_hash=draft.payload_sha256,
                             change_reason='نسخه جدید ساختگی برای آزمون')
        self.assertEqual(len(evidence_state(draft)['items']), 1); self.assertEqual(evidence_state(child)['items'], [])
        self.assertNotEqual(evidence_state(draft)['fingerprint'], evidence_state(child)['fingerprint'])
        self.client.force_login(self.viewer)
        self.assertContains(self.detail(child), 'ارجاع تکمیلی ثبت نشده است')

    def test_cap_dedup_and_overlimit_fail_closed(self):
        draft = self.draft()
        for i in range(MAX_REFERENCES): self.add(draft, data={**self.ref_data, 'reference_title': f'ارجاع ساختگی {i}'})
        state = evidence_state(draft); self.assertEqual(len(state['items']), 10)
        same, created = self.add(draft, actor=self.author, data={**self.ref_data, 'reference_title': 'ارجاع ساختگی 0'})
        self.assertFalse(created); self.assertEqual(same.recorded_by, self.recorder)
        with self.assertRaises(DraftConflict): self.add(draft, data={**self.ref_data, 'reference_title': 'ارجاع اضافه ساختگی'})
        extra = {**self.ref_data, 'reference_title': 'داده اضافه خارج از خدمت'}
        ClinicalReferenceAssertion.objects.create(draft=draft, draft_payload_sha256=draft.payload_sha256,
            payload_sha256=reference_fingerprint(extra, draft.pk, draft.payload_sha256), recorded_by=self.recorder, **extra)
        self.assertEqual(evidence_state(draft)['status'], 'over_limit')
        self.client.force_login(self.reviewer); response = self.detail(draft)
        self.assertContains(response, 'ارجاع‌های تکمیلی ناسازگارند یا بیش از سقف‌اند')
        self.assertNotContains(response, 'ارجاع تکمیلی ساختگی')
        with self.assertRaises(DraftConflict):
            review_draft(actor=self.reviewer, draft_id=draft.pk, decision='defer', reason='دلیل ساختگی برای آزمایش',
                         expected_review=0, expected_hash=draft.payload_sha256, expected_evidence_hash=state['fingerprint'])
        self.client.force_login(self.recorder)
        self.assertEqual(self.client.get(reverse('staff_clinical_reference_create', args=[draft.pk])).status_code, 409)

    def test_changed_recorder_changes_set_fingerprint_and_stales_review(self):
        draft = self.draft(); ref, _ = self.add(draft)
        previous = self.review_data(draft)
        ClinicalReferenceAssertion.objects.filter(pk=ref.pk).update(recorded_by=self.author)
        self.assertNotEqual(previous['expected_evidence_hash'], evidence_state(draft)['fingerprint'])
        with self.assertRaises(DraftConflict): review_draft(actor=self.reviewer, draft_id=draft.pk, **previous)
        self.assertEqual(ClinicalDraftReview.objects.count(), 0)

    def test_missing_recorder_does_not_hide_reference_from_integrity_check(self):
        draft = self.draft(); self.add(draft)
        with patch('clinical.evidence.get_user_model') as model:
            model.return_value.objects.in_bulk.return_value = {}
            self.assertEqual(evidence_state(draft)['status'], 'invalid')

    def test_missing_web_fingerprint_is_rejected_even_without_references(self):
        draft = self.draft(); self.client.force_login(self.reviewer)
        payload = self.review_data(draft); payload.pop('expected_evidence_hash')
        response = self.client.post(reverse('staff_clinical_review', args=[draft.pk]), payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(ClinicalDraftReview.objects.count(), 0)

    def test_tampered_references_hide_content_and_block_writes(self):
        draft = self.draft(); ref, _ = self.add(draft); previous = evidence_state(draft)['fingerprint']
        ClinicalReferenceAssertion.objects.filter(pk=ref.pk).update(reference_title='<script>tampered</script>')
        self.assertEqual(evidence_state(draft)['status'], 'invalid')
        self.client.force_login(self.reviewer); response = self.detail(draft)
        self.assertContains(response, 'ارجاع‌های تکمیلی ناسازگارند یا بیش از سقف‌اند')
        self.assertNotContains(response, '<script>tampered</script>'); self.assertNotContains(response, 'ثبت بازبینی اولیه')
        self.assertEqual(self.client.post(reverse('staff_clinical_review', args=[draft.pk]), {
            'decision': 'defer', 'reason': 'دلیل ساختگی برای بررسی بیشتر', 'expected_review': 0,
            'expected_hash': draft.payload_sha256, 'expected_evidence_hash': previous}).status_code, 409)
        self.client.force_login(self.recorder)
        with self.assertRaises(DraftConflict): self.add(draft, expected=previous)
        self.assertEqual(ClinicalDraftReview.objects.count(), 0)

    def test_csrf_escaped_values_no_public_data(self):
        draft = self.draft()
        client = Client(enforce_csrf_checks=True); client.force_login(self.recorder)
        url = reverse('staff_clinical_reference_create', args=[draft.pk])
        payload = self.form_data(draft, {**self.ref_data, 'reference_title': '<script>alert(1)</script>'})
        self.assertEqual(client.post(url, payload).status_code, 403)
        client.get(url); payload['csrfmiddlewaretoken'] = client.cookies['csrftoken'].value
        self.assertEqual(client.post(url, payload).status_code, 302)
        response = client.get(reverse('staff_clinical_detail', args=[draft.pk]))
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;'); self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertNotContains(client.get(reverse('home')), 'ارجاع تکمیلی ساختگی')
        self.assertNotContains(client.get(reverse('sitemap')), '/staff/')
        self.assertEqual(PriceCandidate.objects.count(), 0); self.assertEqual(ProductPresentation.objects.count(), 0)

    def test_database_constraints_and_bad_ids(self):
        draft = self.draft(); ref, _ = self.add(draft)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ClinicalReferenceAssertion.objects.filter(pk=ref.pk).update(relation='approved')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ClinicalReferenceAssertion.objects.create(draft=draft, draft_payload_sha256=draft.payload_sha256,
                payload_sha256=ref.payload_sha256, recorded_by=self.author, **self.ref_data)
        self.assertFalse(Permission.objects.filter(content_type__app_label='clinical', content_type__model='clinicalreferenceassertion').exists())
        with self.assertRaises(DraftError):
            add_reference(actor=self.recorder, draft_id=9223372036854775808, data=self.ref_data,
                          expected_draft_hash='0'*64, expected_evidence_hash='0'*64)
        self.client.force_login(self.recorder)
        response = self.client.get(reverse('staff_clinical_reference_create', args=[9223372036854775808]))
        self.assertEqual(response.status_code, 404); self.assert_private(response)

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_debug_gate(self):
        draft = self.draft(); self.client.force_login(self.recorder)
        for method in [self.client.get, self.client.post]:
            response = method(reverse('staff_clinical_reference_create', args=[draft.pk]))
            self.assertEqual(response.status_code, 404); self.assert_private(response)


class ClinicalEvidenceMigrationTests(TransactionTestCase):
    def test_existing_review_is_not_rewritten(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        old = [('clinical', '0001_initial')]; new = [('clinical', '0002_clinicalreferenceassertion')]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(old); apps = executor.loader.project_state(old).apps
            U = apps.get_model('auth', 'User'); Draft = apps.get_model('clinical', 'ClinicalDraft'); Review = apps.get_model('clinical', 'ClinicalDraftReview')
            author = U.objects.create(username='legacy-author'); reviewer = U.objects.create(username='legacy-reviewer')
            draft = Draft.objects.create(subject='فرضی', audience='patient', title='نمونه', statement='متن ساختگی',
                reference_title='ارجاع ساختگی', reference_url='https://example.org', reference_location='بخش فرضی',
                payload_sha256='a' * 64, author_id=author.pk)
            event = Review.objects.create(draft_id=draft.pk, reviewer_id=reviewer.pk, decision='defer', reason='قدیمی',
                draft_payload_sha256='a' * 64, review_snapshot={'legacy': True})
            executor = MigrationExecutor(connection); executor.migrate(new); apps = executor.loader.project_state(new).apps
            Review = apps.get_model('clinical', 'ClinicalDraftReview'); Reference = apps.get_model('clinical', 'ClinicalReferenceAssertion')
            self.assertEqual(Review.objects.get(pk=event.pk).review_snapshot, {'legacy': True})
            self.assertFalse(Reference.objects.filter(draft_id=draft.pk).exists())
        finally:
            executor = MigrationExecutor(connection); executor.migrate(executor.loader.graph.leaf_nodes())
