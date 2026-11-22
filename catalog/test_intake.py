import csv
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from .intake import FIELDS, MAX_FILE_BYTES, MAX_ROWS, IntakeError, parse_product_csv, stage_products
from .models import ProductCandidate, ProductCandidateReview, ProductPresentation


def make_csv(rows, fields=FIELDS):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode('utf-8')


class ProductIntakeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.submitter = User.objects.create_user('catalog-stager', password='test-only-passphrase', is_staff=True)
        cls.reviewer = User.objects.create_user('catalog-reviewer', password='test-only-passphrase', is_staff=True)
        cls.viewer = User.objects.create_user('catalog-viewer', password='test-only-passphrase', is_staff=True)
        cls.add_only = User.objects.create_user('catalog-add-only', password='test-only-passphrase', is_staff=True)
        cls.regular = User.objects.create_user('catalog-regular', password='test-only-passphrase')
        perms = Permission.objects.filter(content_type__app_label='catalog')
        cls.submitter.user_permissions.add(*perms.filter(codename__in=['view_productcandidate', 'add_productcandidate', 'review_productcandidate']))
        cls.reviewer.user_permissions.add(*perms.filter(codename__in=['view_productcandidate', 'review_productcandidate']))
        cls.viewer.user_permissions.add(perms.get(codename='view_productcandidate'))
        cls.add_only.user_permissions.add(perms.get(codename='add_productcandidate'))
        cls.regular.user_permissions.add(perms.get(codename='view_productcandidate'))
        cls.row = {'source_record_id': 'synthetic-001', 'name_fa': 'فرآورده ساختگی', 'name_en': 'Synthetic',
                   'manufacturer': 'سازنده فرضی', 'strength': '۵ میلی گرم', 'dosage_form': 'قرص',
                   'package_description': '۱۰ عدد', 'irc': '۰۰۱۲۳۴'}

    def submit(self, *, action='stage', rights=True, data=None, source_url='https://example.org/feed'):
        return self.client.post(reverse('staff_product_upload'), {
            'source_name': 'منبع ساختگی', 'source_url': source_url, 'action': action,
            'rights_attested': 'on' if rights else '',
            'csv_file': SimpleUploadedFile('data.csv', data if data is not None else make_csv([self.row]), content_type='text/csv'),
        })

    def stage_one(self):
        self.client.force_login(self.submitter)
        response = self.submit()
        self.assertContains(response, 'هیچ فرآورده‌ای منتشر نشده است')
        return ProductCandidate.objects.get()

    def review_data(self, candidate, decision='further_review', expected_review=0):
        return {'decision': decision, 'reason': 'برای بررسی بیشتر به مدارک مستقل نیاز است.',
                'expected_review': expected_review, 'expected_hash': candidate.payload_sha256}

    def review(self, candidate, data=None):
        return self.client.post(reverse('staff_product_review', args=[candidate.pk]), data or self.review_data(candidate))

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_access_roles_and_anonymous_redirect(self):
        for name in ['staff_products', 'staff_product_upload']:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assert_private(response)
        for user in [self.regular, self.add_only]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(reverse('staff_products')).status_code, 403)
            self.assertEqual(self.client.get(reverse('staff_product_upload')).status_code, 403)
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(reverse('staff_products')).status_code, 200)
        self.assertEqual(self.client.get(reverse('staff_product_upload')).status_code, 403)
        self.assertNotContains(self.client.get(reverse('staff_products')), reverse('staff_product_upload'))
        self.client.force_login(self.reviewer)
        self.assertEqual(self.client.get(reverse('staff_product_upload')).status_code, 403)
        self.client.force_login(self.submitter)
        self.assertContains(self.client.get(reverse('staff_products')), reverse('staff_product_upload'))

    def test_group_permissions_and_product_only_login_redirect(self):
        user = get_user_model().objects.create_user('group-test', password='test-only-passphrase', is_staff=True)
        group = Group.objects.create(name='synthetic-catalog-viewers')
        group.permissions.add(Permission.objects.get(content_type__app_label='catalog', codename='view_productcandidate'))
        user.groups.add(group)
        response = self.client.post(reverse('staff_login'), {'username': 'group-test', 'password': 'test-only-passphrase'})
        self.assertRedirects(response, reverse('staff_products'))
        self.assertEqual(self.client.get(reverse('staff_product_upload')).status_code, 403)

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_disabled_portal(self):
        self.client.force_login(self.submitter)
        for name, args in [('staff_products', []), ('staff_product_upload', []), ('staff_product_detail', [1]), ('staff_product_review', [1])]:
            response = self.client.get(reverse(name, args=args))
            self.assertEqual(response.status_code, 404)
            self.assert_private(response)

    def test_preview_attestation_and_no_publication(self):
        self.client.force_login(self.submitter)
        response = self.submit(action='preview', rights=False)
        self.assertContains(response, 'نتیجه بررسی آزمایشی')
        self.assertEqual(ProductCandidate.objects.count(), 0)
        response = self.submit(rights=False)
        self.assertContains(response, 'برای ثبت داده باید مجوز را تأیید کنید')
        self.assertEqual(ProductCandidate.objects.count(), 0)
        response = self.submit()
        self.assertContains(response, 'رکورد جدید: 1')
        candidate = ProductCandidate.objects.get()
        self.assertEqual(candidate.staged_by, self.submitter)
        self.assertTrue(candidate.source_rights_attested)
        self.assertEqual(ProductPresentation.objects.count(), 0)
        self.assertNotContains(self.client.get(reverse('search'), {'q': 'فرآورده ساختگی'}), 'Synthetic')
        self.assertEqual(self.client.get(reverse('search_api'), {'q': 'فرآورده ساختگی'}).json()['data'], [])
        self.assertNotContains(self.client.get(reverse('sitemap')), '/staff/')

    def test_service_requires_actor_permissions_and_boolean_attestation(self):
        for actor in [self.viewer, self.add_only, self.regular, self.reviewer]:
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                stage_products(io.BytesIO(make_csv([self.row])), 'منبع', 'https://example.org', actor=actor, commit=True, rights_attested=True)
        with self.assertRaises(IntakeError):
            stage_products(io.BytesIO(make_csv([self.row])), 'منبع', 'https://example.org', actor=self.submitter, commit=True, rights_attested='false')
        self.assertEqual(ProductCandidate.objects.count(), 0)

    def test_queue_pagination_and_out_of_range_id(self):
        self.client.force_login(self.submitter)
        rows = [{**self.row, 'source_record_id': f'fake-{i}'} for i in range(25)]
        self.assertEqual(self.submit(data=make_csv(rows)).status_code, 200)
        first = self.client.get(reverse('staff_products'))
        second = self.client.get(reverse('staff_products'), {'page': 2})
        self.assertEqual(len(first.context['page'].object_list), 20)
        self.assertEqual(len(second.context['page'].object_list), 5)
        self.assertContains(first, 'صفحه بعد')
        for name in ['staff_product_detail', 'staff_product_review']:
            response = self.client.get(reverse(name, args=[9223372036854775808])) if name.endswith('detail') else self.client.post(reverse(name, args=[9223372036854775808]))
            self.assertEqual(response.status_code, 404)
            self.assert_private(response)

    def test_dedup_revision_and_original_submitter_remain_unchanged(self):
        candidate = self.stage_one()
        other = get_user_model().objects.create_user('catalog-other', password='test-only-passphrase', is_staff=True)
        other.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog', codename__in=['view_productcandidate', 'add_productcandidate']))
        self.client.force_login(other)
        self.assertContains(self.submit(), 'تکراری: 1')
        candidate.refresh_from_db()
        self.assertEqual(candidate.staged_by, self.submitter)
        changed = {**self.row, 'strength': '۱۰ میلی گرم'}
        self.assertContains(self.submit(data=make_csv([changed])), 'رکورد جدید: 1')
        self.assertEqual(ProductCandidate.objects.count(), 2)
        self.assertEqual(ProductCandidate.objects.get(source_fields__strength='۱۰ میلی گرم').staged_by, other)

    def test_invalid_input_aborts_whole_file_and_avoids_echoing_values(self):
        self.client.force_login(self.submitter)
        invalid_rows = [self.row, {**self.row, 'source_record_id': 'fake-2', 'strength': ''}]
        response = self.submit(data=make_csv(invalid_rows))
        self.assertContains(response, 'ردیف 3')
        self.assertEqual(ProductCandidate.objects.count(), 0)
        for raw in [b'\xff', b'not,csv\na,b', b'"unterminated']:
            self.assertContains(self.submit(data=raw), 'فایل معتبر نیست')
        self.assertContains(self.submit(data=b'x' * (MAX_FILE_BYTES + 1)), 'حجم فایل نباید بیشتر')
        self.assertContains(self.submit(source_url='https://example.org/?secret=hidden'), 'فایل معتبر نیست')
        self.assertEqual(ProductCandidate.objects.count(), 0)
        rows = [{**self.row, 'source_record_id': str(i)} for i in range(MAX_ROWS + 1)]
        with self.assertRaises(IntakeError):
            parse_product_csv(io.BytesIO(make_csv(rows)))
        for field in ['name_fa', 'manufacturer', 'strength', 'dosage_form', 'package_description', 'source_record_id']:
            with self.subTest(field=field), self.assertRaises(IntakeError):
                parse_product_csv(io.BytesIO(make_csv([{**self.row, field: '\u200d'}])))
        with self.assertRaises(IntakeError):
            parse_product_csv(io.BytesIO(make_csv([{**self.row, 'name_fa': 'الف\nب'}])))

    def test_independent_review_history_and_stale_form(self):
        candidate = self.stage_one()
        self.assertEqual(self.review(candidate).status_code, 403)
        self.client.force_login(self.viewer)
        self.assertEqual(self.review(candidate).status_code, 403)
        self.client.force_login(self.reviewer)
        detail = self.client.get(reverse('staff_product_detail', args=[candidate.pk]))
        self.assertContains(detail, 'ثبت بازبینی اولیه')
        self.assert_private(detail)
        self.assertEqual(self.review(candidate).status_code, 302)
        event = ProductCandidateReview.objects.get()
        self.assertEqual(event.reviewer, self.reviewer)
        self.assertEqual(event.candidate_payload_sha256, candidate.payload_sha256)
        self.assertEqual(event.review_snapshot['source_fields'], candidate.source_fields)
        self.assertEqual(self.review(candidate).status_code, 409)
        self.assertEqual(self.review(candidate, self.review_data(candidate, 'reject', event.pk)).status_code, 302)
        self.assertEqual(ProductCandidateReview.objects.count(), 2)
        self.assertEqual(ProductPresentation.objects.count(), 0)
        self.assertContains(self.client.get(reverse('staff_product_detail', args=[candidate.pk])), 'تاریخچه بازبینی')
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()

    def test_queue_filter_uses_latest_review_not_a_public_approval(self):
        candidate = self.stage_one()
        self.client.force_login(self.reviewer)
        self.assertContains(self.client.get(reverse('staff_products'), {'status': 'pending'}), 'فرآورده ساختگی')
        self.assertEqual(self.review(candidate).status_code, 302)
        event = ProductCandidateReview.objects.get()
        self.assertEqual(len(self.client.get(reverse('staff_products'), {'status': 'pending'}).context['page'].object_list), 0)
        self.assertContains(self.client.get(reverse('staff_products'), {'status': 'further_review'}), 'فرآورده ساختگی')
        self.assertEqual(self.review(candidate, self.review_data(candidate, 'defer', event.pk)).status_code, 302)
        self.assertEqual(len(self.client.get(reverse('staff_products'), {'status': 'further_review'}).context['page'].object_list), 0)
        self.assertContains(self.client.get(reverse('staff_products'), {'status': 'defer'}), 'فرآورده ساختگی')
        invalid = self.client.get(reverse('staff_products'), {'status': '<script>'})
        self.assertEqual(invalid.status_code, 400)
        self.assert_private(invalid)
        self.assertEqual(ProductPresentation.objects.count(), 0)

    def test_tampering_and_missing_rights_fail_closed(self):
        candidate = self.stage_one()
        self.client.force_login(self.reviewer)
        for change in [dict(source_rights_attested=False), dict(source_url='https://example.org/other'),
                       dict(source_record_id='modified'), dict(source_fields={'name_fa': 'changed'}), dict(payload_sha256='z' * 64)]:
            with self.subTest(change=change):
                ProductCandidate.objects.filter(pk=candidate.pk).update(**change)
                self.assertEqual(self.review(candidate).status_code, 409)
                ProductCandidate.objects.filter(pk=candidate.pk).update(
                    source_rights_attested=True, source_url=candidate.source_url, source_record_id=candidate.source_record_id,
                    source_fields=candidate.source_fields, payload_sha256=candidate.payload_sha256,
                )
        self.assertEqual(ProductCandidateReview.objects.count(), 0)

    def test_full_csrf_protected_upload_and_review(self):
        stager = Client(enforce_csrf_checks=True)
        stager.force_login(self.submitter)
        upload_url = reverse('staff_product_upload')
        stager.get(upload_url)
        response = stager.post(upload_url, {
            'csrfmiddlewaretoken': stager.cookies['csrftoken'].value, 'source_name': 'منبع ساختگی',
            'source_url': 'https://example.org/feed', 'action': 'stage', 'rights_attested': 'on',
            'csv_file': SimpleUploadedFile('synthetic.csv', make_csv([self.row])),
        })
        self.assertEqual(response.status_code, 200)
        candidate = ProductCandidate.objects.get()
        reviewer = Client(enforce_csrf_checks=True)
        reviewer.force_login(self.reviewer)
        reviewer.get(reverse('staff_product_detail', args=[candidate.pk]))
        data = self.review_data(candidate)
        data['csrfmiddlewaretoken'] = reviewer.cookies['csrftoken'].value
        self.assertEqual(reviewer.post(reverse('staff_product_review', args=[candidate.pk]), data).status_code, 302)
        self.assertEqual(ProductCandidateReview.objects.count(), 1)
        self.assertEqual(ProductPresentation.objects.count(), 0)

    def test_checked_in_synthetic_csv_is_valid_for_preview(self):
        from pathlib import Path
        self.client.force_login(self.submitter)
        data = Path('examples/product_candidates.synthetic.csv').read_bytes()
        self.assertContains(self.submit(action='preview', rights=False, data=data), 'ردیف‌ها: 2')
        self.assertFalse(ProductCandidate.objects.exists())

    def test_changed_hash_cannot_bypass_an_old_form(self):
        from .intake import fingerprint
        candidate = self.stage_one()
        self.client.force_login(self.reviewer)
        old_form = self.review_data(candidate)
        changed = {**candidate.source_fields, 'strength': '۲۰ میلی گرم'}
        ProductCandidate.objects.filter(pk=candidate.pk).update(
            source_fields=changed, payload_sha256=fingerprint(candidate.source_name, candidate.source_url, changed),
        )
        self.assertEqual(self.review(candidate, old_form).status_code, 409)
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_csrf_escaping_and_error_rollback(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.submitter)
        self.assertEqual(client.post(reverse('staff_product_upload'), {}).status_code, 403)
        candidate = self.stage_one()
        client.force_login(self.reviewer)
        self.assertEqual(client.post(reverse('staff_product_review', args=[candidate.pk]), self.review_data(candidate)).status_code, 403)
        self.client.force_login(self.reviewer)
        with patch('catalog.intake.ProductCandidateReview.objects.create', side_effect=RuntimeError('test')):
            with self.assertRaises(RuntimeError):
                self.review(candidate)
        self.assertEqual(ProductCandidateReview.objects.count(), 0)
        data = self.review_data(candidate, 'defer')
        data['reason'] = '<script>alert(1)</script> بررسی آزمایشی'
        self.assertEqual(self.review(candidate, data).status_code, 302)
        response = self.client.get(reverse('staff_product_detail', args=[candidate.pk]))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')
        self.assertEqual(self.client.get(reverse('staff_product_review', args=[candidate.pk])).status_code, 405)
