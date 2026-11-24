"""Selected catalog-quality reads handle oversized stored search projections."""
import io
import json
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import ProductPresentation
from .quality import MAX_INSPECTED_SEARCH_LENGTH, inspect_batch


@override_settings(DEBUG=True)
class QualityBoundedProjectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='فرآورده ساختگی', name_en='Synthetic', manufacturer='سازنده فرضی',
            strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='123',
            source_name='منبع', source_url='https://example.org/synthetic',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True)

    def test_oversized_projection_reports_unknown_without_exposing_or_transferring_whole_text(self):
        original = 'پ' * 1_000_000 + '\x01synthetic-private-canary'
        ProductPresentation.objects.filter(pk=self.product.pk).update(search_text=original)
        with CaptureQueriesContext(connection) as queries:
            report = inspect_batch()
        self.assertEqual(len(queries), 1)
        select = queries[0]['sql'].split(' FROM ', 1)[0].lower()
        self.assertIn('substring(', select)
        self.assertNotRegex(select, r'(?:^select |, )"catalog_productpresentation"\."search_text"(?:,|$)')
        self.assertEqual(report['rows'][0]['public_filter'], 'unknown')
        self.assertIn('oversized_search_projection', report['rows'][0]['issues'])
        self.assertNotIn('synthetic-private-canary', json.dumps(report))
        self.assertEqual(ProductPresentation.objects.get(pk=self.product.pk).search_text, original)

    @override_settings(STAFF_PORTAL_ENABLED=True)
    def test_private_page_and_command_report_fixed_warning_without_payload(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(
            search_text='s' * (MAX_INSPECTED_SEARCH_LENGTH + 100) + 'private-synthetic-canary')
        user = get_user_model().objects.create_user('synthetic-quality-operator', is_staff=True)
        user.user_permissions.add(Permission.objects.get(content_type__app_label='catalog',
                                                         codename='view_productpresentation'))
        self.client.force_login(user)
        url = reverse('staff_catalog_quality')
        for method in (self.client.get, self.client.head):
            response = method(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
            self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
            self.assertNotIn(b'private-synthetic-canary', response.content)
            if method == self.client.get:
                self.assertContains(response, 'شاخص جست‌وجو برای این بازرسی بیش از حد طولانی است')
                self.assertContains(response, 'نامشخص')
        output = io.StringIO()
        call_command('inspect_catalog_quality', stdout=output)
        self.assertNotIn('private-synthetic-canary', output.getvalue())
        self.assertIn('oversized_search_projection', json.loads(output.getvalue())['rows'][0]['issues'])

    def test_boundary_and_control_handling(self):
        maximum = MAX_INSPECTED_SEARCH_LENGTH
        for size in (maximum - 1, maximum, maximum + 1):
            with self.subTest(size=size):
                ProductPresentation.objects.filter(pk=self.product.pk).update(search_text='آ' * size)
                row = inspect_batch()['rows'][0]
                if size > maximum:
                    self.assertEqual(row['public_filter'], 'unknown')
                    self.assertEqual(row['issues'], ['oversized_search_projection'])
                else:
                    self.assertEqual(row['public_filter'], 'passes')
                    self.assertEqual(row['issues'], ['search_projection'])
        ProductPresentation.objects.filter(pk=self.product.pk).update(search_text='آ' * maximum + '\x01extra')
        row = inspect_batch()['rows'][0]
        self.assertEqual(row['public_filter'], 'unknown')
        self.assertIn('invalid_text', row['issues'])
        self.assertIn('oversized_search_projection', row['issues'])
