"""Synthetic source and clinical triage validation at web/service boundaries."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from clinical.evidence import evidence_state
from clinical.models import ClinicalDraftReview
from clinical.services import DraftConflict, create_draft, review_draft
from sources.models import SourceClaimReview
from sources.services import ReviewConflict, record_claim, review_claim

MAX_PK = 9_223_372_036_854_775_807


@override_settings(STAFF_PORTAL_ENABLED=True)
class TriageInputBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('boundary-author', is_staff=True)
        cls.reviewer = User.objects.create_user('boundary-reviewer', is_staff=True)
        cls.viewer = User.objects.create_user('boundary-viewer', is_staff=True)
        for app, entity in [('sources', 'sourceclaim'), ('clinical', 'clinicaldraft')]:
            permissions = Permission.objects.filter(content_type__app_label=app)
            cls.author.user_permissions.add(*permissions.filter(codename__in=[f'view_{entity}', f'add_{entity}']))
            cls.reviewer.user_permissions.add(*permissions.filter(codename__in=[f'view_{entity}', f'review_{entity}']))
            cls.viewer.user_permissions.add(permissions.get(codename=f'view_{entity}'))
        cls.claim = record_claim(actor=cls.author, data=dict(source_name='منبع ساختگی',
            source_url='https://example.org/source', owner='مالک فرضی', evidence_url='https://example.org/evidence',
            evidence_note='', claims_collection=True, claims_storage=False, claims_publication=False,
            starts_on=None, expires_on=None))[0]
        cls.draft = create_draft(actor=cls.author, data=dict(subject='موضوع فرضی', audience='patient',
            title='عنوان ساختگی', statement='گزاره ساختگی صرفاً برای آزمون', reference_title='ارجاع فرضی',
            reference_url='https://example.org/reference', reference_location='بخش فرضی', reference_author='',
            reference_version='', reference_published_on=None, reference_accessed_on=None))

    def cases(self):
        common = dict(decision='defer', reason='این متن ساختگی برای بررسی اولیه است.', expected_review=0)
        return [
            ('source', review_claim, ReviewConflict, SourceClaimReview, 'claim_id', self.claim.pk,
             {**common, 'expected_hash': self.claim.payload_sha256}, 'staff_source_review'),
            ('clinical', review_draft, DraftConflict, ClinicalDraftReview, 'draft_id', self.draft.pk,
             {**common, 'expected_hash': self.draft.payload_sha256,
              'expected_evidence_hash': evidence_state(self.draft)['fingerprint']}, 'staff_clinical_review'),
        ]

    def test_invalid_inputs_are_rejected_before_db_and_after_permission(self):
        for domain, service, conflict, model, id_name, pk, form, _ in self.cases():
            self.reviewer.has_perm(f'{"sources.view_sourceclaim" if domain == "source" else "clinical.view_clinicaldraft"}')
            args = {'actor': self.reviewer, id_name: pk, **form}
            bad = [(id_name, value) for value in (True, False, 0, -1, MAX_PK + 1, '1', None, [])]
            bad += [('expected_review', value) for value in (True, False, -1, MAX_PK + 1, '0', None, [])]
            bad += [('decision', value) for value in ([], {}, None, 1, 'invalid')]
            bad += [('expected_hash', value) for value in (None, [], '0' * 63, 'A' * 64)]
            if domain == 'clinical':
                bad += [('expected_evidence_hash', value) for value in ([], 1, '0' * 63, 'A' * 64)]
            for field, value in bad:
                with self.subTest(domain=domain, field=field, value=value):
                    with CaptureQueriesContext(connection) as queries:
                        with self.assertRaises(conflict):
                            service(**(args | {field: value}))
                    self.assertEqual(len(queries), 0)
            for actor in (None, self.viewer):
                with self.subTest(domain=domain, actor=actor), self.assertRaises(PermissionDenied):
                    service(**(args | {'actor': actor, id_name: MAX_PK + 1, 'decision': []}))
            self.assertFalse(model.objects.exists())

    def test_web_rejects_out_of_range_review_before_service(self):
        self.client.force_login(self.reviewer)
        for domain, _, _, model, _, pk, form, route in self.cases():
            for value in (-1, MAX_PK + 1):
                with self.subTest(domain=domain, value=value):
                    response = self.client.post(reverse(route, args=[pk]), {**form, 'expected_review': value})
                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                    self.assertEqual(response['Referrer-Policy'], 'same-origin')
                    detail = 'staff_source_detail' if domain == 'source' else 'staff_clinical_detail'
                    self.assertContains(response, 'بازگشت به جزئیات و شروع دوباره', status_code=400)
                    self.assertContains(response, f'href="{reverse(detail, args=[pk])}"', status_code=400)
                    self.assertContains(response, 'role="alert"', status_code=400)
                    self.assertFalse(model.objects.exists())
            detail_name = 'staff_source_detail' if domain == 'source' else 'staff_clinical_detail'
            detail_response = self.client.get(reverse(detail_name, args=[pk]))
            self.assertContains(detail_response, 'فقط شناسه آخرین بازبینی موجود بررسی می‌شود')
            if domain == 'clinical':
                self.assertContains(detail_response, 'تغییر هم‌زمان یا بعدی ارجاع‌ها')
            else:
                self.assertContains(detail_response, 'تغییر هم‌زمان یا بعدی تاریخچه همچنان ممکن است')
            # Max bigint is syntactically valid but stale; zero is valid for no review.
            stale = self.client.post(reverse(route, args=[pk]), {**form, 'expected_review': MAX_PK})
            self.assertEqual(stale.status_code, 409)
            self.assertFalse(model.objects.exists())
            accepted = self.client.post(reverse(route, args=[pk]), form)
            self.assertEqual(accepted.status_code, 302)
            self.assertEqual(model.objects.count(), 1)
