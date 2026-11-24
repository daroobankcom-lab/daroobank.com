"""Synthetic evidence-note bounds for selected claim reads."""
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import tests as fixtures
from .date_inspection import inspect_dates
from .models import SourceClaim
from .services import ReviewConflict, date_label, fingerprint, related_claims, review_claim


@override_settings(STAFF_PORTAL_ENABLED=True)
class BoundedClaimNoteTests(TestCase):
    claim = fixtures.SourceClaimTests.claim

    @classmethod
    def setUpTestData(cls):
        fixtures.SourceClaimTests.setUpTestData.__func__(cls)

    def assert_bounded_select(self, queries):
        selects = [q['sql'] for q in queries if 'FROM "sources_sourceclaim"' in q['sql'] and q['sql'].startswith('SELECT')]
        self.assertTrue(selects)
        for sql in selects:
            if 'SELECT 1 ' in sql or 'COUNT(' in sql:
                continue
            select = sql.rsplit(' FROM "sources_sourceclaim"', 1)[0].lower()
            self.assertIn('substring', select)
            self.assertNotRegex(select, r'(?:^select |, )"sources_sourceclaim"\."evidence_note"(?:,|$)')

    def test_oversized_note_is_never_fetched_or_reflected_in_detail_list_scan_and_related(self):
        claim = self.claim()
        SourceClaim.objects.filter(pk=claim.pk).update(evidence_note='آ' * 1_000_000 + 'source-note-canary')
        self.client.force_login(self.viewer)
        for route, args in [('staff_source_detail', [claim.pk]), ('staff_sources', []), ('staff_source_date_inspection', [])]:
            with self.subTest(route=route), CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse(route, args=args))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, 'source-note-canary')
            self.assertIn('no-store', response['Cache-Control'])
            self.assert_bounded_select(queries)
            if route == 'staff_source_detail':
                self.assertContains(response, 'شرح مدرک بیش از حد مجاز است؛ نمایش داده نمی‌شود')
                self.assertFalse(response.context['can_review'])
        with CaptureQueriesContext(connection) as queries:
            report = inspect_dates(category='invalid')
        self.assertEqual(report['rows'], [{'id': claim.pk, 'status': 'invalid'}])
        self.assert_bounded_select(queries)
        with CaptureQueriesContext(connection) as queries:
            summary = related_claims(self.viewer, claim.source_url)
        self.assertEqual(summary['items'][0]['date_label'], 'invalid')
        self.assert_bounded_select(queries)
        self.assertEqual(len(SourceClaim.objects.get(pk=claim.pk).evidence_note), 1_000_000 + len('source-note-canary'))

    def test_failed_forms_and_conflict_refresh_remain_bounded(self):
        claim = self.claim()
        review = review_claim(actor=self.reviewer, claim_id=claim.pk, decision='defer',
            reason='توضیح ساختگی برای بررسی بیشتر', expected_review=0, expected_hash=claim.payload_sha256)
        self.client.force_login(self.reviewer)
        def conflict(**kwargs):
            SourceClaim.objects.filter(pk=claim.pk).update(evidence_note='آ' * 1_000_000 + 'race-canary')
            raise ReviewConflict('تداخل ساختگی')
        with patch('sources.staff_views.review_claim', side_effect=conflict):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.post(reverse('staff_source_review', args=[claim.pk]), {
                    'decision': 'defer', 'reason': 'توضیح ساختگی برای بررسی بیشتر',
                    'expected_review': review.pk, 'expected_hash': claim.payload_sha256})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'شرح مدرک بیش از حد مجاز است؛ نمایش داده نمی‌شود', status_code=409)
        self.assertNotContains(response, 'race-canary', status_code=409)
        self.assertEqual(response.context['reviews'][0].claim_comparison, 'unknown')
        self.assertEqual(response.context['reviews'][0].technical_status, 'unavailable')
        self.assertFalse(response.context['can_review'])
        self.assert_bounded_select(queries)
        with CaptureQueriesContext(connection) as queries:
            invalid = self.client.post(reverse('staff_source_review', args=[claim.pk]), {})
        self.assertEqual(invalid.status_code, 400)
        self.assertNotContains(invalid, 'race-canary', status_code=400)
        self.assert_bounded_select(queries)

    def test_threshold_and_whitespace_preserve_invalid_classification_without_partial_validation(self):
        from .claim_reads import bounded_claim_notes, materialize_claim_note
        claim = self.claim()
        for note in ('آ' * 1000, 'آ' * 1001, 'x' * 12 + ' ' * 100_000 + 'last-canary'):
            data = {**self.data, 'evidence_note': note}
            SourceClaim.objects.filter(pk=claim.pk).update(evidence_note=note, payload_sha256=fingerprint(data))
            selected = bounded_claim_notes(SourceClaim.objects.filter(pk=claim.pk)).get()
            self.assertIn('evidence_note', selected.get_deferred_fields())
            self.assertEqual(len(selected._note_prefix), min(len(note), 1001))
            materialize_claim_note(selected)
            if len(note) > 1000:
                with patch('sources.services.validate_data', side_effect=AssertionError('partial note must not be validated')):
                    self.assertEqual(date_label(selected), 'invalid')
                self.assertTrue(selected.note_oversized)
                self.assertIsNone(selected.evidence_note)
            else:
                self.assertFalse(selected.note_oversized)
                self.assertEqual(selected.evidence_note, note)
                self.assertNotEqual(date_label(selected), 'invalid')

    def test_scan_and_related_lookahead_are_bounded_but_not_classified(self):
        from .claim_reads import bounded_claim_notes
        claims = [self.claim(owner=f'مالک فرضی {i}') for i in range(51)]
        SourceClaim.objects.filter(pk=claims[50].pk).update(evidence_note='ر' * 1_000_000 + 'sentinel-canary')
        with CaptureQueriesContext(connection) as queries:
            rows = list(bounded_claim_notes(SourceClaim.objects.order_by('pk'))[:51])
        self.assert_bounded_select(queries)
        self.assertEqual(rows[-1].pk, claims[50].pk)
        self.assertEqual(len(rows[-1]._note_prefix), 1001)
        first = inspect_dates(category='invalid')
        self.assertEqual((first['scanned'], first['rows'], first['next_after']), (50, [], claims[49].pk))
        second = inspect_dates(after=first['next_after'], category='invalid')
        self.assertEqual(second['rows'], [{'id': claims[50].pk, 'status': 'invalid'}])
        SourceClaim.objects.filter(pk=claims[-6].pk).update(evidence_note='ر' * 1_000_000 + 'related-sentinel')
        with CaptureQueriesContext(connection) as queries:
            summary = related_claims(self.viewer, claims[0].source_url)
        self.assert_bounded_select(queries)
        self.assertTrue(summary['limited'])
        self.assertEqual(len(summary['items']), 5)
