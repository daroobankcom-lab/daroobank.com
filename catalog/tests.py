from datetime import datetime, timezone
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from .models import ProductPresentation
from .normalization import normalize_search

class SearchNormalizationTests(TestCase):
    def test_normalizes_character_digits_and_spacing(self):
        self.assertEqual(normalize_search('  كيک\u200c۱۲٣  '), 'کیک 123')
        self.assertEqual(normalize_search('ＡＢＣ ٢٠'), 'abc 20')

class ProductSearchTests(TestCase):
    def setUp(self):
        self.data = dict(name_fa='داروی آزمایشی', name_en='Synthetic product', manufacturer='شرکت نمونه', strength='۵ میلی‌گرم', dosage_form='قرص', package_description='۱۰ عدد', irc='001234', source_name='منبع آزمایشی', source_url='https://example.org/product', verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        ProductPresentation.objects.create(**self.data, published=True)
        ProductPresentation.objects.create(**{**self.data, 'name_fa': 'محرمانه'}, published=False)

    def test_published_only_and_no_query_enumeration(self):
        response = self.client.get(reverse('search'), {'q': 'شرکت نمونه'})
        self.assertContains(response, 'داروی آزمایشی')
        self.assertNotContains(response, 'محرمانه')
        self.assertNotContains(self.client.get(reverse('search')), 'داروی آزمایشی')

    def test_api_returns_only_published_sourced_data(self):
        response = self.client.get(reverse('search_api'), {'q': 'شرکت نمونه'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['data']), 1)
        self.assertEqual(response.json()['data'][0]['source']['url'], 'https://example.org/product')
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(self.client.get(reverse('search_api')).json()['data'], [])

    def test_digit_and_arabic_letters(self):
        self.assertContains(self.client.get(reverse('search'), {'q': 'شركت نمونه'}), 'داروی آزمایشی')
        self.assertContains(self.client.get(reverse('search'), {'q': '۰۰۱۲۳۴'}), 'داروی آزمایشی')
        self.assertContains(self.client.get(reverse('search'), {'q': 'SYNTHETIC'}), 'داروی آزمایشی')

    def test_missing_verification_and_non_https_are_rejected(self):
        with self.assertRaises(ValidationError):
            ProductPresentation.objects.create(**{**self.data, 'verified_at': None}, published=True)
        with self.assertRaises(ValidationError):
            ProductPresentation.objects.create(**{**self.data, 'source_url': 'javascript:alert(1)'}, published=True)

    def test_api_bounds_results_and_filters_unsafe_source_after_bulk_write(self):
        for i in range(35):
            ProductPresentation.objects.create(**{**self.data, 'name_fa': f'محصول نمونه {i}'}, published=True)
        draft = ProductPresentation.objects.get(published=False)
        ProductPresentation.objects.filter(pk=draft.pk).update(published=True, source_url='javascript:alert(1)')
        response = self.client.get(reverse('search_api'), {'q': 'شرکت نمونه'})
        self.assertEqual(len(response.json()['data']), 30)
        self.assertTrue(all(item['source']['url'].startswith('https://') for item in response.json()['data']))

    def test_partial_save_updates_normalized_projection(self):
        product = ProductPresentation.objects.get(published=True)
        product.name_fa = 'نام جدید'
        product.save(update_fields=['name_fa'])
        self.assertContains(self.client.get(reverse('search'), {'q': 'نام جدید'}), 'نام جدید')

    def test_partial_or_bypassed_invalid_data_does_not_display(self):
        ProductPresentation.objects.filter(published=False).update(published=True, source_name='')
        response = self.client.get(reverse('search'), {'q': 'محرمانه'})
        self.assertEqual(len(response.context['results']), 0)

    def test_search_escape_and_bound(self):
        response = self.client.get(reverse('search'), {'q': '<script>alert(1)</script>'})
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;')
        self.assertContains(self.client.get(reverse('search'), {'q': 'x' * 200}), 'x' * 120)

class PublicPagesTests(TestCase):
    def test_pages_have_expected_status_and_direction(self):
        for name in ['home', 'search', 'prices', 'about']:
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'lang="fa" dir="rtl"')
            self.assertEqual(response['X-Content-Type-Options'], 'nosniff')

    def test_noindex_and_sitemap(self):
        response = self.client.get(reverse('search'))
        self.assertEqual(response['X-Robots-Tag'], 'noindex, follow')
        self.assertContains(response, 'name="robots" content="noindex,follow"')
        self.assertEqual(self.client.get(reverse('prices'))['X-Robots-Tag'], 'noindex, follow')
        sitemap = self.client.get(reverse('sitemap'))
        self.assertContains(sitemap, 'https://daroobank.com/about/')
        self.assertNotContains(sitemap, '/search/')
        self.assertContains(self.client.get(reverse('home')), 'rel="canonical" href="https://daroobank.com/"')

    def test_methods_are_read_only(self):
        for name in ['home', 'search', 'prices', 'about', 'robots', 'sitemap']:
            self.assertEqual(self.client.post(reverse(name)).status_code, 405)
