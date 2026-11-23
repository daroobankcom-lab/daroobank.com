"""Privacy headers on resolved public read endpoints, including early errors."""
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=False)
class PublicReadPrivacyTests(TestCase):
    def assert_privacy_headers(self, response):
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, follow')

    def public_urls(self):
        return [reverse('search'), reverse('search_api'),
                reverse('presentation_detail', args=[99999]),
                reverse('presentation_api', args=[99999]), reverse('openapi_document')]

    def test_success_and_handled_errors_for_get_and_head(self):
        cases = [(reverse('search'), {}, 200), (reverse('search_api'), {}, 200),
                 (reverse('search'), {'q': 'safe\x00bad'}, 400),
                 (reverse('search_api'), {'q': 'safe\x00bad'}, 400),
                 (reverse('search'), {'q': 'safe', 'cursor': 'bad'}, 400),
                 (reverse('search_api'), {'q': 'safe', 'cursor': 'bad'}, 400),
                 (reverse('presentation_detail', args=[99999]), {}, 404),
                 (reverse('presentation_api', args=[99999]), {}, 404),
                 (reverse('openapi_document'), {}, 200)]
        for url, params, status in cases:
            for method in (self.client.get, self.client.head):
                with self.subTest(url=url, status=status, method=method.__name__):
                    response = method(url, params)
                    self.assertEqual(response.status_code, status)
                    self.assert_privacy_headers(response)
                    if method == self.client.head:
                        self.assertEqual(response.content, b'')

    def test_method_rejections_and_csrf_short_circuit(self):
        client = Client(enforce_csrf_checks=True)
        for url in self.public_urls():
            with self.subTest(url=url, case='csrf'):
                response = client.post(url + '?q=synthetic-canary')
                self.assertEqual(response.status_code, 403)
                self.assert_privacy_headers(response)
            client.cookies['csrftoken'] = 'a' * 32  # Synthetic valid-format test token.
            for method in ('post', 'put', 'patch', 'delete', 'options', 'trace'):
                with self.subTest(url=url, method=method), self.assertNumQueries(0):
                    response = client.generic(method.upper(), url + '?q=synthetic-canary',
                                              HTTP_X_CSRFTOKEN='a' * 32)
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response['Allow'], 'GET, HEAD')
                    self.assert_privacy_headers(response)
                    self.assertNotIn(b'synthetic-canary', response.content)
            client.cookies.clear()

    @override_settings(APPEND_SLASH=True)
    def test_slashless_redirects_keep_public_privacy_policy(self):
        for path in ('/search', '/api/v1/search', '/products/123', '/api/v1/products/123'):
            for method in (self.client.get, self.client.head):
                with self.subTest(path=path, method=method.__name__), self.assertNumQueries(0):
                    response = method(path, {'q': 'synthetic-canary'})
                    self.assertEqual(response.status_code, 301)
                    self.assertEqual(response['Location'], path + '/?q=synthetic-canary')
                    self.assert_privacy_headers(response)
                    self.assertNotIn(b'synthetic-canary', response.content)

    @override_settings(APPEND_SLASH=False)
    def test_slashless_missing_routes_keep_policy_without_redirect(self):
        for path in ('/search', '/api/v1/search', '/products/123', '/api/v1/products/123'):
            with self.subTest(path=path), self.assertNumQueries(0):
                response = self.client.get(path, {'q': 'synthetic-canary'})
                self.assertEqual(response.status_code, 404)
                self.assert_privacy_headers(response)

    def test_slashless_lookalikes_do_not_acquire_public_policy(self):
        for path in ('/searches', '/api/v1/search-other', '/products/123extra',
                     '/products/-1', '/products/123/extra', '/staff/products/123'):
            with self.subTest(path=path):
                response = self.client.get(path)
                if path.startswith('/staff/'):
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                else:
                    self.assertNotEqual(response.get('Referrer-Policy'), 'no-referrer')

    def test_resolved_unhandled_error_is_covered_without_exposing_details(self):
        client = Client(raise_request_exception=False)
        with patch('catalog.views.search_product_page', side_effect=RuntimeError('synthetic-secret')):
            response = client.get(reverse('search_api'), {'q': 'synthetic-canary'})
        self.assertEqual(response.status_code, 500)
        self.assert_privacy_headers(response)
        self.assertNotIn(b'synthetic-secret', response.content)
        self.assertNotIn(b'synthetic-canary', response.content)

    def test_unrelated_routes_keep_their_own_policy(self):
        self.assertEqual(self.client.get(reverse('home'))['Referrer-Policy'], 'same-origin')
        self.assertEqual(self.client.get('/unresolved-synthetic-path/')['Referrer-Policy'], 'same-origin')
        with self.settings(STAFF_PORTAL_ENABLED=False):
            staff = self.client.get(reverse('staff_workspace'))
        self.assertEqual(staff.status_code, 404)
        self.assertEqual(staff['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(staff['Referrer-Policy'], 'same-origin')
        self.assertEqual(staff['X-Robots-Tag'], 'noindex, nofollow')
