"""Synthetic CLI payload checks, not price/source validation or authorization."""
import hashlib
import io
import json
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from catalog.models import ProductPresentation
from .importer import stage_csv, suggest_product
from .models import PriceCandidate
from .test_workflow import csv_bytes


class CandidateListIntegrityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(name_fa='فرآورده ساختگی', manufacturer='سازنده فرضی',
            strength='1 mg', dosage_form='قرص', package_description='10 عدد', irc='001',
            source_name='منبع ساختگی', source_url='https://example.org/product')
        cls.row = dict(source_record_id='synthetic-record', irc='001', manufacturer='سازنده فرضی',
            strength='1 mg', dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
            category='retail', unit='package', effective_date='', source_published_date='')
        stage_csv(io.BytesIO(csv_bytes([cls.row])), 'منبع ساختگی', 'https://example.org/feed',
                  commit=True, rights_attested=True)
        cls.candidate = PriceCandidate.objects.get()

    def listing(self, **kwargs):
        output = io.StringIO()
        call_command('list_price_candidates', stdout=output, **kwargs)
        return output.getvalue(), json.loads(output.getvalue())

    def test_consistent_candidate_preserves_normal_output_and_marks_scope(self):
        output, report = self.listing()
        self.assertTrue(output.isascii())
        item = report['data'][0]
        self.assertEqual(item['payload_status'], 'consistent')
        self.assertEqual(item['source_fields'], self.row)
        self.assertEqual(item['amount_rial'], 100)
        self.assertEqual(item['current_suggestion'], {'match_status': 'suggested', 'suggested_product_id': self.product.pk})
        # This CLI-created row has no stager; consistency is not review eligibility.
        self.assertIsNone(self.candidate.staged_by_id)

    def test_changed_derived_amount_suppresses_payload_and_matching(self):
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(amount_rial=101)
        with patch('pricing.management.commands.list_price_candidates.suggest_product', wraps=suggest_product) as match:
            raw, report = self.listing()
        match.assert_not_called()
        self.assertEqual(report['data'], [{'id': self.candidate.pk, 'review_required': True,
            'payload_status': 'invalid', 'current_suggestion': {'match_status': 'invalid', 'suggested_product_id': None}}])
        self.assertNotIn('synthetic-record', raw)
        self.assertNotIn('example.org', raw)
        self.assertEqual(PriceCandidate.objects.get(pk=self.candidate.pk).amount_rial, 101)

    def test_invalid_row_counts_against_limit_and_status_filters_original_status(self):
        second = {**self.row, 'source_record_id': 'second-record', 'irc': '999'}
        stage_csv(io.BytesIO(csv_bytes([second])), 'منبع ساختگی', 'https://example.org/feed',
                  commit=True, rights_attested=True)
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(amount_rial=101)
        _, first = self.listing(limit=1)
        self.assertEqual([entry['payload_status'] for entry in first['data']], ['invalid'])
        _, all_rows = self.listing(limit=2)
        self.assertEqual([entry['payload_status'] for entry in all_rows['data']], ['invalid', 'consistent'])
        _, suggested = self.listing(status='suggested')
        self.assertEqual([entry['id'] for entry in suggested['data']], [self.candidate.pk])
        _, unmatched = self.listing(status='unmatched')
        self.assertEqual(unmatched['data'][0]['source_record_id'], 'second-record')

    def test_coherent_recomputation_is_not_authenticity_or_confidentiality(self):
        fields = {**self.row, 'source_record_id': 'coherent-canary'}
        source_name = 'منبع ساختگی'
        encoded = json.dumps({'source_name': source_name, 'fields': fields}, sort_keys=True,
                             ensure_ascii=False, separators=(',', ':')).encode('utf-8')
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(
            source_fields=fields, source_record_id=fields['source_record_id'],
            source_url='https://example.org/changed', payload_sha256=hashlib.sha256(encoded).hexdigest())
        raw, report = self.listing()
        self.assertEqual(report['data'][0]['payload_status'], 'consistent')
        self.assertIn('coherent-canary', raw)
        self.assertIn('https://example.org/changed', raw)

    def test_malformed_or_tampered_payload_does_not_echo_canaries(self):
        for fields in ({**self.row, 'extra': 'private-canary'},
                       {**self.row, 'manufacturer': 'private-canary'},
                       ['private-canary']):
            with self.subTest(fields=fields):
                PriceCandidate.objects.filter(pk=self.candidate.pk).update(source_fields=fields)
                with patch('pricing.management.commands.list_price_candidates.suggest_product', wraps=suggest_product) as match:
                    raw, report = self.listing(status='suggested')
                self.assertNotIn('private-canary', raw)
                self.assertEqual(report['data'][0]['payload_status'], 'invalid')
                self.assertEqual(report['data'][0]['current_suggestion']['match_status'], 'invalid')
                match.assert_not_called()
