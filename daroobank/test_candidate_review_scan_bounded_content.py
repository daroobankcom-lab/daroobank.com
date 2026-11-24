"""Synthetic oversized content in the selected product/price review scans."""
from unittest.mock import patch

from django.db import connection
from django.db.models import JSONField, TextField, Value
from django.db.models.functions import Cast, Length
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import test_candidate_review_inspection as fixtures


@override_settings(STAFF_PORTAL_ENABLED=True)
class CandidateReviewScanBoundedContentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.CandidateReviewInspectionTests.setUpTestData.__func__(cls)

    def cases(self):
        return fixtures.CandidateReviewInspectionTests.cases(self)

    def test_oversized_review_payload_and_reason_are_not_fetched_or_echoed(self):
        from . import candidate_review_scan as scan
        for domain, candidate, event, model, route, _ in self.cases():
            with self.subTest(domain=domain):
                model.objects.filter(pk=event.pk).update(review_snapshot={'private-canary': 'آ' * 1_000_000},
                                                          reason='ر' * 100_000 + 'private-reason-canary')
                with CaptureQueriesContext(connection) as fetched:
                    batch = scan._review_batch(model, candidate.pk, 0)
                self.assertEqual(len(fetched), 1)
                self.assertEqual(len(batch), 1)
                self.assertEqual(batch[0].get_deferred_fields(), {'reason', 'review_snapshot'})
                self.assertIsNone(batch[0]._bounded_json)
                self.assertEqual(batch[0]._bounded_reason, 'ر' * (scan.MAX_REVIEW_REASON_LENGTH + 1))
                self.assertGreater(batch[0]._json_length, scan.MAX_REVIEW_JSON_TEXT_LENGTH)
                self.viewer.has_perm(f'{"catalog.view_productcandidate" if domain == "product" else "pricing.view_pricecandidate"}')
                with patch.dict(scan._DOMAINS, {domain: (*scan._DOMAINS[domain][:3],
                                lambda *_: self.fail('Oversized row must not be classified from truncated data'),
                                scan._DOMAINS[domain][4])}), CaptureQueriesContext(connection) as queries:
                    report = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)
                self.assertEqual(report['rows'], [{'id': event.pk, 'status': 'oversized', 'comparison': 'unknown'}])
                self.assertEqual(report['scanned'], 1)
                sql = next(q['sql'] for q in queries if f'FROM "{model._meta.db_table}"' in q['sql'])
                select = sql.split(' FROM ', 1)[0].lower()
                self.assertIn('case', select)
                self.assertIn('length', select)
                self.assertIn('substring', select)
                self.assertNotRegex(select, rf'(?:^select |, )"{model._meta.db_table}"\."(?:reason|review_snapshot)"(?:,|$)')
                self.assertIn('LIMIT 51', sql)
                self.client.force_login(self.viewer)
                response = self.client.get(reverse(route, args=[candidate.pk]), {'category': 'oversized'})
                self.assertContains(response, 'بیش از حد بازرسی')
                self.assertNotContains(response, 'private-canary')
                self.assertNotContains(response, 'private-reason-canary')
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                self.assertEqual(model.objects.get(pk=event.pk).review_snapshot['private-canary'], 'آ' * 1_000_000)

    def test_reason_and_json_thresholds_on_database_character_length(self):
        from . import candidate_review_scan as scan
        for domain, candidate, event, model, _, _ in self.cases():
            with self.subTest(domain=domain):
                original = event.review_snapshot
                for length in (scan.MAX_REVIEW_REASON_LENGTH, scan.MAX_REVIEW_REASON_LENGTH + 1):
                    model.objects.filter(pk=event.pk).update(review_snapshot=original, reason='ر' * length)
                    row = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)['rows'][0]
                    self.assertEqual(row['status'], 'consistent' if length == scan.MAX_REVIEW_REASON_LENGTH else 'oversized')
                overhead = len('{"canary": ""}')
                for length in (scan.MAX_REVIEW_JSON_TEXT_LENGTH, scan.MAX_REVIEW_JSON_TEXT_LENGTH + 1):
                    model.objects.filter(pk=event.pk).update(reason=event.reason,
                        review_snapshot={'canary': 'آ' * (length - overhead)})
                    actual = model.objects.annotate(n=Length(Cast('review_snapshot', TextField()))).get(pk=event.pk).n
                    self.assertEqual(actual, length)
                    row = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)['rows'][0]
                    self.assertEqual(row['status'], 'invalid_record' if length == scan.MAX_REVIEW_JSON_TEXT_LENGTH else 'oversized')

    def test_oversized_current_candidate_is_unknown_without_unbounded_json_transfer(self):
        from . import candidate_review_scan as scan
        for domain, candidate, event, model, _, _ in self.cases():
            with self.subTest(domain=domain):
                candidate.__class__.objects.filter(pk=candidate.pk).update(source_fields={'private-canary': 'آ' * 1_000_000})
                with CaptureQueriesContext(connection) as queries:
                    report = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)
                self.assertEqual(report['rows'], [{'id': event.pk, 'status': 'consistent', 'comparison': 'unknown'}])
                sql = next(q['sql'] for q in queries if f'FROM "{candidate._meta.db_table}"' in q['sql'])
                select = sql.split(' FROM ', 1)[0].lower()
                self.assertIn('case', select)
                self.assertNotRegex(select, rf'(?:^select |, )"{candidate._meta.db_table}"\."source_fields"(?:,|$)')

    def test_candidate_json_exact_database_character_boundary(self):
        from . import candidate_review_scan as scan
        overhead = len('{"canary": ""}')
        for domain, candidate, event, model, _, _ in self.cases():
            with self.subTest(domain=domain):
                parent_model, review_model, _, classify, permission = scan._DOMAINS[domain]
                for length in (scan.MAX_CANDIDATE_JSON_TEXT_LENGTH, scan.MAX_CANDIDATE_JSON_TEXT_LENGTH + 1):
                    value = {'canary': 'آ' * (length - overhead)}
                    parent_model.objects.filter(pk=candidate.pk).update(source_fields=value)
                    actual = parent_model.objects.annotate(n=Length(Cast('source_fields', TextField()))).get(pk=candidate.pk).n
                    self.assertEqual(actual, length)
                    seen = []
                    def validate(obj):
                        seen.append(obj.source_fields)
                        return False
                    with patch.dict(scan._DOMAINS, {domain: (parent_model, review_model, validate, classify, permission)}), CaptureQueriesContext(connection) as queries:
                        result = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)
                    self.assertEqual(seen, [value if length == scan.MAX_CANDIDATE_JSON_TEXT_LENGTH else None])
                    self.assertEqual(result['rows'][0]['comparison'], 'unknown')
                    self.assertEqual(len([q for q in queries if f'FROM "{parent_model._meta.db_table}"' in q['sql']]), 1)

    def test_no_review_or_candidate_update_occurs_and_existing_valid_rows_unchanged(self):
        from . import candidate_review_scan as scan
        for domain, candidate, event, model, route, _ in self.cases():
            with self.subTest(domain=domain), CaptureQueriesContext(connection) as queries:
                report = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)
                self.assertEqual(report['rows'], [{'id': event.pk, 'status': 'consistent', 'comparison': 'same'}])
            self.assertFalse(any(q['sql'].lstrip().upper().startswith(('UPDATE', 'DELETE', 'INSERT')) for q in queries))

    def test_malformed_small_json_values_are_still_invalid_without_lazy_loads(self):
        from . import candidate_review_scan as scan
        for domain, candidate, event, model, _, _ in self.cases():
            for raw in (Value(None, output_field=JSONField()), [], 'synthetic-canary', 17, {'key': '🌱'}):
                with self.subTest(domain=domain, value=repr(raw)):
                    model.objects.filter(pk=event.pk).update(review_snapshot=raw)
                    self.viewer.has_perm('catalog.view_productcandidate' if domain == 'product' else 'pricing.view_pricecandidate')
                    with CaptureQueriesContext(connection) as queries:
                        result = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)
                    self.assertEqual(result['rows'], [{'id': event.pk, 'status': 'invalid_record', 'comparison': 'unknown'}])
                    # Candidate, account lookup and exactly one bounded review SELECT.
                    self.assertEqual(len(queries), 3)
                    self.assertEqual(len([q for q in queries if f'FROM "{model._meta.db_table}"' in q['sql']]), 1)

    def test_oversized_sentinel_is_bounded_but_classified_only_on_next_page(self):
        from . import candidate_review_scan as scan
        for domain, candidate, event, model, _, _ in self.cases():
            with self.subTest(domain=domain):
                for _ in range(49):
                    model.objects.create(candidate=candidate, reviewer=self.reviewer, decision=event.decision,
                        reason=event.reason, candidate_payload_sha256=event.candidate_payload_sha256,
                        review_snapshot=event.review_snapshot)
                sentinel = model.objects.create(candidate=candidate, reviewer=self.reviewer, decision=event.decision,
                    reason='ر' * 100_000, candidate_payload_sha256=event.candidate_payload_sha256,
                    review_snapshot={'canary': 'آ' * 100_000})
                batch = scan._review_batch(model, candidate.pk, 0)
                self.assertEqual(len(batch), 51)
                self.assertEqual(batch[-1].pk, sentinel.pk)
                self.assertIsNone(batch[-1]._bounded_json)
                self.assertEqual(len(batch[-1]._bounded_reason), scan.MAX_REVIEW_REASON_LENGTH + 1)
                first = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk, category='oversized')
                self.assertEqual(first['rows'], [])
                self.assertEqual(first['scanned'], 50)
                second = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk,
                    after=first['next_after'], category='oversized')
                self.assertEqual(second['rows'], [{'id': sentinel.pk, 'status': 'oversized', 'comparison': 'unknown'}])
                self.assertIsNone(second['next_after'])

    def test_oversized_filtered_batch_keeps_continuation_and_candidate_scope(self):
        from . import candidate_review_scan as scan
        for domain, candidate, event, model, _, _ in self.cases():
            with self.subTest(domain=domain):
                model.objects.filter(pk=event.pk).update(reason='ر' * (scan.MAX_REVIEW_REASON_LENGTH + 1))
                for _ in range(49):
                    model.objects.create(candidate=candidate, reviewer=self.reviewer, decision=event.decision,
                        reason='ر' * (scan.MAX_REVIEW_REASON_LENGTH + 1),
                        candidate_payload_sha256=event.candidate_payload_sha256, review_snapshot=event.review_snapshot)
                last = model.objects.create(candidate=candidate, reviewer=self.reviewer, decision=event.decision,
                    reason=event.reason, candidate_payload_sha256=event.candidate_payload_sha256,
                    review_snapshot=event.review_snapshot)
                first = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk, category='consistent')
                self.assertEqual(first['scanned'], 50)
                self.assertEqual(first['rows'], [])
                self.assertIsNotNone(first['next_after'])
                final = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk,
                    category='consistent', after=first['next_after'])
                self.assertEqual(final['rows'], [{'id': last.pk, 'status': 'consistent', 'comparison': 'same'}])
                self.assertIsNone(final['next_after'])
