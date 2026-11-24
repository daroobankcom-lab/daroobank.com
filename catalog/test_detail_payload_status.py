"""Synthetic product detail consistency checks are not source verification."""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from .intake import stage_products
from .models import ProductCandidate, ProductCandidateReview
from .test_intake import make_csv


@override_settings(STAFF_PORTAL_ENABLED=True)
class ProductDetailPayloadStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.stager = User.objects.create_user('product-payload-stager', is_staff=True)
        cls.reviewer = User.objects.create_user('product-payload-reviewer', is_staff=True)
        cls.stager.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog',
            codename__in=['view_productcandidate', 'add_productcandidate']))
        cls.reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog',
            codename__in=['view_productcandidate', 'review_productcandidate']))
        cls.row = dict(source_record_id='product-fixture', name_fa='نام ساختگی', name_en='',
            manufacturer='سازنده ساختگی', strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        stage_products(io.BytesIO(make_csv([cls.row])), 'منبع ساختگی', 'https://example.org/feed',
                       actor=cls.stager, commit=True, rights_attested=True)
        cls.candidate = ProductCandidate.objects.get()

    def setUp(self):
        self.client.force_login(self.reviewer)
        self.url = reverse('staff_product_detail', args=[self.candidate.pk])

    def test_consistent_payload_keeps_comparison_and_review_form(self):
        response = self.client.get(self.url)
        self.assertTrue(response.context['comparison']['available'])
        self.assertContains(response, 'name="decision"')
        self.assertNotContains(response, 'اطلاعات این رکورد ناسازگار است؛ بازبینی متوقف شد')

    def test_inconsistent_payload_suppresses_form_and_comparison(self):
        for update in (dict(payload_sha256='0' * 64), dict(source_record_id='changed'),
                       dict(irc_normalized='invalid'), dict(source_url='http://example.org/unsafe'),
                       dict(source_fields={**self.row, 'extra': 'synthetic'})):
            with self.subTest(update=update):
                ProductCandidate.objects.filter(pk=self.candidate.pk).update(**update)
                response = self.client.get(self.url)
                self.assertFalse(response.context['comparison']['available'])
                self.assertContains(response, 'اطلاعات این رکورد ناسازگار است؛ بازبینی متوقف شد')
                self.assertNotContains(response, 'name="decision"')
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                ProductCandidate.objects.filter(pk=self.candidate.pk).update(**{
                    k: getattr(self.candidate, k) for k in update})
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_inconsistent_identity_values_are_not_rendered_in_detail(self):
        altered = {**self.row, 'name_fa': 'product-identity-canary', 'manufacturer': 'product-manufacturer-canary'}
        ProductCandidate.objects.filter(pk=self.candidate.pk).update(source_fields=altered)
        for method in (self.client.get, self.client.head):
            with self.subTest(method=method.__name__):
                response = method(self.url)
                self.assertEqual(response.status_code, 200)
                self.assertNotIn(b'product-identity-canary', response.content)
                self.assertNotIn(b'product-manufacturer-canary', response.content)
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                if method == self.client.get:
                    self.assertContains(response, 'مشخصات ناسازگار نمایش داده نمی‌شوند')
                    self.assertNotContains(response, 'name="decision"')
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_stale_and_malformed_review_responses_suppress_inconsistent_identity(self):
        initial = self.client.get(self.url).context['review_form'].initial
        ProductCandidate.objects.filter(pk=self.candidate.pk).update(
            source_fields={**self.row, 'name_fa': 'product-post-canary'})
        review_url = reverse('staff_product_review', args=[self.candidate.pk])
        for data, status in (({'decision': 'invalid'}, 400),
                             ({**initial, 'decision': 'defer', 'reason': 'توضیح ساختگی برای بررسی اولیه'}, 409)):
            with self.subTest(status=status):
                response = self.client.post(review_url, data)
                self.assertEqual(response.status_code, status)
                self.assertNotContains(response, 'product-post-canary', status_code=status)
                self.assertContains(response, 'مشخصات ناسازگار نمایش داده نمی‌شوند', status_code=status)
                self.assertNotContains(response, 'name="decision"', status_code=status)
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_stale_post_conflicts_without_review_or_form(self):
        before = self.client.get(self.url).context['review_form'].initial
        ProductCandidate.objects.filter(pk=self.candidate.pk).update(irc_normalized='changed')
        response = self.client.post(reverse('staff_product_review', args=[self.candidate.pk]), {
            **before, 'decision': 'defer', 'reason': 'توضیح ساختگی برای بررسی اولیه'})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'اطلاعات این رکورد ناسازگار است؛ بازبینی متوقف شد', status_code=409)
        self.assertNotContains(response, 'name="decision"', status_code=409)
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_coherent_rewrite_passes_consistency_check_without_proving_authenticity(self):
        from .intake import fingerprint
        altered = {**self.row, 'name_fa': 'نام بازنویسی‌شده ساختگی'}
        digest = fingerprint(self.candidate.source_name, self.candidate.source_url, altered)
        ProductCandidate.objects.filter(pk=self.candidate.pk).update(source_fields=altered, payload_sha256=digest)
        response = self.client.get(self.url)
        self.assertTrue(response.context['comparison']['available'])
        self.assertContains(response, 'نام بازنویسی‌شده ساختگی')
        self.assertContains(response, 'name="decision"')

    def test_invalid_form_and_payload_does_not_reenable_review(self):
        ProductCandidate.objects.filter(pk=self.candidate.pk).update(irc_normalized='changed')
        response = self.client.post(reverse('staff_product_review', args=[self.candidate.pk]), {'decision': 'invalid'})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'اطلاعات این رکورد ناسازگار است؛ بازبینی متوقف شد', status_code=400)
        self.assertNotContains(response, 'name="decision"', status_code=400)
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_in_flight_candidate_read_does_not_establish_snapshot(self):
        from .comparisons import product_comparison_context
        def mutate_then_compare(candidate):
            ProductCandidate.objects.filter(pk=candidate.pk).update(irc_normalized='changed')
            return product_comparison_context(candidate)
        with patch('catalog.staff_views.product_comparison_context', side_effect=mutate_then_compare):
            stale = self.client.get(self.url)
        self.assertContains(stale, 'name="decision"')
        fresh = self.client.get(self.url)
        self.assertNotContains(fresh, 'name="decision"')
        self.assertContains(fresh, 'اطلاعات این رکورد ناسازگار است؛ بازبینی متوقف شد')
