"""Selected in-flight price/clinical review boundaries; not global revocation."""
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from clinical.evidence import evidence_state
from clinical.models import ClinicalDraftReview
from clinical.services import create_draft
from clinical.services import valid_review_reason as draft_reason
from pricing.importer import stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import valid_review_reason as price_reason
from pricing.test_workflow import csv_bytes

PRICE = dict(source_record_id='one', irc='001', manufacturer='سازنده فرضی', strength='5 mg',
             dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
             category='retail', unit='package', effective_date='', source_published_date='')
DRAFT = {'subject': 'موضوع فرضی', 'audience': 'patient', 'title': 'عنوان ساختگی',
         'statement': 'گزاره ساختگی صرفاً برای آزمون', 'reference_title': 'ارجاع فرضی',
         'reference_url': 'https://example.org/reference', 'reference_location': 'بخش فرضی',
         'reference_author': '', 'reference_version': '', 'reference_published_on': None,
         'reference_accessed_on': None}
REASON = 'دلیل ساختگی برای بررسی اولیه'


@override_settings(STAFF_PORTAL_ENABLED=True,
                   AUTHENTICATION_BACKENDS=['django.contrib.auth.backends.ModelBackend'],
                   SESSION_ENGINE='django.contrib.sessions.backends.db')
class StaffInflightReviewWriteTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user('synthetic-inflight-author', password='synthetic-only', is_staff=True)
        self.reviewer = User.objects.create_user('synthetic-inflight-reviewer', password='synthetic-only', is_staff=True)
        for user, app in ((self.author, 'pricing'), (self.reviewer, 'pricing'),
                          (self.author, 'clinical'), (self.reviewer, 'clinical')):
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label=app))
        stage_csv(io.BytesIO(csv_bytes([PRICE])), 'منبع ساختگی', 'https://example.org/price',
                  staged_by=self.author, commit=True, rights_attested=True)
        self.candidate = PriceCandidate.objects.get()
        self.draft = create_draft(actor=self.author, data=dict(DRAFT))

    def reviewer_client(self, detail_route, pk):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        self.assertEqual(client.get(reverse(detail_route, args=[pk])).status_code, 200)
        return client

    def price_payload(self):
        return {'decision': PriceCandidateReview.DEFER, 'reason': REASON, 'expected_review': 0,
                'expected_product': 0, 'expected_product_hash': ''}

    def draft_payload(self):
        return {'decision': ClinicalDraftReview.DECISIONS[0][0], 'reason': REASON, 'expected_review': 0,
                'expected_hash': self.draft.payload_sha256,
                'expected_evidence_hash': evidence_state(self.draft)['fingerprint']}

    def _paused_post(self, client, path, payload, target, original, change_account, reviews):
        """Park one CSRF-valid review POST inside service input validation."""
        ready, resume = Event(), Event()

        def paused(*args, **kwargs):
            # The view's own permission checks have already passed.
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic in-flight review did not resume')
            return original(*args, **kwargs)

        def post_review():
            close_old_connections()
            try:
                return client.post(path, payload, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
            finally:
                close_old_connections()

        with patch(target, side_effect=paused):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(post_review)
                try:
                    self.assertTrue(ready.wait(10), 'Synthetic review did not reach input validation')
                    change_account()
                    self.assertFalse(reviews.objects.exists())
                finally:
                    resume.set()
                return future.result(timeout=20)

    def invalidate_and_reactivate(self):
        current = get_user_model().objects.get(pk=self.reviewer.pk)
        current.is_active = False
        current.set_unusable_password()
        current.save(update_fields=['is_active', 'password'])
        get_user_model().objects.filter(pk=self.reviewer.pk).update(is_active=True)

    def disable_then_reactivate(self):
        current = get_user_model().objects.get(pk=self.reviewer.pk)
        current.is_active = False
        current.save(update_fields=['is_active'])
        get_user_model().objects.filter(pk=self.reviewer.pk).update(is_active=True)

    def test_password_invalidation_before_price_review_guard_denies_inflight_review(self):
        client = self.reviewer_client('staff_price_detail', self.candidate.pk)
        path = reverse('staff_price_review', args=[self.candidate.pk])
        payload = self.price_payload()
        self.assertEqual(client.post(path, payload).status_code, 403)  # CSRF negative control
        self.assertFalse(PriceCandidateReview.objects.exists())
        response = self._paused_post(client, path, payload, 'pricing.reviews.valid_review_reason', price_reason,
                                     self.invalidate_and_reactivate, PriceCandidateReview)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PriceCandidateReview.objects.exists())
        fresh = client.post(path, payload, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertEqual(PriceCandidateReview.objects.count(), 0)

    def test_flag_only_reactivation_before_price_review_guard_can_still_allow_inflight_review(self):
        client = self.reviewer_client('staff_price_detail', self.candidate.pk)
        path = reverse('staff_price_review', args=[self.candidate.pk])
        payload = self.price_payload()
        response = self._paused_post(client, path, payload, 'pricing.reviews.valid_review_reason', price_reason,
                                     self.disable_then_reactivate, PriceCandidateReview)
        event = PriceCandidateReview.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_price_detail', args=[self.candidate.pk]))
        self.assertEqual(event.reviewer_id, self.reviewer.pk)

    def test_password_invalidation_before_clinical_review_guard_denies_inflight_review(self):
        client = self.reviewer_client('staff_clinical_detail', self.draft.pk)
        path = reverse('staff_clinical_review', args=[self.draft.pk])
        payload = self.draft_payload()
        self.assertEqual(client.post(path, payload).status_code, 403)  # CSRF negative control
        self.assertFalse(ClinicalDraftReview.objects.exists())
        response = self._paused_post(client, path, payload, 'clinical.services.valid_review_reason', draft_reason,
                                     self.invalidate_and_reactivate, ClinicalDraftReview)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ClinicalDraftReview.objects.exists())
        fresh = client.post(path, payload, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertEqual(ClinicalDraftReview.objects.count(), 0)

    def test_flag_only_reactivation_before_clinical_review_guard_can_still_allow_inflight_review(self):
        client = self.reviewer_client('staff_clinical_detail', self.draft.pk)
        path = reverse('staff_clinical_review', args=[self.draft.pk])
        payload = self.draft_payload()
        response = self._paused_post(client, path, payload, 'clinical.services.valid_review_reason', draft_reason,
                                     self.disable_then_reactivate, ClinicalDraftReview)
        event = ClinicalDraftReview.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_clinical_detail', args=[self.draft.pk]))
        self.assertEqual(event.reviewer_id, self.reviewer.pk)
