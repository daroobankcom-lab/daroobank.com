"""Synthetic, read-only source date scan tests on PostgreSQL."""
from datetime import date, datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from sources.date_inspection import BATCH_SIZE, MAX_PK, InvalidDateInspection, inspect_dates
from sources.models import SourceClaim
from sources.services import fingerprint

TODAY = date(2026, 6, 1)


@override_settings(STAFF_PORTAL_ENABLED=True)
class SourceDateInspectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.viewer = users.objects.create_user('date-viewer', is_staff=True)
        cls.add_only = users.objects.create_user('date-add', is_staff=True)
        cls.regular = users.objects.create_user('date-nonstaff')
        cls.inactive = users.objects.create_user('date-inactive', is_staff=True, is_active=False)
        group = Group.objects.create(name='date-viewers')
        group.permissions.add(Permission.objects.get(content_type__app_label='sources', codename='view_sourceclaim'))
        cls.viewer.groups.add(group)
        cls.add_only.user_permissions.add(Permission.objects.get(content_type__app_label='sources', codename='add_sourceclaim'))
        cls.regular.groups.add(group)
        rows = []
        for i in range(103):
            if i < 50:
                start, end = date(2026, 6, 2), None
            elif i < 100:
                start, end = TODAY, TODAY
            elif i == 100:
                start, end = None, date(2026, 5, 31)
            else:
                start, end = None, None
            data = {'source_name': '<script>synthetic secret</script>', 'source_url': f'https://example.org/{i}',
                    'owner': f'synthetic owner {i}', 'evidence_url': 'https://example.org/evidence',
                    'evidence_note': '', 'claims_collection': True, 'claims_storage': False,
                    'claims_publication': False, 'starts_on': start, 'expires_on': end}
            rows.append(SourceClaim(**data, payload_sha256=fingerprint(data), recorded_by=cls.viewer))
        SourceClaim.objects.bulk_create(rows)
        ids = list(SourceClaim.objects.order_by('pk').values_list('pk', flat=True))
        cls.ids = ids
        SourceClaim.objects.filter(pk=ids[-1]).update(owner='tampered synthetic')

    def test_bounded_scan_and_filter_advance_over_empty_batches(self):
        before = list(SourceClaim.objects.order_by('pk').values_list('pk', 'owner', 'payload_sha256'))
        with self.assertNumQueries(1):
            first = inspect_dates(category='expired', today=TODAY)
        self.assertEqual(first['scanned'], BATCH_SIZE)
        self.assertEqual(first['rows'], [])
        self.assertEqual(first['next_after'], self.ids[49])
        with self.assertNumQueries(1):
            second = inspect_dates(after=first['next_after'], category='expired', today=TODAY)
        self.assertEqual(second['scanned'], BATCH_SIZE)
        self.assertEqual(second['rows'], [])
        self.assertEqual(second['next_after'], self.ids[99])
        third = inspect_dates(after=second['next_after'], category='expired', today=TODAY)
        self.assertEqual(third['scanned'], 3)
        self.assertEqual(third['rows'], [{'id': self.ids[100], 'status': 'expired'}])
        self.assertIsNone(third['next_after'])
        all_rows = inspect_dates(after=self.ids[99], today=TODAY)
        self.assertEqual([r['status'] for r in all_rows['rows']], ['expired', 'unknown', 'invalid'])
        exactly_one_batch = inspect_dates(after=self.ids[52], today=TODAY)
        self.assertEqual(exactly_one_batch['scanned'], BATCH_SIZE)
        self.assertIsNone(exactly_one_batch['next_after'])
        self.assertEqual(inspect_dates(after=MAX_PK, today=TODAY)['rows'], [])
        self.assertEqual(list(SourceClaim.objects.order_by('pk').values_list('pk', 'owner', 'payload_sha256')), before)

    def test_live_scan_does_not_revisit_already_scanned_claims(self):
        first = inspect_dates(today=TODAY)
        self.assertEqual(first['rows'][0]['status'], 'future')
        SourceClaim.objects.filter(pk=self.ids[0]).update(owner='synthetic change after first scan')
        following = inspect_dates(after=first['next_after'], category='invalid', today=TODAY)
        self.assertNotIn(self.ids[0], [row['id'] for row in following['rows']])
        restarted = inspect_dates(category='invalid', today=TODAY)
        self.assertEqual(restarted['rows'], [{'id': self.ids[0], 'status': 'invalid'}])
        # The local date can also change the status without any record change.
        self.assertEqual(inspect_dates(today=date(2026, 6, 2))['rows'][1]['status'], 'unknown')

    def test_invalid_service_parameters_do_not_query(self):
        cases = [{'after': -1}, {'after': MAX_PK + 1}, {'after': True}, {'after': '1'},
                 {'category': '<script>'}, {'category': None}, {'today': datetime(2026, 6, 1)}]
        for case in cases:
            with self.subTest(case=case), self.assertNumQueries(0), self.assertRaises(InvalidDateInspection):
                inspect_dates(**case)

    def test_permissions_methods_inputs_and_private_headers(self):
        url = reverse('staff_source_date_inspection')
        anonymous = self.client.get(url)
        self.assertEqual(anonymous.status_code, 302)
        self.assertEqual(anonymous['Cache-Control'], 'private, no-store, max-age=0')
        for user in (self.add_only, self.regular):
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.inactive)
        self.assertNotEqual(self.client.get(url).status_code, 200)
        self.client.force_login(self.viewer)
        for params in [{'after': ''}, {'after': '-1'}, {'after': 'x'}, {'after': '1e2'},
                       {'after': '1' * 20}, {'after': str(MAX_PK + 1)},
                       {'after': '۹۲۲۳۳۷۲۰۳۶۸۵۴۷۷۵۸۰۸'}, {'after': '१'},
                       {'category': 'EXPIRED'}, {'category': '<script>'}]:
            with self.subTest(params=params):
                response = self.client.get(url, params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        for raw, expected in [('١', 1), ('۰' * 19, 0), ('۱2٣', 123), ('۹۲۲۳۳۷۲۰۳۶۸۵۴۷۷۵۸۰۷', MAX_PK),
                              (str(MAX_PK), MAX_PK)]:
            response = self.client.get(url, {'after': raw})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['report']['after'], expected)
        html = self.client.get(url)
        self.assertContains(html, 'aria-describedby="after-hint"')
        self.assertContains(html, 'pattern="[0-9۰-۹٠-٩]{1,19}"')
        self.assertContains(html, '9223372036854775807')
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.head(url).status_code, 200)
        with self.settings(STAFF_PORTAL_ENABLED=False):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertNotContains(self.client.get(reverse('home')), url)
        self.assertNotContains(self.client.get(reverse('sitemap')), url)

    def test_invalid_scan_error_is_private_nonreflecting_and_restarts(self):
        url = reverse('staff_source_date_inspection')
        self.client.force_login(self.add_only)
        self.assertEqual(self.client.get(url, {'after': 'synthetic-canary<script>'}).status_code, 403)
        self.client.force_login(self.viewer)
        with patch('sources.staff_views.inspect_dates') as scan:
            for params in ({'after': 'synthetic-canary<script>'}, {'after': str(MAX_PK + 1)},
                           {'category': 'synthetic-canary<script>'}):
                for method in (self.client.get, self.client.head):
                    with self.subTest(params=params, method=method.__name__):
                        response = method(url, params)
                        self.assertEqual(response.status_code, 400)
                        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                        self.assertEqual(response['Referrer-Policy'], 'same-origin')
                        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                        self.assertNotIn(b'synthetic-canary', response.content)
                        if method == self.client.get:
                            self.assertContains(response, 'درخواست بازرسی معتبر نیست', status_code=400)
                            self.assertContains(response, f'href="{url}"', status_code=400)
                            self.assertNotContains(response, '&lt;script&gt;', status_code=400)
                        else:
                            self.assertEqual(response.content, b'')
            scan.assert_not_called()
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_localized_starting_id_selects_same_batch_and_cursor(self):
        self.client.force_login(self.viewer)
        url = reverse('staff_source_date_inspection')
        ascii_id = str(self.ids[49])
        persian_id = ascii_id.translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))
        arabic_id = ascii_id.translate(str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩'))
        with patch('sources.date_inspection.timezone.localdate', return_value=TODAY):
            reports = [self.client.get(url, {'after': raw, 'category': 'expired'}).context['report']
                       for raw in (ascii_id, persian_id, arabic_id)]
        self.assertEqual(reports[0], reports[1])
        self.assertEqual(reports[0], reports[2])
        self.assertEqual(reports[0]['scanned'], 50)
        self.assertEqual(reports[0]['next_after'], self.ids[99])

    def test_html_linked_batches_hide_claim_text_and_never_fetch(self):
        self.client.force_login(self.viewer)
        url = reverse('staff_source_date_inspection')
        self.assertContains(self.client.get(reverse('staff_sources')), f'href="{url}"')
        with patch('sources.date_inspection.timezone.localdate', return_value=TODAY), \
             patch('socket.create_connection', side_effect=AssertionError('unexpected network')):
            first = self.client.get(url, {'category': 'expired'})
            self.assertEqual(first.status_code, 200)
            self.assertEqual(first['Cache-Control'], 'private, no-store, max-age=0')
            self.assertEqual(first['Referrer-Policy'], 'same-origin')
            self.assertContains(first, 'در این بخش نتیجه‌ای مطابق فیلتر دیده نشد')
            self.assertContains(first, f'?after={self.ids[49]}&amp;category=expired')
            self.assertNotContains(first, 'synthetic secret')
            self.assertNotContains(first, 'example.org')
            second = self.client.get(url, {'after': self.ids[49], 'category': 'expired'})
            self.assertContains(second, f'?after={self.ids[99]}&amp;category=expired')
            third = self.client.get(url, {'after': self.ids[99], 'category': 'expired'})
            self.assertContains(third, reverse('staff_source_detail', args=[self.ids[100]]))
            self.assertNotContains(third, reverse('staff_source_detail', args=[self.ids[101]]))
            self.assertNotContains(third, 'بررسی بخش بعد')
            self.assertNotContains(third, 'synthetic secret')
