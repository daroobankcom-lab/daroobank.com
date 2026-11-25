"""Synthetic staff pages should not materialize stored suggestion objects they do not use."""
import io
from datetime import datetime, timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog.models import ProductPresentation
from .importer import stage_csv
from .models import PriceCandidate
from .test_workflow import csv_bytes


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffCandidateQueryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user('candidate-query-staff', is_staff=True)
        cls.staff.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
            codename__in=['view_pricecandidate', 'add_pricecandidate']))
        cls.product = ProductPresentation.objects.create(name_fa='فرآورده ساختگی', manufacturer='سازنده فرضی',
            strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001',
            source_name='منبع ساختگی', source_url='https://example.org/product',
            published=True, verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
        row = dict(source_record_id='test', irc='001', manufacturer='سازنده فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
            unit='package', effective_date='', source_published_date='')
        stage_csv(io.BytesIO(csv_bytes([row])), 'منبع ساختگی', 'https://example.org/feed',
                  commit=True, rights_attested=True, staged_by=cls.staff)
        cls.candidate = PriceCandidate.objects.get()

    def test_queue_and_detail_do_not_join_stored_suggested_product(self):
        self.client.force_login(self.staff)
        for route, args in (('staff_prices', []), ('staff_price_detail', [self.candidate.pk])):
            with self.subTest(route=route), CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse(route, args=args))
            self.assertEqual(response.status_code, 200)
            candidate_reads = [q['sql'] for q in queries if 'FROM "pricing_pricecandidate"' in q['sql']]
            self.assertTrue(candidate_reads)
            self.assertFalse(any('JOIN "catalog_productpresentation"' in sql for sql in candidate_reads))
        # The detail still computes a separate current suggestion from current data.
        self.assertContains(response, 'فرآورده ساختگی')
