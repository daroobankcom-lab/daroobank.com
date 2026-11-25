"""Privacy policies on Django's early HTTPS redirects; all data is synthetic."""
from django.test import Client, SimpleTestCase, override_settings


@override_settings(DEBUG=False, SECURE_SSL_REDIRECT=True, SECURE_SSL_HOST=None, STAFF_PORTAL_ENABLED=False)
class EarlyRedirectPrivacyTests(SimpleTestCase):
    def test_public_https_redirects_keep_privacy_headers_and_query(self):
        paths = ('/search', '/search/', '/api/v1/search', '/api/v1/search/',
                 '/products/42', '/products/42/', '/api/v1/products/42', '/api/v1/products/42/',
                 '/api/v1/openapi.json')
        for path in paths:
            for method in (self.client.get, self.client.head):
                with self.subTest(path=path, method=method.__name__):
                    response = method(path, {'q': 'synthetic-canary'})
                    self.assertEqual(response.status_code, 301)
                    self.assertEqual(response['Location'], 'https://testserver' + path + '?q=synthetic-canary')
                    self.assertEqual(response['Cache-Control'], 'no-store')
                    self.assertEqual(response['Referrer-Policy'], 'no-referrer')
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, follow')
                    self.assertNotIn(b'synthetic-canary', response.content)

    def test_large_numeric_product_paths_keep_redirect_policy(self):
        for prefix in ('/products/', '/api/v1/products/'):
            for suffix in ('', '/'):
                with self.subTest(prefix=prefix, suffix=suffix):
                    response = self.client.get(prefix + '9' * 5000 + suffix, {'q': 'synthetic-canary'})
                    self.assertEqual(response.status_code, 301)
                    self.assertEqual(response['Cache-Control'], 'no-store')
                    self.assertEqual(response['Referrer-Policy'], 'no-referrer')
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, follow')
                    self.assertNotIn(b'synthetic-canary', response.content)

    def test_staff_https_redirect_stays_before_disabled_gate_but_is_private(self):
        client = Client(enforce_csrf_checks=True)
        for path in ('/staff', '/staff/', '/staff/login/', '/staff/unknown/'):
            for method in (client.get, client.head, client.post):
                with self.subTest(path=path, method=method.__name__):
                    response = method(path, {'next': 'synthetic-canary'})
                    self.assertEqual(response.status_code, 301)
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                    self.assertEqual(response['Referrer-Policy'], 'same-origin')
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                    self.assertNotIn(b'synthetic-canary', response.content)
            # On HTTPS the existing disabled gate still returns a private 404.
            secure = client.get(path, secure=True)
            self.assertEqual(secure.status_code, 404)
            self.assertEqual(secure['Cache-Control'], 'private, no-store, max-age=0')

    def test_unrelated_redirects_do_not_get_the_specific_policies(self):
        for path in ('/', '/staffing', '/searches', '/api/v1/search-extra', '/products/42x'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 301)
                self.assertNotEqual(response.get('Cache-Control'), 'no-store')
                self.assertNotEqual(response.get('Cache-Control'), 'private, no-store, max-age=0')
                self.assertNotEqual(response.get('Referrer-Policy'), 'no-referrer')
