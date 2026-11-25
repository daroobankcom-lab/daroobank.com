"""Synthetic staff detail must not offer a current match for an inconsistent payload."""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import ProductPresentation
from .importer import stage_csv, suggest_product
from .models import PriceCandidate, PriceCandidateReview
from .test_workflow import csv_bytes


@override_settings(STAFF_PORTAL_ENABLED=True)
class PriceDetailPayloadStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.stager = User.objects.create_user('detail-payload-stager', is_staff=True)
        cls.reviewer = User.objects.create_user('detail-payload-reviewer', is_staff=True)
        cls.stager.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
            codename__in=['view_pricecandidate', 'add_pricecandidate']))
        cls.reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
            codename__in=['view_pricecandidate', 'review_pricecandidate']))
        cls.product = ProductPresentation.objects.create(name_fa='نام پیشنهاد ساختگی', manufacturer='سازنده فرضی',
            strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001',
            source_name='منبع ساختگی', source_url='https://example.org/product')
        cls.row = dict(source_record_id='test', irc='001', manufacturer='سازنده فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
            unit='package', effective_date='', source_published_date='')
        stage_csv(io.BytesIO(csv_bytes([cls.row])), 'منبع ساختگی', 'https://example.org/feed',
                  commit=True, rights_attested=True, staged_by=cls.stager)
        cls.candidate = PriceCandidate.objects.get()

    def setUp(self):
        self.client.force_login(self.reviewer)
        self.url = reverse('staff_price_detail', args=[self.candidate.pk])

    def test_inconsistent_amount_disables_current_match_and_review_form(self):
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(amount_rial=101)
        with patch('pricing.staff_views.suggest_product', wraps=suggest_product) as match:
            response = self.client.get(self.url)
        self.assertContains(response, 'اطلاعات نامعتبر')
        self.assertContains(response, 'اطلاعات این رکورد ناسازگار است')
        self.assertNotContains(response, 'نام پیشنهاد ساختگی')
        self.assertNotContains(response, 'name="decision"')
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        match.assert_not_called()
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_inconsistent_identity_and_amount_are_not_rendered_in_detail(self):
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(
            source_fields={**self.row, 'manufacturer': 'price-identity-canary'},
            original_amount='price-amount-canary', amount_rial=987654321)
        for method in (self.client.get, self.client.head):
            with self.subTest(method=method.__name__):
                response = method(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                for canary in (b'price-identity-canary', b'price-amount-canary', b'987654321'):
                    self.assertNotIn(canary, response.content)
                if method == self.client.get:
                    self.assertContains(response, 'مشخصات و مبلغ ناسازگار نمایش داده نمی‌شوند')
                    self.assertNotContains(response, 'name="decision"')
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_stale_and_malformed_review_responses_suppress_inconsistent_amount(self):
        initial = self.client.get(self.url).context['review_form'].initial
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(original_amount='price-post-canary')
        review_url = reverse('staff_price_review', args=[self.candidate.pk])
        for data, status in (({'decision': 'invalid'}, 400),
                             ({**initial, 'decision': 'defer', 'reason': 'توضیح ساختگی برای بررسی اولیه'}, 409)):
            with self.subTest(status=status):
                response = self.client.post(review_url, data)
                self.assertEqual(response.status_code, status)
                self.assertNotContains(response, 'price-post-canary', status_code=status)
                self.assertContains(response, 'مشخصات و مبلغ ناسازگار نمایش داده نمی‌شوند', status_code=status)
                self.assertNotContains(response, 'name="decision"', status_code=status)
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_changed_fields_hash_and_source_url_each_suppress_current_suggestion(self):
        for update in (dict(payload_sha256='0' * 64),
                       dict(source_fields={**self.row, 'extra': 'synthetic-canary'}),
                       dict(source_url='http://example.org/unsafe')):
            with self.subTest(update=update):
                PriceCandidate.objects.filter(pk=self.candidate.pk).update(**update)
                with patch('pricing.staff_views.suggest_product', wraps=suggest_product) as match:
                    response = self.client.get(self.url)
                self.assertContains(response, 'اطلاعات این رکورد ناسازگار است')
                self.assertContains(response, 'اطلاعات نامعتبر')
                self.assertNotContains(response, 'name="decision"')
                match.assert_not_called()
                PriceCandidate.objects.filter(pk=self.candidate.pk).update(
                    source_fields=self.candidate.source_fields, source_url=self.candidate.source_url,
                    payload_sha256=self.candidate.payload_sha256)

    def test_stale_post_fails_without_new_review_or_current_match(self):
        before = self.client.get(self.url).context['review_form'].initial
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(amount_rial=101)
        response = self.client.post(reverse('staff_price_review', args=[self.candidate.pk]), {
            **before, 'decision': 'accept_suggestion', 'reason': 'توضیح ساختگی برای بررسی اولیه',
        })
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'اطلاعات این رکورد ناسازگار است', status_code=409)
        self.assertNotContains(response, 'name="decision"', status_code=409)
        self.assertNotContains(response, 'نام پیشنهاد ساختگی', status_code=409)
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_in_flight_read_is_not_a_snapshot_or_review_authorization(self):
        def change_after_candidate_fetch(fields):
            PriceCandidate.objects.filter(pk=self.candidate.pk).update(amount_rial=101)
            return suggest_product(fields)
        with patch('pricing.staff_views.suggest_product', side_effect=change_after_candidate_fetch):
            stale = self.client.get(self.url)
        self.assertContains(stale, 'نام پیشنهاد ساختگی')
        self.assertContains(stale, 'name="decision"')
        self.assertNotContains(stale, 'اطلاعات این رکورد ناسازگار است')
        # A later read and the write-side check observe the changed value.
        fresh = self.client.get(self.url)
        self.assertContains(fresh, 'اطلاعات این رکورد ناسازگار است')
        self.assertNotContains(fresh, 'name="decision"')
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_consistent_candidate_keeps_fresh_suggestion_and_review_form(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'نام پیشنهاد ساختگی')
        self.assertContains(response, 'name="decision"')
        self.assertNotContains(response, 'اطلاعات این رکورد ناسازگار است')
