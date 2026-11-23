from datetime import datetime, timezone

from django.test import TestCase
from django.urls import reverse

from .models import ProductPresentation
from .services import MAX_SEARCH_CANDIDATES


class PresentationDetailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='فرآورده ساختگی', name_en='Synthetic example', manufacturer='سازنده فرضی',
            strength='۵ میلی‌گرم', dosage_form='قرص', package_description='۱۰ عدد', irc='001234',
            source_name='منبع ساختگی', source_url='https://example.org/item',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True,
        )
        cls.draft = ProductPresentation.objects.create(
            name_fa='پیش‌نویس ساختگی', manufacturer='سازنده فرضی', strength='۵ میلی‌گرم',
            dosage_form='قرص', package_description='۱۰ عدد', irc='', source_name='منبع ساختگی',
            source_url='https://example.org/item', verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

    def urls(self, pk):
        return reverse('presentation_detail', args=[pk]), reverse('presentation_api', args=[pk])

    def assert_private_read_headers(self, response):
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, follow')

    def test_search_to_detail_and_api_contract(self):
        html_url, api_url = self.urls(self.product.pk)
        search = self.client.get(reverse('search'), {'q': '۰۰۱۲۳۴'})
        self.assertContains(search, f'href="{html_url}"')
        html = self.client.get(html_url)
        self.assertEqual(html.status_code, 200)
        self.assertContains(html, 'lang="fa" dir="rtl"')
        for value in ['فرآورده ساختگی', 'Synthetic example', 'سازنده فرضی', '۵ میلی‌گرم', '۱۰ عدد', '001234', 'منبع ساختگی']:
            self.assertContains(html, value)
        self.assertContains(html, 'نه راهنمای مصرف دارو')
        self.assertContains(html, 'نشان‌دهنده تأیید بالینی یا مجوز بازنشر نیستند')
        self.assertContains(html, 'name="robots" content="noindex,follow"')
        self.assertNotContains(html, 'rel="canonical"')
        self.assert_private_read_headers(html)
        api = self.client.get(api_url)
        self.assert_private_read_headers(api)
        self.assertEqual(api.json()['data'], self.client.get(reverse('search_api'), {'q': '001234'}).json()['data'][0])
        self.assertNotIn('price', api.json()['data'])
        self.assertNotIn('clinical', api.json()['data'])
        self.assertNotIn('published', api.json()['data'])

    def test_draft_missing_and_out_of_range_are_indistinguishable(self):
        for pk in (self.draft.pk, 99999999, 0, 9223372036854775808):
            html_url, api_url = self.urls(pk)
            html, api = self.client.get(html_url), self.client.get(api_url)
            self.assertEqual(html.status_code, 404)
            self.assertEqual(api.status_code, 404)
            self.assert_private_read_headers(html)
            self.assert_private_read_headers(api)
            self.assertEqual(api.json(), {'error': {'code': 'not_found', 'message': 'Presentation not found.'}})
            self.assertNotContains(html, 'پیش‌نویس ساختگی', status_code=404)
        self.assertNotContains(self.client.get(reverse('sitemap')), '/products/')

    def test_unpublished_or_metadata_removed_disappears_immediately(self):
        html_url, api_url = self.urls(self.product.pk)
        for change in [dict(published=False), dict(verified_at=None), dict(source_name=''), dict(source_name='   '),
                       dict(source_url='http://example.org'), dict(source_url='https://'),
                       dict(source_url='https://user:password@example.org/path'), dict(name_fa='  '),
                       dict(manufacturer=''), dict(strength=''), dict(dosage_form=''), dict(package_description='')]:
            with self.subTest(change=change):
                ProductPresentation.objects.filter(pk=self.product.pk).update(**change)
                self.assertEqual(self.client.get(html_url).status_code, 404)
                self.assertEqual(self.client.get(api_url).status_code, 404)
                self.assertEqual(self.client.get(reverse('search_api'), {'q': '001234'}).json()['data'], [])
                self.product.refresh_from_db()
                # Restore without invoking model validation for each intentional corruption.
                ProductPresentation.objects.filter(pk=self.product.pk).update(
                    published=True, verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), source_name='منبع ساختگی',
                    source_url='https://example.org/item', name_fa='فرآورده ساختگی', manufacturer='سازنده فرضی',
                    strength='۵ میلی‌گرم', dosage_form='قرص', package_description='۱۰ عدد',
                )

    def test_control_characters_in_public_fields_are_not_disclosed(self):
        # Direct SQL/ORM updates bypass model validation and leave the search
        # projection unchanged; both public reads must still fail closed.
        fields = ('name_fa', 'name_en', 'manufacturer', 'strength', 'dosage_form',
                  'package_description', 'irc', 'source_name', 'source_url')
        for field in fields:
            with self.subTest(field=field):
                original = getattr(self.product, field)
                corrupted = original + '\x01private-canary'
                ProductPresentation.objects.filter(pk=self.product.pk).update(**{field: corrupted})
                html, api = (self.client.get(url) for url in self.urls(self.product.pk))
                self.assertEqual(html.status_code, 404)
                self.assertEqual(api.status_code, 404)
                self.assert_private_read_headers(html)
                self.assert_private_read_headers(api)
                self.assertNotIn(b'private-canary', html.content)
                self.assertNotIn(b'private-canary', api.content)
                search = self.client.get(reverse('search'), {'q': '001234'})
                search_api = self.client.get(reverse('search_api'), {'q': '001234'})
                self.assertNotContains(search, 'private-canary')
                self.assertNotContains(search, f'/products/{self.product.pk}/')
                self.assertEqual(search_api.json()['data'], [])
                ProductPresentation.objects.filter(pk=self.product.pk).update(**{field: original})
        # An optional blank field and the Persian zero-width non-joiner stay valid.
        self.assertEqual(self.client.get(self.urls(self.product.pk)[1]).status_code, 200)
        ProductPresentation.objects.filter(pk=self.product.pk).update(name_en='', irc='')
        self.assertEqual(self.client.get(self.urls(self.product.pk)[1]).status_code, 200)

    def test_invalid_python_text_types_and_surrogates_are_rejected(self):
        from .services import is_public_presentation
        for field in ('name_fa', 'name_en', 'manufacturer', 'strength', 'dosage_form',
                      'package_description', 'irc', 'source_name', 'source_url'):
            for value in (None, 123, '\ud800', 'bad\x7ftext', 'bad\x85text'):
                with self.subTest(field=field, value=ascii(value)):
                    original = getattr(self.product, field)
                    try:
                        setattr(self.product, field, value)
                        self.assertFalse(is_public_presentation(self.product))
                    finally:
                        setattr(self.product, field, original)

    def test_escaping_and_optional_irc(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(
            name_fa='<script>alert(1)</script>', source_name='<b>منبع</b>', irc='',
            source_url='https://example.org/item?a=1&b=2',
        )
        html = self.client.get(self.urls(self.product.pk)[0])
        self.assertNotContains(html, '<script>alert(1)</script>')
        self.assertContains(html, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(html, '<b>منبع</b>')
        self.assertContains(html, 'https://example.org/item?a=1&amp;b=2')
        self.assertContains(html, 'نامشخص')
        self.assertIsNone(self.client.get(self.urls(self.product.pk)[1]).json()['data']['irc'])

    def test_safe_methods_only(self):
        for url in self.urls(self.product.pk):
            self.assertEqual(self.client.head(url).status_code, 200)
            self.assertEqual(self.client.post(url).status_code, 405)
            self.assertEqual(self.client.put(url).status_code, 405)

    def test_candidate_inspection_is_bounded_even_for_bad_metadata(self):
        # All entries still pass the SQL prefilter but fail source validation in Python.
        for i in range(MAX_SEARCH_CANDIDATES):
            ProductPresentation.objects.create(
                name_fa=f'الف{i:04}', manufacturer='سازنده فرضی', strength='۵ میلی‌گرم',
                dosage_form='قرص', package_description='۱۰ عدد', source_name='منبع',
                source_url='https://example.org/item', verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True,
            )
        ProductPresentation.objects.filter(name_fa__startswith='الف').update(source_name='   ')
        response = self.client.get(reverse('search_api'), {'q': 'سازنده فرضی'})
        self.assertEqual(response.json()['data'], [])
        self.assertEqual(response.json()['meta']['candidate_scan_limit'], MAX_SEARCH_CANDIDATES)
        self.assertContains(self.client.get(reverse('search'), {'q': 'سازنده فرضی'}), 'می‌توانید بخش بعدی را بررسی کنید')
        # A separately addressed valid record is still available despite the search cap.
        self.assertEqual(self.client.get(self.urls(self.product.pk)[1]).status_code, 200)
