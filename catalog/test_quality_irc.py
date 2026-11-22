import io
import json
from datetime import datetime, timezone
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core import signing
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ProductPresentation
from .quality import BATCH_SIZE, MAX_PK, inspect_batch
from .quality_irc import CURSOR_SALT, InvalidIRCCursor, QualityAnchorNotFound, inspect_irc


@override_settings(STAFF_PORTAL_ENABLED=True)
class CatalogIRCInspectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fields = dict(name_fa='نام ساختگی محرمانه', name_en='Private synthetic name',
                          manufacturer='سازنده فرضی', strength='۵ میلی‌گرم', dosage_form='قرص',
                          package_description='۱۰ عدد', irc='۰۰۱', source_name='منبع ساختگی',
                          source_url='https://example.org/private', verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        cls.anchor = ProductPresentation.objects.create(**cls.fields, published=True)
        cls.other = ProductPresentation.objects.create(**{**cls.fields, 'irc': '001'}, published=False)
        User = get_user_model()
        cls.viewer = User.objects.create_user('irc-viewer', password='test-only-password', is_staff=True)
        cls.viewer.user_permissions.add(Permission.objects.get(content_type__app_label='catalog', codename='view_productpresentation'))
        cls.candidate_viewer = User.objects.create_user('irc-candidate-only', is_staff=True)
        cls.candidate_viewer.user_permissions.add(Permission.objects.get(content_type__app_label='catalog', codename='view_productcandidate'))
        cls.regular = User.objects.create_user('irc-nonstaff', is_staff=False)
        cls.regular.user_permissions.add(Permission.objects.get(content_type__app_label='catalog', codename='view_productpresentation'))
        cls.inactive = User.objects.create_user('irc-inactive', is_staff=True, is_active=False)
        cls.inactive.user_permissions.add(Permission.objects.get(content_type__app_label='catalog', codename='view_productpresentation'))
        cls.group_user = User.objects.create_user('irc-group', is_staff=True)
        group = Group.objects.create(name='irc-presentation-viewers')
        group.permissions.add(Permission.objects.get(content_type__app_label='catalog', codename='view_productpresentation'))
        cls.group_user.groups.add(group)

    def url(self, pk=None):
        return reverse('staff_catalog_quality_irc', args=[self.anchor.pk if pk is None else pk])

    def add_indexed(self, n):
        return ProductPresentation.objects.bulk_create([
            ProductPresentation(**{**self.fields, 'name_fa': f'نمونه محرمانه {i}'},
                                irc_normalized='001', published=(i % 2 == 0)) for i in range(n)
        ])

    def test_finds_indexed_matches_across_original_batch_boundaries(self):
        self.other.irc = ''; self.other.save(update_fields=['irc'])
        ProductPresentation.objects.bulk_create([
            ProductPresentation(**{**self.fields, 'irc': ''}, irc_normalized='', published=False)
            for _ in range(BATCH_SIZE)
        ])
        late = ProductPresentation.objects.create(**self.fields, published=False)
        first_batch = inspect_batch()
        self.assertNotIn('duplicate_irc_in_batch', first_batch['rows'][0]['issues'])
        report = inspect_irc(anchor_id=self.anchor.pk)
        self.assertEqual(report['rows'], [{'id': late.pk, 'status': 'consistent'}])
        self.assertEqual((report['consistent'], report['inconsistent'], report['next_cursor']), (1, 0, None))
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse('staff_catalog_quality')), self.url())
        response = self.client.get(self.url())
        self.assertContains(response, f'شناسه داخلی {late.pk}')
        self.assertContains(response, 'اثبات هویت')
        self.assertNotContains(response, self.fields['source_url'])
        self.assertNotContains(response, self.fields['name_fa'])

    def test_bounded_indexed_pages_and_signed_cursor_do_not_expose_code(self):
        self.add_indexed(104)
        found, cursor = [], ''
        for expected in [50, 50, 5]:
            with self.assertNumQueries(2):
                report = inspect_irc(anchor_id=self.anchor.pk, cursor=cursor)
            self.assertEqual(report['scanned'], expected)
            self.assertEqual(report['consistent'], expected)
            found += [item['id'] for item in report['rows']]
            cursor = report['next_cursor']
            if cursor:
                contents = signing.loads(cursor, salt=CURSOR_SALT)
                self.assertEqual(set(contents), {'anchor', 'code', 'last'})
                self.assertNotEqual(contents['code'], '001')
                self.assertNotIn('۰۰۱', cursor)
        self.assertIsNone(cursor)
        self.assertEqual(len(found), 105)
        self.assertEqual(found, sorted(set(found)))
        self.assertNotIn(self.anchor.pk, found)
        self.assertIn(self.other.pk, found)  # includes unpublished records

    def test_code_and_other_private_fields_are_not_rendered_or_embedded_in_cursor(self):
        code = 'SECRET-<script>alert(1)</script>'
        self.anchor.irc = code
        self.anchor.save(update_fields=['irc'])
        ProductPresentation.objects.bulk_create([
            ProductPresentation(**{**self.fields, 'irc': code}, irc_normalized=code.lower(), published=False)
            for _ in range(BATCH_SIZE + 1)
        ])
        report = inspect_irc(anchor_id=self.anchor.pk)
        self.assertNotIn(code, json.dumps(report))
        payload = signing.loads(report['next_cursor'], salt=CURSOR_SALT)
        self.assertNotIn(code.lower(), str(payload))
        self.client.force_login(self.viewer)
        response = self.client.get(self.url())
        self.assertNotContains(response, code)
        self.assertNotContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(response, self.fields['source_url'])

    def test_web_next_link_and_headers(self):
        self.add_indexed(50)
        self.client.force_login(self.viewer)
        response = self.client.get(self.url())
        report = response.context['report']
        self.assertEqual(report['scanned'], 50)
        self.assertIsNotNone(report['next_cursor'])
        self.assertContains(response, 'بررسی بخش بعد')
        from html.parser import HTMLParser
        class Links(HTMLParser):
            def __init__(self):
                super().__init__(); self.hrefs = []
            def handle_starttag(self, tag, attrs):
                if tag == 'a': self.hrefs.append(dict(attrs).get('href', ''))
        parser = Links(); parser.feed(response.content.decode())
        href = next(href for href in parser.hrefs if 'cursor=' in href)
        self.assertEqual(parse_qs(urlsplit(href).query)['cursor'], [report['next_cursor']])
        second = self.client.get(self.url() + href)
        self.assertEqual(second.context['report']['scanned'], 1)
        self.assertNotContains(second, 'بررسی بخش بعد')
        for r in [response, second]:
            self.assertEqual(r['Cache-Control'], 'private, no-store, max-age=0')
            self.assertEqual(r['X-Robots-Tag'], 'noindex, nofollow')
            self.assertEqual(r['Referrer-Policy'], 'same-origin')
            self.assertNotContains(r, self.fields['name_fa'])
            self.assertNotContains(r, self.fields['source_url'])

    def test_inconsistent_matching_index_is_not_reported_as_a_valid_clue(self):
        ProductPresentation.objects.filter(pk=self.other.pk).update(irc='002')
        damaged = ProductPresentation.objects.create(**self.fields, published=False)
        ProductPresentation.objects.filter(pk=damaged.pk).update(irc='bad\x01irc')
        report = inspect_irc(anchor_id=self.anchor.pk)
        self.assertEqual(report['consistent'], 0)
        self.assertEqual(report['inconsistent'], 2)
        self.assertTrue(all(item['status'] == 'inconsistent' for item in report['rows']))
        self.client.force_login(self.viewer)
        response = self.client.get(self.url())
        self.assertContains(response, 'این رکورد سرنخ تأییدشده نیست')
        self.assertNotContains(response, 'bad')
        self.assertNotContains(response, self.url(self.other.pk))

    def test_bad_or_absent_anchor_code_fails_closed_and_explains_limits(self):
        self.client.force_login(self.viewer)
        for irc, projection, state in [('', '', 'empty'), ('\u200d', '', 'empty'), ('001', '', 'invalid'),
                                       ('x\x01y', '001', 'invalid'), ('ﬃ' * 40, '001', 'invalid')]:
            with self.subTest(irc=ascii(irc)):
                ProductPresentation.objects.filter(pk=self.anchor.pk).update(irc=irc, irc_normalized=projection)
                report = inspect_irc(anchor_id=self.anchor.pk)
                self.assertEqual(report['status'], state)
                self.assertEqual(report['rows'], [])
                self.assertEqual(report['scanned'], 0)
                with self.assertRaises(InvalidIRCCursor): inspect_irc(anchor_id=self.anchor.pk, cursor='invalid')
                response = self.client.get(self.url())
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'نبود نتیجه به معنی یکتایی نیست' if state == 'empty' else 'بررسی متوقف شد')

    def test_missing_or_stale_indexes_are_not_silently_claimed_to_be_complete(self):
        ProductPresentation.objects.filter(pk=self.other.pk).update(irc_normalized='other')
        report = inspect_irc(anchor_id=self.anchor.pk)
        self.assertEqual(report['rows'], [])
        self.client.force_login(self.viewer)
        response = self.client.get(self.url())
        self.assertContains(response, 'نمایه‌های خراب ممکن است رکوردهای مرتبط را پنهان کنند')
        self.assertContains(response, 'نبود نتیجه به معنی یکتایی نیست')

    def test_cursor_tampering_scope_expiry_and_anchor_changes(self):
        self.add_indexed(50)
        with patch('django.core.signing.time.time', return_value=1000):
            token = inspect_irc(anchor_id=self.anchor.pk)['next_cursor']
        with patch('django.core.signing.time.time', return_value=1001):
            with self.assertRaises(InvalidIRCCursor): inspect_irc(anchor_id=self.other.pk, cursor=token)
            for bad in [token + 'x', '.' + token, 'x' * 513, None, 42]:
                with self.subTest(bad=repr(bad)), self.assertRaises(InvalidIRCCursor):
                    inspect_irc(anchor_id=self.anchor.pk, cursor=bad)
            for body in [{}, {'anchor': self.anchor.pk, 'code': 'x', 'last': True},
                         {'anchor': self.anchor.pk, 'code': '0' * 64, 'last': 1},
                         {'anchor': self.anchor.pk, 'code': '0' * 64, 'last': MAX_PK + 1}]:
                forged = signing.dumps(body, salt=CURSOR_SALT)
                with self.subTest(body=body), self.assertRaises(InvalidIRCCursor):
                    inspect_irc(anchor_id=self.anchor.pk, cursor=forged)
            ProductPresentation.objects.filter(pk=self.anchor.pk).update(irc='002', irc_normalized='002')
            with self.assertRaises(InvalidIRCCursor): inspect_irc(anchor_id=self.anchor.pk, cursor=token)
            ProductPresentation.objects.filter(pk=self.anchor.pk).update(irc='001', irc_normalized='001')
        with patch('django.core.signing.time.time', return_value=4601):
            with self.assertRaises(InvalidIRCCursor): inspect_irc(anchor_id=self.anchor.pk, cursor=token)

    def test_deleted_continuation_row_and_missing_anchor(self):
        self.add_indexed(50)
        report = inspect_irc(anchor_id=self.anchor.pk)
        last = report['rows'][-1]['id']
        ProductPresentation.objects.filter(pk=last).delete()
        self.assertEqual(inspect_irc(anchor_id=self.anchor.pk, cursor=report['next_cursor'])['scanned'], 1)
        for value in [0, -1, MAX_PK + 1, True, None, '1', 99999999]:
            with self.subTest(value=value), self.assertRaises(QualityAnchorNotFound): inspect_irc(anchor_id=value)
        self.client.force_login(self.viewer)
        for pk in [0, MAX_PK + 1, 99999999]:
            response = self.client.get(self.url(pk))
            self.assertEqual(response.status_code, 404)
            self.assertIn('no-store', response['Cache-Control'])

    def test_permission_method_and_gate(self):
        r = self.client.get(self.url())
        self.assertEqual(r.status_code, 302)
        self.assertIn('no-store', r['Cache-Control'])
        for user in [self.candidate_viewer, self.regular, self.inactive]:
            self.client.force_login(user)
            response = self.client.get(self.url())
            self.assertIn(response.status_code, (302, 403))
            self.assertNotContains(response, self.fields['name_fa'], status_code=response.status_code)
        for user in [self.viewer, self.group_user]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(self.url()).status_code, 200)
            self.assertEqual(self.client.head(self.url()).status_code, 200)
            self.assertEqual(self.client.post(self.url()).status_code, 405)
            self.assertEqual(self.client.get(self.url(), {'cursor': 'bad'}).status_code, 400)
        with self.settings(STAFF_PORTAL_ENABLED=False):
            self.assertEqual(self.client.get(self.url()).status_code, 404)

    def test_inspection_does_not_publish_or_change_public_results(self):
        ProductPresentation.objects.filter(pk=self.other.pk).update(name_fa='پیش‌نویس محرمانه خصوصی')
        params = {'q': '001'}
        before = self.client.get(reverse('search_api'), params).json()
        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self.url()).status_code, 200)
        after = self.client.get(reverse('search_api'), params).json()
        self.assertEqual(before, after)
        self.assertEqual([entry['id'] for entry in after['data']], [self.anchor.pk])
        self.assertNotContains(self.client.get(reverse('sitemap')), '/staff/catalog/quality/')
        self.assertEqual(self.client.get(reverse('presentation_api', args=[self.other.pk])).status_code, 404)

    def test_cli_and_service_read_only_and_no_unnecessary_data(self):
        before = list(ProductPresentation.objects.order_by('pk').values())
        output = io.StringIO()
        with patch('socket.create_connection', side_effect=AssertionError('network')):
            call_command('inspect_catalog_irc', anchor_id=self.anchor.pk, stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(result['rows'], [{'id': self.other.pk, 'status': 'consistent'}])
        self.assertNotIn(self.fields['source_url'], output.getvalue())
        self.assertNotIn(self.fields['name_fa'], output.getvalue())
        self.assertNotIn(self.fields['irc'], output.getvalue())
        self.assertEqual(list(ProductPresentation.objects.order_by('pk').values()), before)
        with self.assertRaises(CommandError): call_command('inspect_catalog_irc', anchor_id=0, stdout=io.StringIO())
        with self.assertRaises(CommandError): call_command('inspect_catalog_irc', anchor_id=self.anchor.pk, cursor='bad', stdout=io.StringIO())
