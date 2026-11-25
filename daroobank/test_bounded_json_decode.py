"""Database JSON can be smaller than the transfer limit but undecodable by Python."""
import io
import json

from django.core.management import call_command
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog import test_identity_missing_reviewers as identity_fixtures
from catalog.models import IdentityPackageReview, ProductCandidate, ProductCandidateReview
from catalog.intake import ReviewConflict as ProductConflict, review_product, stage_products
from catalog.test_intake import make_csv
from clinical.models import ClinicalDraftReview
from clinical.services import review_draft
from clinical.evidence import evidence_state
from ingestion import test_manifest_inspection as manifest_fixtures
from ingestion.manifest_inspection import inspect_manifest
from ingestion.exceptions import StagingConflict
from pricing.importer import stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import ReviewConflict as PriceConflict, record_preliminary_review
from pricing.test_workflow import csv_bytes
from sources.models import SourceClaimReview
from sources.services import review_claim
from sources.review_inspection import inspect_reviews as inspect_source_reviews
from clinical.review_inspection import inspect_reviews as inspect_clinical_reviews
from . import test_staff_raw_multiline_controls as fixtures
from .candidate_review_scan import inspect_reviews
from .bounded_json_decode import MAX_INTEGER_DIGITS, decode_bounded_json
from .candidate_content_bounds import bounded_candidates, materialize_candidate


class BoundedJsonDecoderUnitTests(SimpleTestCase):
    def test_valid_values_and_integer_boundary(self):
        for raw, expected in [('null', None), ('[]', []), ('{"نام": "نمونه"}', {'نام': 'نمونه'}),
                              ('{"id": 9223372036854775807}', {'id': 9223372036854775807}),
                              ('9' * MAX_INTEGER_DIGITS, int('9' * MAX_INTEGER_DIGITS))]:
            self.assertEqual(decode_bounded_json(raw), expected)
        for raw in ('9' * (MAX_INTEGER_DIGITS + 1), '-' + '9' * (MAX_INTEGER_DIGITS + 1),
                    '{bad', '[' * 1200 + '0' + ']' * 1200, None):
            self.assertIsNone(decode_bounded_json(raw))


# Both are valid PostgreSQL JSONB, well below 65,536 characters, but exceed
# Python's default integer or recursion limits. The sentinel must never echo.
PAYLOADS = ('{"private-canary": ' + '9' * 5000 + '}',
            '{"private-canary": ' + '[' * 1200 + '0' + ']' * 1200 + '}')


def set_json(model, pk, field, payload):
    table = connection.ops.quote_name(model._meta.db_table)
    column = connection.ops.quote_name(model._meta.get_field(field).column)
    with connection.cursor() as cursor:
        cursor.execute(f'UPDATE {table} SET {column} = %s::jsonb WHERE id = %s', [payload, pk])


