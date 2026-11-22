from datetime import datetime, timezone

from django.test import TestCase
from django.urls import reverse

from .models import ProductPresentation
from .services import MAX_CURSOR_LENGTH, MAX_RESULTS, MAX_SEARCH_CANDIDATES


class ApiContractTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='نمونه ساختگی', name_en='', manufacturer='شرکت نمونه', strength='۱ میلی گرم',
            dosage_form='قرص', package_description='بسته نمونه', source_name='منبع نمونه',
            source_url='https://example.org/sample', verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            published=True,
        )

    def assert_schema_shape(self, data, schema, spec):
        """Check the subset of OpenAPI schema keywords used for runtime responses."""
        if '$ref' in schema:
            schema = spec['components']['schemas'][schema['$ref'].split('/')[-1]]
        if data is None:
            self.assertTrue(schema.get('nullable', False))
            return
        if schema['type'] == 'object':
            self.assertIsInstance(data, dict)
            self.assertTrue(set(schema.get('required', [])).issubset(data))
            for name, value in data.items():
                if name in schema.get('properties', {}):
                    self.assert_schema_shape(value, schema['properties'][name], spec)
        elif schema['type'] == 'array':
            self.assertIsInstance(data, list)
            if 'maxItems' in schema:
                self.assertLessEqual(len(data), schema['maxItems'])
            for value in data:
                self.assert_schema_shape(value, schema['items'], spec)
        elif schema['type'] == 'string':
            self.assertIsInstance(data, str)
            if 'maxLength' in schema:
                self.assertLessEqual(len(data), schema['maxLength'])
        elif schema['type'] == 'integer':
            self.assertIs(type(data), int)
        elif schema['type'] == 'boolean':
            self.assertIs(type(data), bool)
        else:
            self.fail(f"Unexpected schema type: {schema['type']}")
        if 'enum' in schema:
            self.assertIn(data, schema['enum'])

    def test_document_paths_limits_and_http_methods(self):
        response = self.client.get(reverse('openapi_document'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, follow')
        doc = response.json()
        self.assertEqual(doc['openapi'], '3.0.3')
        self.assertEqual(set(doc['paths']), {'/api/v1/search/', '/api/v1/products/{id}/', '/api/v1/openapi.json'})
        meta = doc['components']['schemas']['SearchPage']['properties']['meta']['properties']
        self.assertEqual(meta['limit']['enum'], [MAX_RESULTS])
        self.assertEqual(meta['candidate_scan_limit']['enum'], [MAX_SEARCH_CANDIDATES])
        self.assertEqual(meta['next_cursor']['maxLength'], MAX_CURSOR_LENGTH)
        self.assertEqual(self.client.head(reverse('openapi_document')).status_code, 200)
        self.assertEqual(self.client.post(reverse('openapi_document')).status_code, 405)

    def test_actual_responses_match_documented_shapes(self):
        spec = self.client.get(reverse('openapi_document')).json()
        for path, url, params, status in [
            ('/api/v1/search/', reverse('search_api'), {'q': 'شرکت نمونه'}, 200),
            ('/api/v1/search/', reverse('search_api'), {'q': 'شرکت نمونه', 'cursor': 'bad'}, 400),
            ('/api/v1/products/{id}/', reverse('presentation_api', args=[self.product.pk]), {}, 200),
            ('/api/v1/products/{id}/', reverse('presentation_api', args=[99999]), {}, 404),
        ]:
            with self.subTest(path=path, status=status):
                response = self.client.get(url, params)
                self.assertEqual(response.status_code, status)
                schema = spec['paths'][path]['get']['responses'][str(status)]['content']['application/json']['schema']
                self.assert_schema_shape(response.json(), schema, spec)
