import csv
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from catalog.models import ProductPresentation
from .importer import FIELDS, ImportValidationError, stage_csv
from .models import PriceCandidate, PriceCandidateReview
from .reviews import MAX_PK, ReviewConflict, product_fingerprint, record_preliminary_review


def csv_bytes(rows):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


class PriceWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.stager = User.objects.create_user('stager', password='test-only-long-password', is_staff=True)
        cls.reviewer = User.objects.create_user('reviewer', password='test-only-long-password', is_staff=True)
        cls.viewer = User.objects.create_user('viewer2', password='test-only-long-password', is_staff=True)
        cls.only_add = User.objects.create_user('only-add', password='test-only-long-password', is_staff=True)
        cls.stager.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing', codename__in=['view_pricecandidate', 'add_pricecandidate', 'review_pricecandidate']))
        cls.reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing', codename__in=['view_pricecandidate', 'review_pricecandidate']))
        cls.viewer.user_permissions.add(Permission.objects.get(content_type__app_label='pricing', codename='view_pricecandidate'))
        cls.only_add.user_permissions.add(Permission.objects.get(content_type__app_label='pricing', codename='add_pricecandidate'))
        cls.product = ProductPresentation.objects.create(
            name_fa='فرآورده ساختگی', manufacturer='شرکت فرضی', strength='۵ میلی گرم',
            dosage_form='قرص', package_description='۱۰ عدد', irc='0000123',
            source_name='نمونه', source_url='https://example.org/product',
        )
        cls.row = dict(source_record_id='fake-001', irc='۰۰۰۰۱۲۳', manufacturer='شركت فرضی',
                       strength='5 میلی گرم', dosage_form='قرص', package_description='10 عدد',
                       amount='۱۲۳٫۵', currency='TOMAN', category='retail', unit='package',
                       effective_date='2026-01-02', source_published_date='')

    def upload(self, action='stage', rights=True, rows=None):
        return self.client.post(reverse('staff_price_upload'), {
            'source_name': 'منبع ساختگی', 'source_url': 'https://example.org/feed', 'action': action,
            'rights_attested': 'on' if rights else '',
            'csv_file': SimpleUploadedFile('synthetic.csv', csv_bytes(rows or [self.row]), content_type='text/csv'),
        })

    def stage_one(self):
        self.client.force_login(self.stager)
        response = self.upload()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'هیچ قیمتی منتشر نشده است')
        return PriceCandidate.objects.get()

    def payload(self, candidate, decision='accept_suggestion', expected_review=0):
        return {
            'decision': decision, 'reason': 'این نتیجه صرفاً یک بررسی آزمایشی است.',
            'expected_review': expected_review, 'expected_product': self.product.pk,
            'expected_product_hash': product_fingerprint(self.product),
        }

    def review(self, candidate, **payload):
        return self.client.post(reverse('staff_price_review', args=[candidate.pk]), payload or self.payload(candidate))

    def test_upload_requires_staff_and_both_permissions(self):
        self.assertEqual(self.client.get(reverse('staff_price_upload')).status_code, 302)
        for user in [self.viewer, self.reviewer, self.only_add]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('staff_price_upload')).status_code, 403)
            self.client.logout()
        self.client.force_login(self.stager)
        self.assertContains(self.client.get(reverse('staff_prices')), reverse('staff_price_upload'))

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_upload_and_review_disabled_without_portal(self):
        self.client.force_login(self.stager)
        self.assertEqual(self.client.get(reverse('staff_price_upload')).status_code, 404)
        self.assertEqual(self.client.post(reverse('staff_price_review', args=[1])).status_code, 404)

    def test_preview_and_attestation_gate(self):
        self.client.force_login(self.stager)
        response = self.upload(action='preview', rights=False)
        self.assertContains(response, 'نتیجه بررسی آزمایشی')
        self.assertEqual(PriceCandidate.objects.count(), 0)
        response = self.upload(rights=False)
        self.assertContains(response, 'برای ثبت داده باید مجوز را تأیید کنید')
        self.assertEqual(PriceCandidate.objects.count(), 0)
        with self.assertRaises(ImportValidationError):
            stage_csv(io.BytesIO(csv_bytes([self.row])), 'نمونه', 'https://example.org', commit=True)

    def test_import_review_history_and_no_public_price(self):
        candidate = self.stage_one()
        self.assertEqual(candidate.staged_by, self.stager)
        self.assertTrue(candidate.source_rights_attested)
        self.assertEqual(candidate.amount_rial, 1235)
        self.assertEqual(self.review(candidate).status_code, 403)  # user cannot review own input
        self.client.force_login(self.reviewer)
        detail = self.client.get(reverse('staff_price_detail', args=[candidate.pk]))
        self.assertContains(detail, 'ثبت بازبینی اولیه')
        self.assertContains(detail, 'این بازبینی تضمین یکتایی نیست')
        self.assertContains(detail, 'فقط شناسه آخرین بازبینی موجود بررسی می‌شود')
        self.assertContains(detail, 'تغییر هم‌زمان یا بعدی تاریخچه همچنان ممکن است')
        self.assertEqual(self.review(candidate).status_code, 302)
        event = PriceCandidateReview.objects.get()
        self.assertEqual(event.reviewer, self.reviewer)
        self.assertEqual(event.reviewed_product, self.product)
        self.assertEqual(event.candidate_payload_sha256, candidate.payload_sha256)
        self.assertEqual(event.review_snapshot['source_record_id'], 'fake-001')
        self.assertEqual(event.review_snapshot['product']['id'], self.product.pk)
        self.assertEqual(event.product_identity_sha256, product_fingerprint(self.product))
        self.assertEqual(self.review(candidate).status_code, 409)  # stale version
        second = self.payload(candidate, decision='defer', expected_review=event.pk)
        self.assertEqual(self.review(candidate, **second).status_code, 302)
        self.assertEqual(PriceCandidateReview.objects.count(), 2)
        self.assertContains(self.client.get(reverse('staff_price_detail', args=[candidate.pk])), 'تاریخچه بازبینی')
        self.assertNotContains(self.client.get(reverse('prices')), '1235')
        self.assertNotIn('amount_rial', str(self.client.get(reverse('search_api'), {'q': '0000123'}).json()))
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_view_only_and_missing_stager_have_no_review_authority(self):
        candidate = self.stage_one()
        self.client.force_login(self.viewer)
        self.assertEqual(self.review(candidate).status_code, 403)
        self.client.force_login(self.reviewer)
        PriceCandidate.objects.filter(pk=candidate.pk).update(staged_by=None)
        detail = self.client.get(reverse('staff_price_detail', args=[candidate.pk]))
        self.assertContains(detail, 'ثبت‌کننده احرازشده ندارد')
        self.assertEqual(self.review(candidate).status_code, 409)
        self.assertEqual(PriceCandidateReview.objects.count(), 0)

    def test_changed_product_and_tampered_candidate_fail_closed(self):
        candidate = self.stage_one()
        self.client.force_login(self.reviewer)
        stale = self.payload(candidate)
        self.product.strength = 'دوز متفاوت'
        self.product.save(update_fields=['strength'])
        self.assertEqual(self.review(candidate, **stale).status_code, 409)
        self.product.strength = '۵ میلی گرم'
        self.product.save(update_fields=['strength'])
        PriceCandidate.objects.filter(pk=candidate.pk).update(amount_rial=9999)
        self.assertEqual(self.review(candidate).status_code, 409)
        self.assertEqual(PriceCandidateReview.objects.count(), 0)

    def test_missing_rights_and_ambiguous_match_fail_closed(self):
        candidate = self.stage_one()
        self.client.force_login(self.reviewer)
        PriceCandidate.objects.filter(pk=candidate.pk).update(source_rights_attested=False)
        self.assertEqual(self.review(candidate).status_code, 409)
        PriceCandidate.objects.filter(pk=candidate.pk).update(source_rights_attested=True)
        ProductPresentation.objects.create(
            name_fa='نسخه فرضی دوم', manufacturer='شرکت فرضی', strength='۵ میلی گرم',
            dosage_form='قرص', package_description='۱۰ عدد', irc='0000123',
            source_name='نمونه', source_url='https://example.org/product',
        )
        self.assertEqual(self.review(candidate).status_code, 409)
        self.assertEqual(PriceCandidateReview.objects.count(), 0)
        # Deferring an ambiguous candidate does not imply a successful match.
        self.assertEqual(self.review(candidate, **self.payload(candidate, decision='defer')).status_code, 302)
        self.assertIsNone(PriceCandidateReview.objects.get().reviewed_product)

    def test_review_needs_explicit_decision_and_private_error_headers(self):
        candidate = self.stage_one()
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse('staff_price_review', args=[candidate.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        payload = self.payload(candidate, decision='')
        response = self.review(candidate, **payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(PriceCandidateReview.objects.count(), 0)

    def test_review_ids_are_bounded_and_service_rejects_invalid_types(self):
        candidate = self.stage_one()
        self.client.force_login(self.reviewer)
        for field in ('expected_review', 'expected_product'):
            for value in (-1, MAX_PK + 1):
                with self.subTest(field=field, value=value):
                    payload = self.payload(candidate)
                    payload[field] = value
                    response = self.review(candidate, **payload)
                    self.assertEqual(response.status_code, 400)
                    self.assertIn('no-store', response['Cache-Control'])
        args = dict(candidate_id=candidate.pk, actor=self.reviewer, decision='defer',
                    reason='این نتیجه صرفاً یک بررسی آزمایشی است.', expected_review=0,
                    expected_product=0, expected_product_hash='')
        for field, value in [('candidate_id', True), ('candidate_id', 0), ('candidate_id', MAX_PK + 1),
                             ('expected_review', True), ('expected_review', MAX_PK + 1),
                             ('expected_product', False), ('expected_product', MAX_PK + 1),
                             ('decision', []), ('expected_product_hash', None)]:
            with self.subTest(field=field, value=value), self.assertRaises(ReviewConflict):
                record_preliminary_review(**(args | {field: value}))
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_invalid_hidden_fingerprint_and_source_mutation_are_rejected(self):
        candidate = self.stage_one()
        self.client.force_login(self.reviewer)
        payload = self.payload(candidate)
        payload['expected_product_hash'] = 'غیرمجاز'
        self.assertEqual(self.review(candidate, **payload).status_code, 400)
        changed = dict(candidate.source_fields)
        changed['source_record_id'] = 'rewritten'
        PriceCandidate.objects.filter(pk=candidate.pk).update(source_fields=changed)
        self.assertEqual(self.review(candidate).status_code, 409)
        self.assertEqual(PriceCandidateReview.objects.count(), 0)

    def test_invalid_file_is_atomic_and_no_extra_data_is_stored(self):
        self.client.force_login(self.stager)
        bad = {**self.row, 'source_record_id': 'fake-002', 'currency': 'UNKNOWN'}
        response = self.upload(rows=[self.row, bad])
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'فایل معتبر نیست')
        self.assertEqual(PriceCandidate.objects.count(), 0)
        oversized = SimpleUploadedFile('big.csv', b'a' * (2 * 1024 * 1024 + 1), content_type='text/csv')
        response = self.client.post(reverse('staff_price_upload'), {
            'source_name': 'نمونه', 'source_url': 'https://example.org', 'action': 'stage',
            'rights_attested': 'on', 'csv_file': oversized,
        })
        self.assertContains(response, 'حجم فایل نباید بیشتر از ۲ مگابایت باشد')
        self.assertEqual(PriceCandidate.objects.count(), 0)

    def test_duplicate_does_not_change_actor_or_attestation(self):
        candidate = self.stage_one()
        another = get_user_model().objects.create_user('another', password='test-only-long-password', is_staff=True)
        another.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing', codename__in=['view_pricecandidate', 'add_pricecandidate']))
        self.client.force_login(another)
        response = self.upload()
        self.assertContains(response, 'تکراری: 1')
        candidate.refresh_from_db()
        self.assertEqual(candidate.staged_by, self.stager)
        self.assertEqual(PriceCandidate.objects.count(), 1)

    def test_csrf_prevents_upload_and_review_and_escaped_reason(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.stager)
        self.assertEqual(client.post(reverse('staff_price_upload'), {}).status_code, 403)
        candidate = self.stage_one()
        client.force_login(self.reviewer)
        self.assertEqual(client.post(reverse('staff_price_review', args=[candidate.pk]), self.payload(candidate)).status_code, 403)
        self.client.force_login(self.reviewer)
        payload = self.payload(candidate, decision='reject')
        payload['reason'] = '<script>alert("test")</script> توضیح ساختگی'
        self.assertEqual(self.review(candidate, **payload).status_code, 302)
        response = self.client.get(reverse('staff_price_detail', args=[candidate.pk]))
        self.assertNotContains(response, '<script>alert("test")</script>')
        self.assertContains(response, '&lt;script&gt;')

    def test_review_creation_error_does_not_mutate_candidate(self):
        candidate = self.stage_one()
        self.client.force_login(self.reviewer)
        with patch('pricing.reviews.PriceCandidateReview.objects.create', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.review(candidate)
        candidate.refresh_from_db()
        self.assertEqual(candidate.amount_rial, 1235)
        self.assertEqual(PriceCandidateReview.objects.count(), 0)
