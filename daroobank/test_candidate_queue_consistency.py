"""Synthetic private queues do not present inconsistent identity fields."""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.intake import stage_products
from catalog.models import ProductCandidate
from catalog.test_intake import make_csv
from pricing.importer import stage_csv
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes


@override_settings(STAFF_PORTAL_ENABLED=True)
class CandidateQueueConsistencyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create_user('synthetic-queue-operator', is_staff=True)
        for app, model in (('catalog', 'productcandidate'), ('pricing', 'pricecandidate')):
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label=app,
                                        codename__in=[f'view_{model}', f'add_{model}']))
        cls.user = user
        cls.product_row = dict(source_record_id='synthetic-product', name_fa='نام محصول سالم', name_en='',
                               manufacturer='سازنده سالم', strength='1 mg', dosage_form='قرص',
                               package_description='10 عدد', irc='123')
        cls.price_row = dict(source_record_id='synthetic-price', irc='123', manufacturer='سازنده سالم',
                             strength='1 mg', dosage_form='قرص', package_description='10 عدد', amount='100',
                             currency='RIAL', category='retail', unit='package', effective_date='', source_published_date='')
        stage_products(io.BytesIO(make_csv([cls.product_row])), 'منبع ساختگی', 'https://example.org/product',
                       actor=user, commit=True, rights_attested=True)
        stage_csv(io.BytesIO(csv_bytes([cls.price_row])), 'منبع ساختگی', 'https://example.org/price',
                  staged_by=user, commit=True, rights_attested=True)
        cls.product = ProductCandidate.objects.get()
        cls.price = PriceCandidate.objects.get()

    def setUp(self):
        self.client.force_login(self.user)

    def test_valid_candidates_remain_visible_without_matching_lookup(self):
        with patch('pricing.staff_views.suggest_product') as match:
            product = self.client.get(reverse('staff_products'))
            price = self.client.get(reverse('staff_prices'))
        match.assert_not_called()
        self.assertContains(product, 'نام محصول سالم')
        self.assertContains(price, 'سازنده سالم')
        self.assertNotContains(product, 'مشخصات نامزد ناسازگار نمایش داده نمی‌شوند')
        self.assertNotContains(price, 'مشخصات نامزد ناسازگار نمایش داده نمی‌شوند')

    def test_coherent_rewrite_can_still_pass_the_unkeyed_consistency_check(self):
        from catalog.intake import fingerprint
        changed = {**self.product_row, 'name_fa': 'نام بازنویسی‌شده ساختگی'}
        ProductCandidate.objects.filter(pk=self.product.pk).update(
            source_fields=changed, payload_sha256=fingerprint(self.product.source_name, self.product.source_url, changed))
        response = self.client.get(reverse('staff_products'))
        self.assertContains(response, 'نام بازنویسی‌شده ساختگی')
        self.assertNotContains(response, 'مشخصات نامزد ناسازگار نمایش داده نمی‌شوند')

    def test_amount_inconsistency_also_hides_price_identity(self):
        PriceCandidate.objects.filter(pk=self.price.pk).update(amount_rial=101)
        response = self.client.get(reverse('staff_prices'))
        self.assertContains(response, 'مشخصات نامزد ناسازگار نمایش داده نمی‌شوند')
        self.assertNotContains(response, 'سازنده سالم')
        self.assertContains(response, reverse('staff_price_detail', args=[self.price.pk]))

    def test_corrupt_candidate_identity_is_suppressed_in_queue(self):
        ProductCandidate.objects.filter(pk=self.product.pk).update(
            source_fields={**self.product_row, 'name_fa': 'product-queue-private-canary'})
        PriceCandidate.objects.filter(pk=self.price.pk).update(
            source_fields={**self.price_row, 'manufacturer': 'price-queue-private-canary'})
        for endpoint, canary in (('staff_products', b'product-queue-private-canary'),
                                 ('staff_prices', b'price-queue-private-canary')):
            for method in (self.client.get, self.client.head):
                with self.subTest(endpoint=endpoint, method=method.__name__):
                    response = method(reverse(endpoint))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                    self.assertNotIn(canary, response.content)
                    if method == self.client.get:
                        self.assertContains(response, 'مشخصات نامزد ناسازگار نمایش داده نمی‌شوند')
