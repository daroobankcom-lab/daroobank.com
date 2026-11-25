"""Synthetic candidate JSON bounds in private receipt views and scans."""
import io
from unittest.mock import patch

from django.db import connection
from django.db.models import TextField
from django.db.models.functions import Cast, Length
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog.models import ProductCandidate
from catalog.test_intake import make_csv
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes
from . import test_manifest_inspection as fixtures
from .manifest_inspection import inspect_manifest
from .receipts import stage_product_with_receipt, stage_price_with_receipt


@override_settings(STAFF_PORTAL_ENABLED=True)
class ManifestBoundedCandidateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.ManifestInspectionTests.setUpTestData.__func__(cls)

    def cases(self):
        return [('product', self.product_receipt, self.product_user, ProductCandidate, 'product_candidate'),
                ('price', self.price_receipt, self.price_user, PriceCandidate, 'price_candidate')]

    def scan(self, receipt, actor, **kwargs):
        return inspect_manifest(actor=actor, receipt_id=receipt.pk, **kwargs)

    def test_oversized_candidate_not_selected_classified_or_reflected(self):
        for kind, receipt, actor, model, field in self.cases():
            with self.subTest(kind=kind):
                item = receipt.items.get()
                candidate_id = getattr(item, field + '_id')
                model.objects.filter(pk=candidate_id).update(source_fields={'private-canary': 'آ' * 1_000_000})
                actor.has_perm(f'{"catalog" if kind == "product" else "pricing"}.view_{kind}candidate')
                classifier = f'ingestion.receipts.valid_{"product" if kind == "product" else "price"}'
                with patch(classifier, side_effect=AssertionError('Oversized JSON must not be classified')):
                    with CaptureQueriesContext(connection) as queries:
                        report = self.scan(receipt, actor)
                    self.assertEqual(report['rows'], [{'ordinal': 1, 'status': 'oversized'}])
                    sql = next(q['sql'] for q in queries if 'FROM "ingestion_importreceiptitem"' in q['sql'] and ' JOIN ' in q['sql'])
                    selection = sql.split(' FROM ', 1)[0].lower()
                    self.assertIn('case', selection)
                    self.assertNotRegex(selection, rf'(?:^select |, )"{model._meta.db_table}"\."source_fields"(?:,|$)')
                    self.assertIn('LIMIT 51', sql)
                    self.client.force_login(actor)
                    detail = self.client.get(reverse('staff_import_receipt_detail', args=[receipt.pk]))
                    self.assertContains(detail, 'نامزد بیش از حد بررسی')
                    self.assertNotContains(detail, 'private-canary')
                    self.assertNotContains(detail, 'مشاهده نامزد')
                    self.assertIn('no-store', detail['Cache-Control'])
                    page = self.client.get(reverse('staff_import_manifest_inspection', args=[receipt.pk]), {'category': 'oversized'})
                    self.assertContains(page, 'نامزد بیش از حد بررسی')
                    self.assertNotContains(page, 'private-canary')
                    self.assertIn('no-store', page['Cache-Control'])
                self.assertEqual(len(model.objects.get(pk=candidate_id).source_fields['private-canary']), 1_000_000)

    def test_exact_json_text_threshold_and_malformed_null(self):
        from django.db.models import JSONField, Value
        for kind, receipt, actor, model, field in self.cases():
            with self.subTest(kind=kind):
                candidate_id = getattr(receipt.items.get(), field + '_id')
                for length in (65536, 65537):
                    model.objects.filter(pk=candidate_id).update(source_fields={'x': 'آ' * (length - len('{"x": ""}'))})
                    self.assertEqual(model.objects.annotate(n=Length(Cast('source_fields', TextField()))).get(pk=candidate_id).n, length)
                    self.assertEqual(self.scan(receipt, actor)['rows'][0]['status'], 'inconsistent' if length == 65536 else 'oversized')
                for value in ([], {'bad': 'small-private-canary'}, Value(None, output_field=JSONField())):
                    model.objects.filter(pk=candidate_id).update(source_fields=value)
                    self.assertEqual(self.scan(receipt, actor)['rows'][0]['status'], 'inconsistent')

    def test_missing_joined_candidate_is_inconsistent_without_lazy_read(self):
        for kind, receipt, actor, model, field in self.cases():
            with self.subTest(kind=kind):
                item = receipt.items.get()
                original_id = getattr(item, field + '_id')
                try:
                    receipt.items.filter(pk=item.pk).update(**{field + '_id': 2_147_483_000})
                    with CaptureQueriesContext(connection) as queries:
                        report = self.scan(receipt, actor)
                    self.assertEqual(report['rows'], [{'ordinal': 1, 'status': 'inconsistent'}])
                    self.assertEqual(len(queries), 3)
                    self.client.force_login(actor)
                    detail = self.client.get(reverse('staff_import_receipt_detail', args=[receipt.pk]))
                    self.assertContains(detail, 'اطلاعات ردیف یا نامزد ناسازگار است')
                finally:
                    receipt.items.filter(pk=item.pk).update(**{field + '_id': original_id})

    def test_filtered_empty_page_continues_to_oversized_sentinel(self):
        for kind, _, actor, model, field in self.cases():
            with self.subTest(kind=kind):
                original = self.product_row if kind == 'product' else self.price_row
                rows = [{**original, 'source_record_id': f'{kind}-{i}'} for i in range(51)]
                data, stage = (make_csv(rows), stage_product_with_receipt) if kind == 'product' else (csv_bytes(rows), stage_price_with_receipt)
                receipt = stage(io.BytesIO(data), 'منبع ساختگی', f'https://example.org/{kind}-large', actor=actor, rights_attested=True)[1]
                item = receipt.items.get(ordinal=51)
                model.objects.filter(pk=getattr(item, field + '_id')).update(source_fields={'private-canary': 'آ' * 1_000_000})
                from .candidate_reads import bounded_manifest_candidates
                with CaptureQueriesContext(connection) as queries:
                    batch = list(bounded_manifest_candidates(receipt.items.order_by('ordinal'), field)[:51])
                self.assertEqual(len(queries), 1)
                self.assertEqual(batch[-1].ordinal, 51)
                self.assertIsNone(batch[-1]._bounded_candidate_json)
                self.assertIn('source_fields', getattr(batch[-1], field).get_deferred_fields())
                first = self.scan(receipt, actor, category='oversized')
                self.assertEqual((first['scanned'], first['rows'], first['next_after']), (50, [], 50))
                next_page = self.scan(receipt, actor, after=50, category='oversized')
                self.assertEqual(next_page['rows'], [{'ordinal': 51, 'status': 'oversized'}])
                self.assertIsNone(next_page['next_after'])
