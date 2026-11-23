"""Public search rejects PostgreSQL-incompatible input without leaking it."""
from django.test import TestCase
from django.urls import reverse

from .services import InvalidSearchQuery, MAX_QUERY_LENGTH, search_product_page


class InvalidSearchQueryTests(TestCase):
    def test_service_rejects_nul_and_surrogates_before_querying(self):
        for query in ['\x00', 'pre\x00post', '\ud800', 'a\udfffb']:
            with self.subTest(query=ascii(query)), self.assertNumQueries(0), self.assertRaises(InvalidSearchQuery):
                search_product_page(query)
        with self.assertNumQueries(0), self.assertRaises(InvalidSearchQuery):
            search_product_page('safe\x00bad', cursor='invalid')

    def test_html_and_api_return_private_no_echo_error_and_head(self):
        secret = 'untrusted-canary-827'
        for name in ('search', 'search_api'):
            for query in ['\x00', secret + '\x00<script>']:
                for method in (self.client.get, self.client.head):
                    with self.subTest(name=name, query=ascii(query), method=method.__name__), self.assertNumQueries(0):
                        response = method(reverse(name), {'q': query, 'cursor': 'bad'})
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(response['Cache-Control'], 'no-store')
                        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
                        self.assertEqual(response['X-Robots-Tag'], 'noindex, follow')
                        self.assertNotIn(secret.encode(), response.content)
                        self.assertNotIn(b'\x00', response.content)
                        if method == self.client.get and name == 'search_api':
                            self.assertEqual(response.json(), {'error': {'code': 'invalid_query',
                                'message': 'Search query contains unsupported characters.'}})
                        if method == self.client.get and name == 'search':
                            self.assertContains(response, 'عبارت جست‌وجو قابل پردازش نیست', status_code=400)
                            self.assertContains(response, 'value=""', status_code=400)
                            self.assertNotContains(response, '&lt;script&gt;', status_code=400)

    def test_bounded_prefix_keeps_existing_truncation_semantics(self):
        for name in ('search', 'search_api'):
            invalid = self.client.get(reverse(name), {'q': 'x' * (MAX_QUERY_LENGTH - 1) + '\x00'})
            self.assertEqual(invalid.status_code, 400)
            ignored_tail = self.client.get(reverse(name), {'q': 'x' * MAX_QUERY_LENGTH + '\x00'})
            self.assertEqual(ignored_tail.status_code, 200)
        self.assertEqual(search_product_page('x' * MAX_QUERY_LENGTH + '\ud800'), ([], None))

    def test_other_normalized_unicode_remains_searchable(self):
        # This safety check does not redefine the existing lookup normalization.
        self.assertEqual(self.client.get(reverse('search_api'), {'q': '  \u200c  '}).status_code, 200)
        self.assertEqual(self.client.get(reverse('search_api'), {'q': 'كيک ۱۲٣'}).status_code, 200)
