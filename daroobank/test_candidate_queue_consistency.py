"""Synthetic private queues do not present inconsistent identity fields."""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog.comparisons import valid_candidate as valid_product_candidate
from catalog.intake import stage_products
from catalog.models import ProductCandidate
from catalog.test_intake import make_csv
from pricing.comparisons import valid_candidate as valid_price_candidate
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

    def test_validation_only_scans_displayed_page_without_per_row_queries(self):
        product_rows = [{**self.product_row, 'source_record_id': f'product-{i}'} for i in range(21)]
        price_rows = [{**self.price_row, 'source_record_id': f'price-{i}'} for i in range(21)]
        stage_products(io.BytesIO(make_csv(product_rows)), 'منبع ساختگی', 'https://example.org/product',
                       actor=self.user, commit=True, rights_attested=True)
        stage_csv(io.BytesIO(csv_bytes(price_rows)), 'منبع ساختگی', 'https://example.org/price',
                  staged_by=self.user, commit=True, rights_attested=True)
        for endpoint, target, check in (
            ('staff_products', 'catalog.staff_views.valid_candidate', valid_product_candidate),
            ('staff_prices', 'pricing.staff_views.valid_candidate', valid_price_candidate),
        ):
            query_counts = []
            for page, expected in ((1, 20), (2, 2)):
                with self.subTest(endpoint=endpoint, page=page), patch(target, wraps=check) as validate:
                    with CaptureQueriesContext(connection) as queries:
                        response = self.client.get(reverse(endpoint), {'page': page})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(validate.call_count, expected)
                    self.assertEqual(len(response.context['page'].object_list), expected)
                    query_counts.append(len(queries))
            self.assertEqual(query_counts[0], query_counts[1])

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
