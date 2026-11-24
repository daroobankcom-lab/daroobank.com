"""Public reads need current display fields, not stored projection payloads."""
from datetime import datetime, timezone

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import ProductPresentation
from .services import get_public_presentation, search_product_page, serialize_presentation


class PublicProjectionFetchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='نمونه ساختگی', name_en='Synthetic marker', manufacturer='سازنده فرضی',
            strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='123',
            source_name='منبع فرضی', source_url='https://example.org/synthetic',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True,
        )
        # Simulate a projection corrupted by a bypassed write. It must remain
        # eligible for the SQL candidate query without being returned to Python.
        ProductPresentation.objects.filter(pk=cls.product.pk).update(
            search_text='synthetic marker ' + 'x' * 1_000_000,
            irc_normalized='private-canary',
        )

    def assert_no_projection_columns_in_select(self, queries):
        selects = [q['sql'].split(' FROM ', 1)[0].lower() for q in queries
                   if q['sql'].lstrip().upper().startswith('SELECT') and 'catalog_productpresentation' in q['sql']]
        self.assertTrue(selects)
        for select in selects:
            self.assertNotIn('"search_text"', select)
            self.assertNotIn('"irc_normalized"', select)

    def test_services_return_same_display_fields_without_loading_projections(self):
        with CaptureQueriesContext(connection) as queries:
            results, cursor = search_product_page('synthetic marker')
            product = get_public_presentation(self.product.pk)
            search_data = [serialize_presentation(row) for row in results]
            detail_data = serialize_presentation(product)
        self.assertEqual(len(queries), 2)
        self.assert_no_projection_columns_in_select(queries)
        self.assertEqual([row.pk for row in results], [self.product.pk])
        self.assertIsNone(cursor)
        self.assertEqual(search_data, [detail_data])
        self.assertEqual(product.get_deferred_fields(), {'search_text', 'irc_normalized'})
        self.assertEqual(results[0].get_deferred_fields(), {'search_text', 'irc_normalized'})

    def test_selected_html_and_json_do_not_trigger_projection_fetch(self):
        for url, params in [
            (reverse('search'), {'q': 'synthetic marker'}),
            (reverse('search_api'), {'q': 'synthetic marker'}),
            (reverse('presentation_detail', args=[self.product.pk]), {}),
            (reverse('presentation_api', args=[self.product.pk]), {}),
        ]:
            for method in (self.client.get, self.client.head):
                with self.subTest(url=url, method=method.__name__), CaptureQueriesContext(connection) as queries:
                    response = method(url, params)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(queries), 1)
                self.assert_no_projection_columns_in_select(queries)
                self.assertNotIn(b'private-canary', response.content)
                if method == self.client.get:
                    if url.startswith('/api/'):
                        body = response.json()['data']
                        self.assertEqual((body[0] if isinstance(body, list) else body)['name_fa'], 'نمونه ساختگی')
                    else:
                        self.assertContains(response, 'نمونه ساختگی')
