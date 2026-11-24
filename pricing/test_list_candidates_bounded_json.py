"""Synthetic local price-list CLI avoids transferring oversized JSON payloads."""
from unittest.mock import patch

from django.db import connection
from django.db.models import JSONField, TextField, Value
from django.db.models.functions import Cast, Length
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .models import PriceCandidate
from . import test_list_candidates_integrity as fixtures


class CandidateListBoundedJsonTests(TestCase):
    listing = fixtures.CandidateListIntegrityTests.listing

    @classmethod
    def setUpTestData(cls):
        fixtures.CandidateListIntegrityTests.setUpTestData.__func__(cls)

    def test_oversized_json_is_uninspected_without_validator_matching_or_output(self):
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(source_fields={'secret-canary': 'آ' * 1_000_000})
        with patch('pricing.management.commands.list_price_candidates.ensure_candidate_integrity',
                   side_effect=AssertionError('oversized candidate must not be validated')), \
             patch('pricing.management.commands.list_price_candidates.suggest_product',
                   side_effect=AssertionError('oversized candidate must not be matched')):
            with CaptureQueriesContext(connection) as queries:
                raw, report = self.listing(status='suggested', limit=1)
        self.assertEqual(report['data'], [{'id': self.candidate.pk, 'review_required': True,
            'payload_status': 'oversized', 'current_suggestion': {'match_status': 'unknown', 'suggested_product_id': None}}])
        self.assertTrue(raw.isascii())
        self.assertNotIn('secret-canary', raw)
        self.assertNotIn('example.org', raw)
        selects = [q['sql'] for q in queries if 'FROM "pricing_pricecandidate"' in q['sql']]
        self.assertEqual(len(selects), 1)
        selected = selects[0].split(' FROM ', 1)[0].lower()
        self.assertIn('case', selected)
        self.assertNotRegex(selected, r'(?:^select |, )"pricing_pricecandidate"\."source_fields"(?:,|$)')
        self.assertEqual(PriceCandidate.objects.count(), 1)

    def test_exact_json_text_boundaries_and_null_are_distinct(self):
        for length in (65536, 65537):
            PriceCandidate.objects.filter(pk=self.candidate.pk).update(source_fields={'x': 'آ' * (length - len('{"x": ""}'))})
            actual = PriceCandidate.objects.annotate(n=Length(Cast('source_fields', TextField()))).get(pk=self.candidate.pk).n
            self.assertEqual(actual, length)
            _, report = self.listing()
            row = report['data'][0]
            self.assertEqual(row['payload_status'], 'invalid' if length == 65536 else 'oversized')
            self.assertEqual(row['current_suggestion']['match_status'], 'invalid' if length == 65536 else 'unknown')
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(source_fields=Value(None, output_field=JSONField()))
        _, report = self.listing()
        self.assertEqual(report['data'][0]['payload_status'], 'invalid')

    def test_oversized_row_counts_towards_limit_and_stored_status_filter(self):
        import io
        from .importer import stage_csv
        from .test_workflow import csv_bytes
        stage_csv(io.BytesIO(csv_bytes([{**self.row, 'source_record_id': 'second', 'irc': '999'}])),
                  'منبع ساختگی', 'https://example.org/feed', commit=True, rights_attested=True)
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(source_fields={'canary': 'آ' * 100_000})
        _, first = self.listing(limit=1)
        self.assertEqual([r['payload_status'] for r in first['data']], ['oversized'])
        _, both = self.listing(limit=2)
        self.assertEqual([r['payload_status'] for r in both['data']], ['oversized', 'consistent'])
        _, suggested = self.listing(status='suggested')
        self.assertEqual([r['id'] for r in suggested['data']], [self.candidate.pk])
        _, unmatched = self.listing(status='unmatched')
        self.assertEqual(unmatched['data'][0]['source_record_id'], 'second')
