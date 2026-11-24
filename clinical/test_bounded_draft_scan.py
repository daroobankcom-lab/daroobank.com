"""Synthetic limits for clinical draft and parent queue/inspection reads."""
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import test_inspection as fixtures
from .inspection import inspect_drafts
from .models import ClinicalDraft
from .services import create_draft, valid_draft


@override_settings(STAFF_PORTAL_ENABLED=True)
class BoundedClinicalScanTests(TestCase):
    draft = fixtures.ClinicalInspectionTests.draft

    @classmethod
    def setUpTestData(cls):
        fixtures.ClinicalInspectionTests.setUpTestData.__func__(cls)

    def assert_bounded_select(self, queries):
        selects = [q['sql'] for q in queries if q['sql'].startswith('SELECT') and 'FROM "clinical_clinicaldraft"' in q['sql']]
        self.assertTrue(selects)
        for sql in selects:
            if 'COUNT(' in sql or 'SELECT 1 ' in sql:
                continue
            select = sql.rsplit(' FROM "clinical_clinicaldraft"', 1)[0].lower()
            self.assertGreaterEqual(select.count('substring'), 4)
            self.assertNotRegex(select, r'(?:^select |, )"clinical_clinicaldraft"\."(?:statement|change_reason)"(?:,|$)')
            self.assertNotRegex(select, r'(?:^select |, )t\d+\."(?:statement|change_reason)"(?:,|$)')

    def test_oversized_own_and_parent_fields_are_uninspected_not_invalid(self):
        parent = self.draft()
        child = create_draft(actor=self.author, data=self.data, parent_id=parent.pk,
                             expected_parent_hash=parent.payload_sha256, change_reason='دلیل اصلاح ساختگی کافی')
        ClinicalDraft.objects.filter(pk=parent.pk).update(statement='آ' * 1_000_000 + 'statement-canary')
        with patch('clinical.services.validate_data', side_effect=AssertionError('no partial validation')):
            with CaptureQueriesContext(connection) as queries:
                report = inspect_drafts(category='oversized')
            self.assertEqual(report['rows'], [{'id': parent.pk, 'status': 'oversized'}, {'id': child.pk, 'status': 'oversized'}])
            self.assert_bounded_select(queries)
            self.client.force_login(self.viewer)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse('staff_clinical_drafts'))
            self.assertContains(response, 'نسخه یا والد بیش از حد بازرسی است؛ سازگاری بررسی نشد')
            self.assertNotContains(response, 'statement-canary')
            self.assertIn('no-store', response['Cache-Control'])
            self.assert_bounded_select(queries)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse('staff_clinical_inspection'), {'category': 'oversized'})
            self.assertContains(response, 'نسخه یا والد بیش از حد بازرسی است؛ سازگاری بررسی نشد')
            self.assertNotContains(response, 'statement-canary')
            self.assert_bounded_select(queries)

    def test_long_whitespace_reason_can_be_valid_so_must_not_be_called_invalid(self):
        parent = self.draft()
        reason = 'دلیل ساختگی قابل قبول' + ' ' * 100_000
        child = create_draft(actor=self.author, data=self.data, parent_id=parent.pk,
                             expected_parent_hash=parent.payload_sha256, change_reason=reason)
        # Current service contract permits edge whitespace in a reason: the
        # exact historical value and digest can be valid despite its length.
        self.assertTrue(valid_draft(ClinicalDraft.objects.select_related('parent').get(pk=child.pk)))
        report = inspect_drafts()
        self.assertEqual(report['rows'], [{'id': parent.pk, 'status': 'available'}, {'id': child.pk, 'status': 'oversized'}])
        self.assertEqual(inspect_drafts(category='draft_invalid')['rows'], [])

    def test_exact_statement_and_reason_transfer_thresholds(self):
        root = create_draft(actor=self.author, data={**self.data, 'statement': 'ر' * 4000})
        child = create_draft(actor=self.author, data=self.data, parent_id=root.pk,
                             expected_parent_hash=root.payload_sha256, change_reason='ر' * 1000)
        first = inspect_drafts()
        self.assertEqual([row['status'] for row in first['rows']], ['available', 'available'])
        oversized_child = create_draft(actor=self.author, data=self.data, parent_id=root.pk,
            expected_parent_hash=root.payload_sha256, change_reason='ر' * 12 + ' ' * 989)
        self.assertTrue(valid_draft(ClinicalDraft.objects.select_related('parent').get(pk=oversized_child.pk)))
        report = inspect_drafts()
        self.assertEqual(report['rows'][-1], {'id': oversized_child.pk, 'status': 'oversized'})
        ClinicalDraft.objects.filter(pk=root.pk).update(statement='ر' * 4001)
        report = inspect_drafts()
        self.assertEqual([row['status'] for row in report['rows']], ['oversized', 'oversized', 'oversized'])

    def test_lookahead_is_bounded_and_filtered_continuation_is_preserved(self):
        from .draft_reads import bounded_draft_text
        drafts = [self.draft() for _ in range(51)]
        ClinicalDraft.objects.filter(pk=drafts[-1].pk).update(statement='آ' * 1_000_000 + 'sentinel-canary')
        with CaptureQueriesContext(connection) as queries:
            batch = list(bounded_draft_text(ClinicalDraft.objects.select_related('parent').order_by('pk'))[:51])
        self.assert_bounded_select(queries)
        self.assertEqual(batch[-1].pk, drafts[-1].pk)
        self.assertEqual(len(batch[-1]._statement_prefix), 4001)
        self.assertIn('statement', batch[-1].get_deferred_fields())
        first = inspect_drafts(category='oversized')
        self.assertEqual((first['scanned'], first['rows'], first['next_after']), (50, [], drafts[49].pk))
        second = inspect_drafts(after=first['next_after'], category='oversized')
        self.assertEqual(second['rows'], [{'id': drafts[-1].pk, 'status': 'oversized'}])
        self.assertIsNone(second['next_after'])
