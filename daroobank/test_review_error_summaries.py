"""Synthetic source, clinical and identity review error navigation."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from catalog.identity import digest, package_snapshot
from catalog.models import IdentityPackageReview
from catalog.test_identity import build
from clinical.evidence import evidence_state
from clinical.models import ClinicalDraftReview
from clinical.services import create_draft
from sources.models import SourceClaimReview
from sources.services import record_claim


@override_settings(STAFF_PORTAL_ENABLED=True)
class OtherReviewErrorSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('summary-author', is_staff=True)
        cls.reviewer = User.objects.create_user('summary-reviewer', is_staff=True)
        for app, model in (('sources', 'sourceclaim'), ('clinical', 'clinicaldraft'), ('catalog', 'identityworkspace')):
            perms = Permission.objects.filter(content_type__app_label=app)
            cls.author.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'add_{model}', f'review_{model}']))
            cls.reviewer.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'review_{model}']))
        cls.claim, _ = record_claim(actor=cls.author, data=dict(source_name='منبع ساختگی',
            source_url='https://example.org/summary', owner='مالک فرضی', evidence_url='https://example.org/evidence',
            evidence_note='', claims_collection=True, claims_storage=False, claims_publication=False, starts_on=None, expires_on=None))
        cls.draft = create_draft(actor=cls.author, data=dict(subject='موضوع ساختگی', audience='patient',
            title='عنوان ساختگی', statement='متن علمی ساختگی', reference_title='مرجع ساختگی',
            reference_url='https://example.org/reference', reference_location='بخش ساختگی',
            reference_author='', reference_version='', reference_published_on=None, reference_accessed_on=None))
        cls.package = build(cls.author)[-1]

    def cases(self):
        common = dict(decision='defer', reason='دلیل ساختگی برای بازبینی', expected_review='0')
        return (
            ('staff_source_detail', [self.claim.pk], 'staff_source_review', [self.claim.pk], SourceClaimReview,
             {**common, 'expected_hash': self.claim.payload_sha256}),
            ('staff_clinical_detail', [self.draft.pk], 'staff_clinical_review', [self.draft.pk], ClinicalDraftReview,
             {**common, 'expected_hash': self.draft.payload_sha256, 'expected_evidence_hash': evidence_state(self.draft)['fingerprint']}),
            ('staff_identity_detail', ['package', self.package.pk], 'staff_identity_review', [self.package.pk], IdentityPackageReview,
             {**common, 'expected_graph_hash': digest(package_snapshot(self.package))}),
        )

    def test_invalid_visible_and_hidden_fields_have_summary_and_do_not_write(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        for detail, detail_args, review, review_args, model, data in self.cases():
            with self.subTest(domain=detail):
                get = client.get(reverse(detail, args=detail_args))
                self.assertEqual(get.status_code, 200)
                self.assertNotContains(get, 'id="staff-form-errors"')
                self.assertNotContains(get, 'خطا در فرم |')
                url = reverse(review, args=review_args)
                invalid = {**data, 'decision': '', 'reason': 'canary', 'expected_review': 'hidden-canary'}
                self.assertEqual(client.post(url, invalid).status_code, 403)
                response = client.post(url, invalid, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(response.status_code, 400)
                html = response.content.decode()
                summary = html.split('<section id="staff-form-errors"', 1)[1].split('</section>', 1)[0]
                self.assertIn('خطا در فرم |', html)
                self.assertIn('href="#id_decision"', summary)
                self.assertIn('href="#id_reason"', summary)
                self.assertIn('اطلاعات پنهان فرم معتبر نیست', summary)
                self.assertNotIn('canary', summary)
                self.assertNotIn('hidden-canary', summary)
                self.assertNotIn('href="#id_expected_review"', summary)
                self.assertIn('id_reason_error', html)
                self.assertEqual(model.objects.count(), 0)
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')

    def test_stale_conflict_remains_discoverable_without_broken_identity_links(self):
        self.client.force_login(self.reviewer)
        for detail, detail_args, review, review_args, model, data in self.cases():
            with self.subTest(domain=detail):
                response = self.client.post(reverse(review, args=review_args), {**data, 'expected_review': '999'})
                self.assertEqual(response.status_code, 409)
                html = response.content.decode()
                self.assertIn('خطا در فرم |', html)
                summary = html.split('<section id="staff-form-errors"', 1)[1].split('</section>', 1)[0]
                self.assertNotIn('دلیل ساختگی', summary)
                if detail == 'staff_identity_detail':
                    self.assertIn('فرم بازبینی اکنون در دسترس نیست', summary)
                    self.assertNotIn('<a ', summary)
                    self.assertIn('صفحه را دوباره بارگذاری کنید', html)
                    self.assertNotIn('name="reason"', html)
                else:
                    self.assertIn('پیام عمومی زیر را نیز بررسی کنید', summary)
                    self.assertIn('صفحه را تازه کنید', html)
                self.assertEqual(model.objects.count(), 0)

    def test_self_review_unavailable_form_does_not_link_or_echo_input(self):
        self.client.force_login(self.author)
        for detail, detail_args, review, review_args, model, data in self.cases():
            with self.subTest(domain=detail):
                response = self.client.post(reverse(review, args=review_args), {**data, 'reason': 'canary'})
                self.assertEqual(response.status_code, 400)
                html = response.content.decode()
                self.assertIn('خطا در فرم |', html)
                self.assertIn('فرم بازبینی اکنون در دسترس نیست', html)
                self.assertNotIn('href="#id_reason"', html)
                self.assertNotIn('canary', html)
                self.assertEqual(model.objects.count(), 0)