@override_settings(STAFF_PORTAL_ENABLED=True)
class MalformedCandidateJsonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.RawMultilineHttpTests.setUpTestData.__func__(cls)
        cls.product_review = review_product(actor=cls.reviewer, candidate_id=cls.product.pk, decision='defer',
            reason='دلیل ساختگی بررسی برای آزمون', expected_review=0, expected_hash=cls.product.payload_sha256)
        cls.price_review = record_preliminary_review(actor=cls.reviewer, candidate_id=cls.price.pk, decision='defer',
            reason='دلیل ساختگی بررسی برای آزمون', expected_review=0, expected_product=0, expected_product_hash='')

    def test_sql_selects_only_bounded_json_as_text_and_materializes_without_extra_query(self):
        set_json(ProductCandidate, self.product.pk, 'source_fields', PAYLOADS[0])
        with CaptureQueriesContext(connection) as queries:
            item = bounded_candidates(ProductCandidate.objects.filter(pk=self.product.pk)).get()
            self.assertIn('source_fields', item.get_deferred_fields())
            materialize_candidate(item)
            self.assertIsNone(item.source_fields)
            self.assertFalse(item.content_oversized)
        self.assertEqual(len(queries), 1)
        selected = queries[0]['sql'].split(' FROM ', 1)[0].lower()
        self.assertIn('case', selected)
        self.assertIn('::text', selected)
        self.assertNotRegex(selected, r'(?:^select |, )"catalog_productcandidate"\."source_fields"(?:,|$)')

    def test_candidate_reads_and_cli_treat_undecodable_json_as_invalid_without_echo(self):
        self.client.force_login(self.reviewer)
        for payload in PAYLOADS:
            for domain, model, candidate, queue, detail in (
                ('product', ProductCandidate, self.product, 'staff_products', 'staff_product_detail'),
                ('price', PriceCandidate, self.price, 'staff_prices', 'staff_price_detail')):
                with self.subTest(domain=domain, payload_length=len(payload)):
                    set_json(model, candidate.pk, 'source_fields', payload)
                    for route, args in ((queue, []), (detail, [candidate.pk])):
                        response = self.client.get(reverse(route, args=args))
                        self.assertEqual(response.status_code, 200)
                        self.assertNotContains(response, 'private-canary')
                        self.assertIn('no-store', response['Cache-Control'])
                    report = inspect_reviews(actor=self.reviewer, domain=domain, candidate_id=candidate.pk)
                    self.assertEqual(report['rows'][0]['comparison'], 'unknown')
                    if domain == 'price':
                        output = io.StringIO()
                        call_command('list_price_candidates', stdout=output)
                        row = json.loads(output.getvalue())['data'][0]
                        self.assertEqual(row['payload_status'], 'invalid')
                        self.assertNotIn('private-canary', output.getvalue())

    def test_locked_review_and_replay_reject_without_writes(self):
        for payload in PAYLOADS:
            for model, candidate, review, conflict, kwargs, stage in (
                (ProductCandidate, self.product, review_product, ProductConflict,
                 {'expected_hash': self.product.payload_sha256},
                 lambda: stage_products(io.BytesIO(make_csv([self.product.source_fields])), self.product.source_name,
                     self.product.source_url, actor=self.author, commit=True, rights_attested=True)),
                (PriceCandidate, self.price, record_preliminary_review, PriceConflict,
                 {'expected_product': 0, 'expected_product_hash': ''},
                 lambda: stage_csv(io.BytesIO(csv_bytes([self.price.source_fields])), self.price.source_name,
                     self.price.source_url, staged_by=self.author, commit=True, rights_attested=True))):
                with self.subTest(model=model.__name__, payload_length=len(payload)):
                    set_json(model, candidate.pk, 'source_fields', payload)
                    before = (model.objects.count(), ProductCandidateReview.objects.count(), PriceCandidateReview.objects.count())
                    with self.assertRaises(conflict):
                        review(actor=self.reviewer, candidate_id=candidate.pk, decision='defer',
                               reason='دلیل ساختگی بررسی برای آزمون', expected_review=1, **kwargs)
                    with self.assertRaises(StagingConflict):
                        stage()
                    self.assertEqual((model.objects.count(), ProductCandidateReview.objects.count(),
                                      PriceCandidateReview.objects.count()), before)

    def test_review_snapshots_cannot_crash_detail_or_scans(self):
        claim_event = review_claim(actor=self.reviewer, claim_id=self.claim.pk, decision='defer',
            reason='دلیل ساختگی بررسی برای آزمون', expected_review=0, expected_hash=self.claim.payload_sha256)
        draft_event = review_draft(actor=self.reviewer, draft_id=self.draft.pk, decision='defer',
            reason='دلیل ساختگی بررسی برای آزمون', expected_review=0, expected_hash=self.draft.payload_sha256,
            expected_evidence_hash=evidence_state(self.draft)['fingerprint'])
        self.client.force_login(self.reviewer)
        cases = ((ProductCandidateReview, self.product_review, 'staff_product_detail', 'staff_product_review_inspection', self.product.pk),
                 (PriceCandidateReview, self.price_review, 'staff_price_detail', 'staff_price_review_inspection', self.price.pk),
                 (SourceClaimReview, claim_event, 'staff_source_detail', 'staff_source_review_inspection', self.claim.pk),
                 (ClinicalDraftReview, draft_event, 'staff_clinical_detail', 'staff_clinical_review_inspection', self.draft.pk))
        for payload in PAYLOADS:
            for model, event, detail, inspection, parent_id in cases:
                with self.subTest(model=model.__name__, payload_length=len(payload)):
                    set_json(model, event.pk, 'review_snapshot', payload)
                    for route in (detail, inspection):
                        response = self.client.get(reverse(route, args=[parent_id]))
                        self.assertEqual(response.status_code, 200)
                        self.assertNotContains(response, 'private-canary')
                        self.assertNotContains(response, event.reason)
                        self.assertIn('no-store', response['Cache-Control'])
                    if model in (ProductCandidateReview, PriceCandidateReview):
                        domain = 'product' if model is ProductCandidateReview else 'price'
                        report = inspect_reviews(actor=self.reviewer, domain=domain, candidate_id=parent_id)
                    elif model is SourceClaimReview:
                        report = inspect_source_reviews(actor=self.reviewer, claim_id=parent_id)
                    else:
                        report = inspect_clinical_reviews(actor=self.reviewer, draft_id=parent_id)
                    self.assertEqual(report['rows'], [{'id': event.pk, 'status': 'invalid_record', 'comparison': 'unknown'}])


@override_settings(STAFF_PORTAL_ENABLED=True)
class MalformedManifestJsonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        manifest_fixtures.ManifestInspectionTests.setUpTestData.__func__(cls)

    def test_joined_candidate_decode_failure_is_inconsistent(self):
        for payload in PAYLOADS:
            for receipt, actor, model, field in ((self.product_receipt, self.product_user, ProductCandidate, 'product_candidate_id'),
                                                  (self.price_receipt, self.price_user, PriceCandidate, 'price_candidate_id')):
                with self.subTest(kind=receipt.kind, payload_length=len(payload)):
                    set_json(model, getattr(receipt.items.get(), field), 'source_fields', payload)
                    report = inspect_manifest(actor=actor, receipt_id=receipt.pk)
                    self.assertEqual(report['rows'], [{'ordinal': 1, 'status': 'inconsistent'}])
                    self.client.force_login(actor)
                    response = self.client.get(reverse('staff_import_receipt_detail', args=[receipt.pk]))
                    self.assertEqual(response.status_code, 200)
                    self.assertNotContains(response, 'private-canary')


@override_settings(STAFF_PORTAL_ENABLED=True)
class MalformedIdentityReviewJsonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        identity_fixtures.MissingIdentityReviewerTests.setUpTestData.__func__(cls)

    def test_graph_snapshot_failure_disables_revision_without_leaking(self):
        self.client.force_login(self.editor)
        for payload in PAYLOADS:
            set_json(IdentityPackageReview, self.event.pk, 'graph_snapshot', payload)
            for name, args in (('staff_identity_detail', ['package', self.package.pk]),
                               ('staff_identity_revise', [self.package.pk])):
                response = self.client.get(reverse(name, args=args))
                self.assertEqual(response.status_code, 200)
                self.assertNotContains(response, 'private-canary')
                self.assertNotContains(response, self.event.reason)
            self.assertNotContains(response, 'name="change_reason"')
