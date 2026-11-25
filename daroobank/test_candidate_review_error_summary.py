"""Selected synthetic product/price review errors are discoverable without echoing values."""
import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from catalog.intake import stage_products
from catalog.models import ProductCandidate, ProductCandidateReview
from catalog.test_intake import make_csv
from pricing.importer import stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.test_workflow import csv_bytes


@override_settings(STAFF_PORTAL_ENABLED=True)
class CandidateReviewErrorSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.stager = get_user_model().objects.create_user('review-summary-author', is_staff=True)
        cls.reviewer = get_user_model().objects.create_user('review-summary-reviewer', is_staff=True)
        for app, model in (('catalog', 'productcandidate'), ('pricing', 'pricecandidate')):
            perms = Permission.objects.filter(content_type__app_label=app)
            cls.stager.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'add_{model}', f'review_{model}']))
            cls.reviewer.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'review_{model}']))
        product = dict(source_record_id='synthetic-product', name_fa='فرآورده ساختگی', name_en='Synthetic',
                       manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        stage_products(io.BytesIO(make_csv([product])), 'منبع ساختگی', 'https://example.org/product',
                       actor=cls.stager, commit=True, rights_attested=True)
        price = dict(source_record_id='synthetic-price', irc='001', manufacturer='سازنده فرضی', strength='1 mg',
                     dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
                     unit='package', effective_date='', source_published_date='')
        stage_csv(io.BytesIO(csv_bytes([price])), 'منبع ساختگی', 'https://example.org/price',
                  staged_by=cls.stager, commit=True, rights_attested=True)
        cls.product = ProductCandidate.objects.get()
        cls.price = PriceCandidate.objects.get()

    def cases(self):
        return (
            ('staff_product_detail', 'staff_product_review', self.product, ProductCandidateReview,
             {'decision': 'defer', 'reason': 'دلیل ساختگی برای بررسی مجدد', 'expected_review': '0', 'expected_hash': self.product.payload_sha256}),
            ('staff_price_detail', 'staff_price_review', self.price, PriceCandidateReview,
             {'decision': 'defer', 'reason': 'دلیل ساختگی برای بررسی مجدد', 'expected_review': '0', 'expected_product': '0', 'expected_product_hash': ''}),
        )

    def test_invalid_visible_and_hidden_fields_have_safe_summary_and_no_write(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        for detail, review, candidate, model, data in self.cases():
            with self.subTest(kind=detail):
                get = client.get(reverse(detail, args=[candidate.pk]))
                self.assertEqual(get.status_code, 200)
                self.assertNotContains(get, 'id="staff-form-errors"')
                self.assertNotContains(get, 'خطا در فرم |')
                url = reverse(review, args=[candidate.pk])
                token = client.cookies['csrftoken'].value
                invalid = {**data, 'decision': '', 'reason': 'canary', 'expected_review': 'hidden-canary'}
                self.assertEqual(client.post(url, invalid).status_code, 403)
                response = client.post(url, invalid, HTTP_X_CSRFTOKEN=token)
                self.assertEqual(response.status_code, 400)
                html = response.content.decode()
                summary = html.split('<section id="staff-form-errors"', 1)[1].split('</section>', 1)[0]
                self.assertIn('خطا در فرم |', html)
                self.assertIn('href="#id_decision"', summary)
                self.assertIn('href="#id_reason"', summary)
                self.assertIn('اطلاعات پنهان فرم معتبر نیست', summary)
                self.assertNotIn('canary', summary)
                self.assertNotIn('href="#id_expected_review"', summary)
                self.assertIn('id_decision_error', html)
                self.assertIn('id_reason_error', html)
                self.assertEqual(model.objects.count(), 0)
                self.assertIn('no-store', response['Cache-Control'])

    def test_stale_review_general_error_is_discoverable_and_retains_status(self):
        self.client.force_login(self.reviewer)
        for detail, review, candidate, model, data in self.cases():
            with self.subTest(kind=detail):
                response = self.client.post(reverse(review, args=[candidate.pk]), {**data, 'expected_review': '999'})
                self.assertEqual(response.status_code, 409)
                html = response.content.decode()
                summary = html.split('<section id="staff-form-errors"', 1)[1].split('</section>', 1)[0]
                self.assertIn('خطا در فرم |', html)
                self.assertIn('پیام عمومی زیر را نیز بررسی کنید', summary)
                self.assertNotIn('دلیل ساختگی', summary)
                self.assertIn('صفحه را تازه کنید', html)
                self.assertEqual(model.objects.count(), 0)

    def test_unavailable_review_form_has_no_broken_error_links(self):
        self.client.force_login(self.stager)
        for detail, review, candidate, model, data in self.cases():
            with self.subTest(kind=detail):
                response = self.client.post(reverse(review, args=[candidate.pk]), {**data, 'reason': 'canary'})
                self.assertEqual(response.status_code, 400)
                html = response.content.decode()
                self.assertIn('خطا در فرم |', html)
                self.assertIn('درخواست انجام نشد؛ فرم بازبینی اکنون در دسترس نیست', html)
                self.assertNotIn('href="#id_reason"', html)
                self.assertNotIn('canary', html)
                self.assertEqual(model.objects.count(), 0)
