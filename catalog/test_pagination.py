from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.core import signing
from django.test import TestCase
from django.urls import reverse

from .models import ProductPresentation
from .services import CURSOR_SALT, MAX_CURSOR_LENGTH, MAX_SEARCH_CANDIDATES, is_public_presentation


class SearchPaginationTests(TestCase):
    @staticmethod
    def make_product(name, **overrides):
        values = dict(
            name_fa=name, name_en='Synthetic', manufacturer='شرکت فرضی', strength='۵ میلی گرم',
            dosage_form='قرص', package_description='۱۰ عدد', irc='', source_name='منبع فرضی',
            source_url='https://example.org/synthetic', verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            published=True,
        )
        values.update(overrides)
        return ProductPresentation.objects.create(**values)

    def api(self, query='شرکت فرضی', cursor=None):
        params = {'q': query}
        if cursor is not None:
            params['cursor'] = cursor
        return self.client.get(reverse('search_api'), params)

    def test_all_pages_and_duplicate_names_are_stable_on_unchanged_data(self):
        for _ in range(65):
            self.make_product('محصول آزمایشی')
        self.make_product('پیش نویس', published=False)
        cursor = None
        ids, page_sizes = [], []
        for _ in range(3):
            response = self.api(cursor=cursor)
            self.assertEqual(response.status_code, 200)
            body = response.json()
            self.assertEqual(body['meta']['limit'], 30)
            self.assertEqual(body['meta']['candidate_scan_limit'], 150)
            self.assertTrue(body['meta']['pagination_available'])
            page_sizes.append(len(body['data']))
            ids.extend(item['id'] for item in body['data'])
            cursor = body['meta']['next_cursor']
        self.assertIsNone(cursor)
        self.assertEqual(page_sizes, [30, 30, 5])
        self.assertEqual(ids, sorted(ids))
        self.assertEqual(len(set(ids)), 65)
        self.assertEqual(self.api().json()['data'][0]['name_fa'], 'محصول آزمایشی')

    def test_html_next_link_preserves_encoded_query_and_uses_same_service(self):
        for i in range(31):
            self.make_product(f'فرآورده {i:02}', manufacturer='شرکت & نمونه')
        query = 'شركت & نمونه'
        response = self.client.get(reverse('search'), {'q': query})
        self.assertContains(response, 'بخش بعدی نتایج')
        cursor = response.context['next_cursor']
        self.assertEqual(self.api(query, cursor).status_code, 200)
        # Locate the actual rendered href to ensure query punctuation stays encoded.
        from html.parser import HTMLParser
        class Links(HTMLParser):
            hrefs = []
            def handle_starttag(self, tag, attrs):
                if tag == 'a':
                    self.hrefs.append(dict(attrs).get('href', ''))
        parser = Links()
        parser.feed(response.content.decode())
        link = next(href for href in parser.hrefs if 'cursor=' in href)
        params = parse_qs(urlsplit(link).query)
        self.assertEqual(params['q'], [query])
        self.assertEqual(params['cursor'], [cursor])
        second = self.client.get(reverse('search') + link)
        self.assertEqual(len(second.context['results']), 1)
        self.assertIsNone(second.context['next_cursor'])
        self.assertNotContains(second, 'بخش بعدی نتایج')

    def test_empty_bounded_page_can_continue_past_invalid_records_without_leaks(self):
        for i in range(MAX_SEARCH_CANDIDATES):
            self.make_product(f'A confidential {i:03}')
        ProductPresentation.objects.filter(name_fa__startswith='A confidential').update(source_name='  ')
        visible = self.make_product('B synthetic')
        with patch('catalog.services.is_public_presentation', wraps=is_public_presentation) as validate:
            first = self.api()
        self.assertEqual(validate.call_count, MAX_SEARCH_CANDIDATES)
        self.assertEqual(first.json()['data'], [])
        cursor = first.json()['meta']['next_cursor']
        self.assertIsNotNone(cursor)
        payload = signing.loads(cursor, salt=CURSOR_SALT)
        self.assertEqual(set(payload), {'query', 'name', 'pk'})
        self.assertNotIn('confidential', str(payload))
        self.assertNotIn('شرکت', str(payload))
        html = self.client.get(reverse('search'), {'q': 'شرکت فرضی'})
        self.assertContains(html, 'می‌توانید بخش بعدی را بررسی کنید')
        self.assertNotContains(html, 'confidential')
        following = self.api(cursor=cursor).json()
        self.assertEqual([p['id'] for p in following['data']], [visible.pk])
        self.assertIsNone(following['meta']['next_cursor'])

    def test_cursor_binding_normalization_and_tamper_fail_closed(self):
        for i in range(31):
            self.make_product(f'محصول {i:02}')
        cursor = self.api('شركت فرضی').json()['meta']['next_cursor']
        self.assertEqual(self.api('شرکت فرضی', cursor).status_code, 200)
        invalid = [('different', cursor), ('', cursor), ('شرکت فرضی', cursor + 'x'),
                   ('شرکت فرضی', 'x' * (MAX_CURSOR_LENGTH + 1)), ('شرکت فرضی', '<script>')]
        for query, bad in invalid:
            with self.subTest(query=query, cursor=bad[:20]):
                api = self.api(query, bad)
                self.assertEqual(api.status_code, 400)
                self.assertEqual(api.json()['error']['code'], 'invalid_cursor')
                self.assertEqual(api['Cache-Control'], 'no-store')
                self.assertEqual(api['Referrer-Policy'], 'no-referrer')
                self.assertEqual(api['X-Robots-Tag'], 'noindex, follow')
                html = self.client.get(reverse('search'), {'q': query, 'cursor': bad})
                self.assertEqual(html.status_code, 400)
                self.assertContains(html, 'جست‌وجو را دوباره آغاز کنید', status_code=400)
                self.assertNotContains(html, '<script>', status_code=400)
                self.assertEqual(html['Cache-Control'], 'no-store')

    def test_expired_deleted_or_changed_anchor_requests_restart(self):
        for i in range(31):
            self.make_product(f'محصول {i:02}')
        with patch('django.core.signing.time.time', return_value=10000):
            cursor = self.api().json()['meta']['next_cursor']
        with patch('django.core.signing.time.time', return_value=13601):
            self.assertEqual(self.api(cursor=cursor).status_code, 400)
        cursor = self.api().json()['meta']['next_cursor']
        pk = signing.loads(cursor, salt=CURSOR_SALT)['pk']
        ProductPresentation.objects.filter(pk=pk).update(name_fa='نام تغییرکرده')
        self.assertEqual(self.api(cursor=cursor).status_code, 400)
        ProductPresentation.objects.filter(pk=pk).update(name_fa='محصول 29')
        self.assertEqual(self.api(cursor=cursor).status_code, 200)
        ProductPresentation.objects.filter(pk=pk).update(published=False)
        self.assertEqual(self.api(cursor=cursor).status_code, 400)
        ProductPresentation.objects.filter(pk=pk).delete()
        self.assertEqual(self.api(cursor=cursor).status_code, 400)

    def test_compressed_cursor_is_rejected_without_decompression(self):
        token = signing.dumps({'payload': 'x' * 10000}, salt=CURSOR_SALT, compress=True)
        self.assertTrue(token.startswith('.'))
        self.assertEqual(self.api(cursor=token).status_code, 400)

    def test_cursors_with_signed_but_wrong_payload_types_are_rejected(self):
        for data in [None, [], {}, {'query': 'x', 'name': 'x', 'pk': True},
                     {'query': 'x', 'name': 'x', 'pk': 9223372036854775808},
                     {'query': [], 'name': 'x', 'pk': 1}]:
            token = signing.dumps(data, salt=CURSOR_SALT)
            self.assertEqual(self.api(cursor=token).status_code, 400)

    def test_keyset_is_not_a_snapshot_when_data_changes(self):
        for i in range(31):
            self.make_product(f'Item {i:02}')
        first = self.api().json()
        cursor = first['meta']['next_cursor']
        before = self.make_product('Item 00 extra')
        after = self.make_product('Item 40 extra')
        ProductPresentation.objects.filter(name_fa='Item 30').update(published=False)
        second = self.api(cursor=cursor).json()
        self.assertEqual([item['id'] for item in second['data']], [after.pk])
        self.assertNotIn(before.pk, [item['id'] for item in first['data'] + second['data']])

    def test_key_rotation_invalidates_old_cursor(self):
        for i in range(31):
            self.make_product(f'Item {i:02}')
        cursor = self.api().json()['meta']['next_cursor']
        with self.settings(SECRET_KEY='different-local-test-key'):
            self.assertEqual(self.api(cursor=cursor).status_code, 400)

    def test_empty_and_exact_page_have_no_extra_cursor(self):
        self.assertEqual(self.api(query='').json()['data'], [])
        self.assertIsNone(self.api(query='').json()['meta']['next_cursor'])
        for i in range(30):
            self.make_product(f'محصول {i:02}')
        page = self.api().json()
        self.assertEqual(len(page['data']), 30)
        self.assertIsNone(page['meta']['next_cursor'])
