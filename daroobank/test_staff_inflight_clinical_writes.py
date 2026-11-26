"""Selected in-flight clinical write boundaries; not global revocation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from clinical.evidence import validate_reference
from clinical.models import ClinicalDraft, ClinicalReferenceAssertion
from clinical.services import validate_data

DRAFT = {'subject': 'موضوع فرضی', 'audience': 'patient', 'title': 'عنوان ساختگی',
         'statement': 'گزاره ساختگی صرفاً برای آزمون', 'reference_title': 'ارجاع فرضی',
         'reference_url': 'https://example.org/reference', 'reference_location': 'بخش فرضی',
         'reference_author': '', 'reference_version': '', 'reference_published_on': '',
         'reference_accessed_on': '', 'synthetic_ack': 'on'}
REFERENCE = {'reference_title': 'ارجاع ساختگی', 'reference_url': 'https://example.org/extra',
             'reference_location': 'بخش ساختگی', 'reference_author': '', 'reference_version': '',
             'reference_published_on': '', 'reference_accessed_on': '', 'relation': 'supports',
             'synthetic_ack': 'on'}


@override_settings(STAFF_PORTAL_ENABLED=True,
                   AUTHENTICATION_BACKENDS=['django.contrib.auth.backends.ModelBackend'],
                   SESSION_ENGINE='django.contrib.sessions.backends.db')
class StaffInflightClinicalWriteTests(TransactionTestCase):
    def setUp(self):
        self.writer = get_user_model().objects.create_user('synthetic-inflight-clinical-writer', password='synthetic-only',
                                                           is_staff=True)
        self.writer.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical'))
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.writer)
        self.assertEqual(self.client.get(reverse('staff_clinical_create')).status_code, 200)

    def token(self):
        return self.client.cookies['csrftoken'].value

    def _paused_post(self, path, payload, target, original, change_account, model):
        ready, resume = Event(), Event()

        def paused(*args, **kwargs):
            # The view's own permission checks have already passed.
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic in-flight clinical write did not resume')
            return original(*args, **kwargs)

        def post_write():
            close_old_connections()
            try:
                return self.client.post(path, payload, HTTP_X_CSRFTOKEN=self.token())
            finally:
                close_old_connections()

        with patch(target, side_effect=paused):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(post_write)
                try:
                    self.assertTrue(ready.wait(10), 'Synthetic clinical write did not reach validation')
                    change_account()
                    self.assertFalse(model.objects.exists())
                finally:
                    resume.set()
                return future.result(timeout=20)

    def invalidate_and_reactivate(self):
        current = get_user_model().objects.get(pk=self.writer.pk)
        current.is_active = False
        current.set_unusable_password()
        current.save(update_fields=['is_active', 'password'])
        get_user_model().objects.filter(pk=self.writer.pk).update(is_active=True)

    def disable_then_reactivate(self):
        current = get_user_model().objects.get(pk=self.writer.pk)
        current.is_active = False
        current.save(update_fields=['is_active'])
        get_user_model().objects.filter(pk=self.writer.pk).update(is_active=True)

    def test_password_invalidation_before_draft_guard_denies_inflight_create(self):
        path = reverse('staff_clinical_create')
        self.assertEqual(self.client.post(path, dict(DRAFT)).status_code, 403)  # CSRF negative control
        self.assertFalse(ClinicalDraft.objects.exists())
        response = self._paused_post(path, dict(DRAFT), 'clinical.services.validate_data', validate_data,
                                     self.invalidate_and_reactivate, ClinicalDraft)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ClinicalDraft.objects.exists())
        fresh = self.client.post(path, dict(DRAFT), HTTP_X_CSRFTOKEN=self.token())
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertFalse(ClinicalDraft.objects.exists())

    def test_flag_only_reactivation_before_draft_guard_can_still_allow_inflight_create(self):
        response = self._paused_post(reverse('staff_clinical_create'), dict(DRAFT), 'clinical.services.validate_data',
                                     validate_data, self.disable_then_reactivate, ClinicalDraft)
        draft = ClinicalDraft.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_clinical_detail', args=[draft.pk]))
        self.assertEqual(draft.author_id, self.writer.pk)

    def reference_payload(self, draft):
        from clinical.evidence import evidence_state
        return {**REFERENCE, 'expected_draft_hash': draft.payload_sha256,
                'expected_evidence_hash': evidence_state(draft)['fingerprint']}

    def test_password_invalidation_before_reference_guard_denies_inflight_create(self):
        self.assertEqual(self.client.post(reverse('staff_clinical_create'), dict(DRAFT),
                                          HTTP_X_CSRFTOKEN=self.token()).status_code, 302)
        draft = ClinicalDraft.objects.get()
        path = reverse('staff_clinical_reference_create', args=[draft.pk])
        payload = self.reference_payload(draft)
        self.assertEqual(self.client.post(path, {k: v for k, v in payload.items() if k != 'synthetic_ack'}).status_code,
                         403)  # CSRF negative control
        self.assertFalse(ClinicalReferenceAssertion.objects.exists())
        response = self._paused_post(path, payload, 'clinical.evidence.validate_reference', validate_reference,
                                     self.invalidate_and_reactivate, ClinicalReferenceAssertion)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ClinicalReferenceAssertion.objects.exists())
        fresh = self.client.post(path, payload, HTTP_X_CSRFTOKEN=self.token())
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertFalse(ClinicalReferenceAssertion.objects.exists())

    def test_flag_only_reactivation_before_reference_guard_can_still_allow_inflight_create(self):
        self.assertEqual(self.client.post(reverse('staff_clinical_create'), dict(DRAFT),
                                          HTTP_X_CSRFTOKEN=self.token()).status_code, 302)
        draft = ClinicalDraft.objects.get()
        path = reverse('staff_clinical_reference_create', args=[draft.pk])
        response = self._paused_post(path, self.reference_payload(draft), 'clinical.evidence.validate_reference',
                                     validate_reference, self.disable_then_reactivate, ClinicalReferenceAssertion)
        assertion = ClinicalReferenceAssertion.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_clinical_detail', args=[draft.pk]))
        self.assertEqual(assertion.recorded_by_id, self.writer.pk)
