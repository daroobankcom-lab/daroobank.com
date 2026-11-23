import io
import json
from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import ProductPresentation
from .quality import BATCH_SIZE, MAX_PK, QualityError, inspect_batch


@override_settings(STAFF_PORTAL_ENABLED=True)
class CatalogQualityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fields = dict(name_fa='نمونه ساختگی', name_en='Sample', manufacturer='شرکت نمونه',
                          strength='۵ میلی‌گرم', dosage_form='قرص', package_description='۱۰ عدد', irc='۰۰۱',
                          source_name='منبع', source_url='https://example.org/item',
                          verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        cls.public = ProductPresentation.objects.create(**cls.fields, published=True)
        cls.draft = ProductPresentation.objects.create(**{**cls.fields, 'name_fa': 'پیش‌نویس محرمانه'}, published=False)
        cls.user = get_user_model().objects.create_user('quality', password='test-password-123', is_staff=True)
        cls.user.user_permissions.add(Permission.objects.get(codename='view_productpresentation'))
        cls.candidate_user = get_user_model().objects.create_user('candidate', password='test-password-123', is_staff=True)
        cls.candidate_user.user_permissions.add(Permission.objects.get(codename='view_productcandidate'))
        cls.group_user = get_user_model().objects.create_user('group-quality', password='test-password-123', is_staff=True)
        group = Group.objects.create(name='inspectors')
        group.permissions.add(Permission.objects.get(codename='view_productpresentation'))
        cls.group_user.groups.add(group)
        cls.not_staff = get_user_model().objects.create_user('not-staff', is_staff=False)
        cls.not_staff.user_permissions.add(Permission.objects.get(codename='view_productpresentation'))
        cls.inactive = get_user_model().objects.create_user('inactive', is_staff=True, is_active=False)
        cls.inactive.user_permissions.add(Permission.objects.get(codename='view_productpresentation'))

    def test_batch_read_only_and_page_local_duplicate_clue(self):
        before = list(ProductPresentation.objects.values())
        report = inspect_batch()
        self.assertEqual(report['scanned'], 2)
        self.assertEqual(report['issue_rows'], 2)
        self.assertEqual(report['rows'][0]['public_filter'], 'passes')
        self.assertEqual(report['rows'][1]['public_filter'], 'blocked')
        self.assertEqual(report['rows'][0]['issues'], ['duplicate_irc_in_batch'])
        self.assertEqual(report['rows'][1]['issues'], ['duplicate_irc_in_batch'])
        self.assertEqual(ProductPresentation.objects.count(), 2)
        self.assertEqual(list(ProductPresentation.objects.values()), before)
        # A different chunk cannot claim a global duplicate check.
        self.assertEqual(inspect_batch(after=self.public.pk)['rows'][0]['issues'], [])

    def test_projection_drift_source_hygiene_and_eligibility(self):
        ProductPresentation.objects.filter(pk=self.public.pk).update(
            name_fa='نام تغییر یافته', irc='009', source_url='https://example.org/item?token=hidden')
        row = inspect_batch()['rows'][0]
        self.assertEqual(row['public_filter'], 'passes')  # internal source hygiene is a stricter diagnostic only
        self.assertEqual(row['issues'], ['search_projection', 'irc_projection', 'weak_source_url'])
        ProductPresentation.objects.filter(pk=self.public.pk).update(source_name=' ')
        row = inspect_batch()['rows'][0]
        self.assertEqual(row['public_filter'], 'blocked')
        self.assertIn('published_but_filtered', row['issues'])
        self.assertNotIn('token', json.dumps(row))

    def test_corrupt_text_is_not_rendered_and_eligibility_unknown(self):
        ProductPresentation.objects.filter(pk=self.public.pk).update(name_fa='secret\x01<bad>')
        row = inspect_batch()['rows'][0]
        self.assertEqual(row['public_filter'], 'unknown')
        self.assertEqual(row['issues'], ['invalid_text'])
        self.client.force_login(self.user)
        response = self.client.get(reverse('staff_catalog_quality'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'secret')
        self.assertContains(response, 'نامشخص')

    def test_bounded_forward_scan_and_parameter_validation(self):
        ProductPresentation.objects.bulk_create([
            ProductPresentation(**{**self.fields, 'name_fa': f'fixture-{i}'}, published=False)
            for i in range(BATCH_SIZE)
        ])
        first = inspect_batch()
        self.assertEqual(first['scanned'], BATCH_SIZE)
        self.assertEqual(first['next_after'], first['rows'][-1]['id'])
        last = inspect_batch(after=first['next_after'])
        self.assertEqual(last['scanned'], 2)
        self.assertIsNone(last['next_after'])
        self.assertTrue(set(x['id'] for x in first['rows']).isdisjoint(x['id'] for x in last['rows']))
        for val in [-1, MAX_PK + 1, True, '1', None]:
            with self.subTest(val=val), self.assertRaises(QualityError): inspect_batch(after=val)
        self.client.force_login(self.user)
        for val in ['', '-1', '+1', ' 1', '१', '۱e2', '1e2', '1'*100, str(MAX_PK + 1), '۹۲۲۳۳۷۲۰۳۶۸۵۴۷۷۵۸۰۸', 'x']:
            self.assertEqual(self.client.get(reverse('staff_catalog_quality'), {'after': val}).status_code, 400)
        for raw, expected in [('١', 1), ('۰' * 19, 0), ('۱2٣', 123), ('۹۲۲۳۳۷۲۰۳۶۸۵۴۷۷۵۸۰۷', MAX_PK),
                              (str(MAX_PK), MAX_PK)]:
            response = self.client.get(reverse('staff_catalog_quality'), {'after': raw})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context['report']['after'], expected)
        html = self.client.get(reverse('staff_catalog_quality'))
        self.assertContains(html, 'aria-describedby="after-hint"')
        self.assertContains(html, 'pattern="[0-9۰-۹٠-٩]{1,19}"')
        self.assertContains(html, '9223372036854775807')

    def test_invalid_scan_error_is_private_nonreflecting_and_restarts(self):
        url = reverse('staff_catalog_quality')
        self.client.force_login(self.candidate_user)
        self.assertEqual(self.client.get(url, {'after': 'synthetic-canary<script>'}).status_code, 403)
        self.client.force_login(self.user)
        with patch('catalog.quality_views.inspect_batch') as scan:
            for value in ('synthetic-canary<script>', '', str(MAX_PK + 1)):
                for method in (self.client.get, self.client.head):
                    with self.subTest(value=value, method=method.__name__):
                        response = method(url, {'after': value})
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

    def test_localized_starting_id_selects_same_batch(self):
        self.client.force_login(self.user)
        url = reverse('staff_catalog_quality')
        ascii_id = str(self.public.pk)
        persian_id = ascii_id.translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))
        arabic_id = ascii_id.translate(str.maketrans('0123456789', '٠١٢٣٤٥٦٧٨٩'))
        reports = [self.client.get(url, {'after': raw}).context['report'] for raw in (ascii_id, persian_id, arabic_id)]
        self.assertEqual(reports[0], reports[1])
        self.assertEqual(reports[0], reports[2])
        self.assertEqual([row['id'] for row in reports[0]['rows']], [self.draft.pk])

    def test_next_link_and_duplicates_across_batch_boundary_are_not_claimed(self):
        self.draft.irc = ''
        self.draft.save(update_fields=['irc'])
        for i in range(BATCH_SIZE - 2):
            ProductPresentation.objects.create(**{**self.fields, 'name_fa': f'fixture-{i}', 'irc': ''}, published=False)
        late = ProductPresentation.objects.create(**self.fields, published=False)
        first = inspect_batch()
        self.assertNotIn('duplicate_irc_in_batch', first['rows'][0]['issues'])
        second = inspect_batch(after=first['next_after'])
        self.assertEqual(second['rows'][0]['id'], late.pk)
        self.assertNotIn('duplicate_irc_in_batch', second['rows'][0]['issues'])
        self.client.force_login(self.user)
        response = self.client.get(reverse('staff_catalog_quality'))
        self.assertContains(response, f'?after={first["next_after"]}')
        response = self.client.get(reverse('staff_catalog_quality'), {'after': first['next_after']})
        self.assertContains(response, f'شناسه داخلی {late.pk}')
        self.assertNotContains(response, 'بررسی بخش بعد')

    def test_web_permissions_private_headers_and_methods(self):
        url = reverse('staff_catalog_quality')
        anonymous = self.client.get(url)
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn('/staff/login/', anonymous['Location'])
        for user in (self.candidate_user, self.not_staff, self.inactive):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertIn(response.status_code, (302, 403))
            self.assertNotContains(response, 'پیش‌نویس محرمانه', status_code=response.status_code)
        for user in (self.user, self.group_user):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'پیش‌نویس محرمانه')
            self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
            self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
            self.assertEqual(response['Referrer-Policy'], 'same-origin')
            self.assertEqual(self.client.head(url).status_code, 200)
            self.assertEqual(self.client.post(url).status_code, 405)
            self.assertEqual(self.client.put(url).status_code, 405)
        with self.settings(STAFF_PORTAL_ENABLED=False):
            self.assertEqual(self.client.get(url).status_code, 404)
        # Possessing the quality permission does not grant candidate access.
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('staff_products')).status_code, 403)

    def test_login_landing_for_quality_only_user_and_navigation(self):
        self.client.logout()
        response = self.client.post(reverse('staff_login'), {'username': 'quality', 'password': 'test-password-123'})
        self.assertRedirects(response, reverse('staff_workspace'))
        self.client.force_login(self.candidate_user)
        self.assertNotContains(self.client.get(reverse('staff_products')), reverse('staff_catalog_quality'))
        self.candidate_user.user_permissions.add(Permission.objects.get(codename='view_productpresentation'))
        self.client.force_login(get_user_model().objects.get(pk=self.candidate_user.pk))
        self.assertContains(self.client.get(reverse('staff_products')), reverse('staff_catalog_quality'))

    def test_cli_has_no_names_or_urls_and_never_writes(self):
        out = io.StringIO()
        with patch('socket.create_connection', side_effect=AssertionError('network')):
            call_command('inspect_catalog_quality', stdout=out)
        data = json.loads(out.getvalue())
        self.assertEqual(data['scanned'], 2)
        self.assertNotIn('example.org', out.getvalue())
        self.assertNotIn('نمونه ساختگی', out.getvalue())
        self.assertNotIn('پیش‌نویس محرمانه', out.getvalue())
        self.assertEqual(ProductPresentation.objects.count(), 2)
        with self.assertRaises(CommandError):
            call_command('inspect_catalog_quality', after=-1, stdout=io.StringIO())
