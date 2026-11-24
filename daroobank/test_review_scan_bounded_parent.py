"""Selected oversized parent content must not be loaded by review scans."""
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from clinical.evidence import evidence_state
from clinical.services import create_draft, draft_data, review_draft
from clinical import review_inspection as clinical_scan
from sources import review_inspection as source_scan
from . import test_recent_review_bounded_content as fixtures
from . import test_candidate_review_inspection as candidate_fixtures


@override_settings(STAFF_PORTAL_ENABLED=True)
class BoundedReviewScanParentsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.RecentReviewBoundedContentTests.setUpTestData.__func__(cls)
        cls.child = create_draft(actor=cls.author, data=draft_data(cls.draft), parent_id=cls.draft.pk,
            expected_parent_hash=cls.draft.payload_sha256, change_reason='تغییر ساختگی برای آزمون')
        cls.child_event = review_draft(actor=cls.reviewer, draft_id=cls.child.pk, decision='defer',
            reason=cls.reason, expected_review=0, expected_hash=cls.child.payload_sha256,
            expected_evidence_hash=evidence_state(cls.child)['fingerprint'])

    def test_large_source_note_is_bounded_and_makes_comparison_unknown(self):
        type(self.claim).objects.filter(pk=self.claim.pk).update(evidence_note='آ' * 1_000_000)
        self.viewer.has_perm('sources.view_sourceclaim')
        with CaptureQueriesContext(connection) as queries:
            result = source_scan.inspect_reviews(actor=self.viewer, claim_id=self.claim.pk)
        self.assertEqual(result['rows'], [{'id': self.source_event.pk, 'status': 'consistent', 'comparison': 'unknown'}])
        sql = next(q['sql'] for q in queries if 'FROM "sources_sourceclaim"' in q['sql'])
        self.assertIn('SUBSTRING', sql.upper())
        self.assertNotRegex(sql.split(' FROM ', 1)[0].lower(), r'(?:^select |, )"sources_sourceclaim"\."evidence_note"(?:,|$)')
        self.assertEqual(len(queries), 2)

    def test_large_current_or_immediate_parent_text_is_bounded_and_unknown(self):
        self.viewer.has_perm('clinical.view_clinicaldraft')
        for item, field in [(self.child, 'statement'), (self.child, 'change_reason'),
                            (self.draft, 'statement')]:
            with self.subTest(item=item.pk, field=field):
                original = getattr(item, field)
                type(item).objects.filter(pk=item.pk).update(**{field: 'آ' * 1_000_000})
                try:
                    with CaptureQueriesContext(connection) as queries:
                        result = clinical_scan.inspect_reviews(actor=self.viewer, draft_id=self.child.pk)
                    self.assertEqual(result['rows'], [{'id': self.child_event.pk, 'status': 'consistent', 'comparison': 'unknown'}])
                    sql = next(q['sql'] for q in queries if 'FROM "clinical_clinicaldraft"' in q['sql'])
                    self.assertIn('SUBSTRING', sql.upper())
                    self.assertNotRegex(sql.split(' FROM ', 1)[0].lower(),
                        r'(?:^select |, )(?:"clinical_clinicaldraft"|t2)\."(?:statement|change_reason)"(?:,|$)')
                    self.assertEqual(len(queries), 2)
                finally:
                    type(item).objects.filter(pk=item.pk).update(**{field: original})


    def test_threshold_prefixes_keep_current_comparison_semantics(self):
        from sources.services import claim_data, fingerprint as claim_fingerprint
        from clinical.services import draft_data, fingerprint as draft_fingerprint
        note = 'ر' * 1000
        data = {**claim_data(self.claim), 'evidence_note': note}
        type(self.claim).objects.filter(pk=self.claim.pk).update(evidence_note=note, payload_sha256=claim_fingerprint(data))
        row = source_scan.inspect_reviews(actor=self.viewer, claim_id=self.claim.pk)['rows'][0]
        self.assertEqual((row['status'], row['comparison']), ('consistent', 'different'))
        type(self.claim).objects.filter(pk=self.claim.pk).update(evidence_note=note + 'ر')
        self.assertEqual(source_scan.inspect_reviews(actor=self.viewer, claim_id=self.claim.pk)['rows'][0]['comparison'], 'unknown')

        text = 'ر' * 4000
        data = {**draft_data(self.draft), 'statement': text}
        type(self.draft).objects.filter(pk=self.draft.pk).update(statement=text, payload_sha256=draft_fingerprint(data, None, '', ''))
        row = clinical_scan.inspect_reviews(actor=self.viewer, draft_id=self.draft.pk)['rows'][0]
        self.assertEqual((row['status'], row['comparison']), ('consistent', 'different'))
        type(self.draft).objects.filter(pk=self.draft.pk).update(statement=text + 'ر')
        self.assertEqual(clinical_scan.inspect_reviews(actor=self.viewer, draft_id=self.draft.pk)['rows'][0]['comparison'], 'unknown')

    def test_oversized_immediate_parent_change_reason(self):
        grandchild = create_draft(actor=self.author, data=draft_data(self.child), parent_id=self.child.pk,
            expected_parent_hash=self.child.payload_sha256, change_reason='تغییر ساختگی دیگر برای آزمون')
        event = review_draft(actor=self.reviewer, draft_id=grandchild.pk, decision='defer', reason=self.reason,
            expected_review=0, expected_hash=grandchild.payload_sha256,
            expected_evidence_hash=evidence_state(grandchild)['fingerprint'])
        type(self.child).objects.filter(pk=self.child.pk).update(change_reason='آ' * 1_000_000)
        result = clinical_scan.inspect_reviews(actor=self.viewer, draft_id=grandchild.pk)
        self.assertEqual(result['rows'], [{'id': event.pk, 'status': 'consistent', 'comparison': 'unknown'}])


@override_settings(STAFF_PORTAL_ENABLED=True)
class BoundedCandidateScanErrorsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        candidate_fixtures.CandidateReviewInspectionTests.setUpTestData.__func__(cls)

    def test_invalid_filter_and_cursor_only_check_existence_without_candidate_json(self):
        self.client.force_login(self.viewer)
        for domain, candidate, event, model, route, _ in candidate_fixtures.CandidateReviewInspectionTests.cases(self):
            with self.subTest(domain=domain):
                type(candidate).objects.filter(pk=candidate.pk).update(source_fields={'private-canary': 'آ' * 1_000_000})
                for params in ({'category': 'invalid'}, {'after': 'not-a-number'}):
                    with CaptureQueriesContext(connection) as queries:
                        response = self.client.get(reverse(route, args=[candidate.pk]), params)
                    self.assertEqual(response.status_code, 400)
                    sql = next(q['sql'] for q in queries if f'FROM "{candidate._meta.db_table}"' in q['sql'])
                    self.assertNotIn('source_fields', sql.lower())
                    self.assertNotContains(response, 'private-canary', status_code=400)
                    self.assertIn('no-store', response['Cache-Control'])
                self.assertEqual(self.client.get(reverse(route, args=[9_000_000]), {'category': 'invalid'}).status_code, 404)
