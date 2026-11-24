"""Direct public-detail service accepts only PostgreSQL bigint IDs."""
from datetime import datetime, timezone
from decimal import Decimal

from django.http import Http404
from django.test import TestCase
from django.urls import reverse

from .models import ProductPresentation
from .services import get_public_presentation


class PublicDetailIdTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='شناسه ساختگی', manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص',
            package_description='10 عدد', source_name='منبع', source_url='https://example.org/synthetic',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True,
        )

    def test_direct_service_rejects_coercible_and_out_of_range_ids_without_query(self):
        bad_values = [None, True, False, 0, -1, 2**63, str(self.product.pk),
                      float(self.product.pk), Decimal(self.product.pk), [], {}]
        for pk in bad_values:
            with self.subTest(pk=repr(pk)), self.assertNumQueries(0), self.assertRaises(Http404):
                get_public_presentation(pk)

    def test_real_integer_and_public_http_contract_remain_unchanged(self):
        self.assertEqual(get_public_presentation(self.product.pk).pk, self.product.pk)
        self.assertEqual(self.client.get(reverse('presentation_api', args=[self.product.pk])).json()['data']['id'],
                         self.product.pk)
        for path in ('/api/v1/products/0/', '/api/v1/products/9223372036854775808/'):
            with self.subTest(path=path), self.assertNumQueries(0):
                self.assertEqual(self.client.get(path).status_code, 404)
