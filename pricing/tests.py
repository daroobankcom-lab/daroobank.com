import csv
import hashlib
import importlib
import io
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from django.apps import apps
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TestCase
from django.urls import reverse

from catalog.models import ProductPresentation
from .importer import FIELDS, ImportValidationError, amount_to_rial, stage_csv
from .models import PriceCandidate


class PriceImportTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'prices.csv'
        self.product_data = dict(
            name_fa='محصول آزمایشی', name_en='Synthetic', manufacturer='شرکت نمونه',
            strength='۵ میلی‌گرم', dosage_form='قرص', package_description='۱۰ عدد',
            irc='001234', source_name='نمونه', source_url='https://example.org/product',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True,
        )
        self.product = ProductPresentation.objects.create(**self.product_data)
        self.row = dict(
            source_record_id='sample-1', irc='۰۰۱۲۳۴', manufacturer='شركت نمونه',
            strength='5 میلی گرم', dosage_form='قرص', package_description='10 عدد',
            amount='۱۲۳٫۵', currency='TOMAN', category='official_consumer', unit='package',
            effective_date='2026-01-02', source_published_date='',
        )

    def write_csv(self, rows, fields=FIELDS):
        with self.path.open('w', encoding='utf-8', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def stage(self, commit=False):
        return stage_csv(self.path, 'منبع آزمایشی', 'https://example.org/feed', commit=commit, rights_attested=commit)

    def test_dry_run_does_not_write_and_command_requires_attestation(self):
        self.write_csv([self.row])
        output = io.StringIO()
        call_command('stage_price_csv', str(self.path), source_name='Synthetic', source_url='https://example.org', stdout=output)
        self.assertIn('DRY RUN', output.getvalue())
        self.assertIn('Repeated identities and IRC candidate sets may reuse earlier observations', output.getvalue())
        self.assertEqual(PriceCandidate.objects.count(), 0)
        with self.assertRaises(CommandError):
            call_command('stage_price_csv', str(self.path), source_name='Synthetic', source_url='https://example.org', commit=True, stdout=io.StringIO())
        self.assertEqual(PriceCandidate.objects.count(), 0)

    def test_attested_staging_is_review_only_and_replay_is_idempotent(self):
        self.write_csv([self.row])
        output = io.StringIO()
        call_command('stage_price_csv', str(self.path), source_name='Synthetic', source_url='https://example.org', commit=True, attest_authorized=True, stdout=output)
        candidate = PriceCandidate.objects.get()
        self.assertEqual(candidate.amount_rial, 1235)
        self.assertEqual(candidate.original_amount, '۱۲۳٫۵')
        self.assertEqual(candidate.match_status, 'suggested')
        self.assertEqual(candidate.suggested_product, self.product)
        self.assertEqual(candidate.effective_date.isoformat(), '2026-01-02')
        self.assertIsNone(candidate.source_published_date)
        self.assertIn('No prices were published', output.getvalue())
        call_command('stage_price_csv', str(self.path), source_name='Synthetic', source_url='https://example.org', commit=True, attest_authorized=True, stdout=output)
        self.assertEqual(PriceCandidate.objects.count(), 1)
        self.assertNotContains(self.client.get(reverse('prices')), '۱۲۳٫۵')
        self.assertNotIn('amount_rial', str(self.client.get(reverse('search_api'), {'q': '001234'}).json()))

    def test_local_review_list_is_bounded_and_read_only(self):
        self.write_csv([self.row])
        self.stage(commit=True)
        output = io.StringIO()
        call_command('list_price_candidates', status='suggested', limit=1, stdout=output)
        result = json.loads(output.getvalue())
        self.assertEqual(len(result['data']), 1)
        self.assertTrue(result['data'][0]['review_required'])
        self.assertEqual(result['data'][0]['amount_rial'], 1235)
        self.assertEqual(result['data'][0]['current_suggestion']['match_status'], 'suggested')
        self.product.strength = 'مقدار متفاوت'
        self.product.save(update_fields=['strength'])
        output = io.StringIO()
        call_command('list_price_candidates', stdout=output)
        self.assertEqual(json.loads(output.getvalue())['data'][0]['current_suggestion']['match_status'], 'unmatched')
        output = io.StringIO()
        call_command('list_price_candidates', status='unmatched', stdout=output)
        self.assertEqual(json.loads(output.getvalue())['data'], [])
        with self.assertRaises(CommandError):
            call_command('list_price_candidates', limit=101, stdout=io.StringIO())
        self.assertEqual(PriceCandidate.objects.count(), 1)

    def test_changed_observation_is_staged_as_new_revision(self):
        self.write_csv([self.row])
        self.stage(commit=True)
        self.write_csv([{**self.row, 'amount': '۱۳۰'}])
        self.stage(commit=True)
        self.assertEqual(PriceCandidate.objects.count(), 2)
        self.assertEqual(set(PriceCandidate.objects.values_list('amount_rial', flat=True)), {1235, 1300})

    def test_exact_match_requires_all_fields_and_duplicate_matches_are_ambiguous(self):
        self.write_csv([{**self.row, 'package_description': '20 عدد'}])
        self.assertEqual(self.stage(commit=True)['unmatched'], 1)
        self.assertIsNone(PriceCandidate.objects.get().suggested_product)
        ProductPresentation.objects.create(**self.product_data)
        self.write_csv([{**self.row, 'source_record_id': 'sample-2'}])
        self.assertEqual(self.stage(commit=True)['ambiguous'], 1)
        candidate = PriceCandidate.objects.get(source_record_id='sample-2')
        self.assertIsNone(candidate.suggested_product)

    def test_invalid_file_is_atomic_and_source_url_has_no_secrets(self):
        self.write_csv([self.row, {**self.row, 'source_record_id': 'bad', 'currency': 'UNKNOWN'}])
        with self.assertRaises(ImportValidationError):
            self.stage(commit=True)
        self.assertEqual(PriceCandidate.objects.count(), 0)
        self.write_csv([self.row])
        for url in ['http://example.org', 'https://user:pass@example.org', 'https://example.org?key=secret', 'https://example.org/#fragment']:
            with self.subTest(url=url), self.assertRaises(ImportValidationError):
                stage_csv(self.path, 'example', url, commit=True, rights_attested=True)
        self.assertEqual(PriceCandidate.objects.count(), 0)

    def test_missing_columns_invalid_dates_and_extra_data_fail_closed(self):
        self.write_csv([self.row], fields=FIELDS)
        raw = self.path.read_text(encoding='utf-8')
        self.path.write_text(raw.replace('effective_date', 'unknown_field', 1), encoding='utf-8')
        with self.assertRaises(ImportValidationError):
            self.stage(commit=True)
        self.write_csv([{**self.row, 'effective_date': '1405-13-40'}])
        with self.assertRaises(ImportValidationError):
            self.stage(commit=True)
        self.write_csv([{**self.row, 'unit': 'package', 'category': 'unit'}])
        with self.assertRaises(ImportValidationError):
            self.stage(commit=True)
        self.assertEqual(PriceCandidate.objects.count(), 0)

    def test_amount_validation_exact_and_currency_explicit(self):
        self.assertEqual(amount_to_rial('۲٫۵', 'TOMAN'), 25)
        self.assertEqual(amount_to_rial('۱۲۳', 'RIAL'), 123)
        for amount, currency in [
            ('1.5', 'RIAL'), ('0.01', 'TOMAN'), ('0', 'RIAL'), ('-1', 'RIAL'),
            ('1e4', 'RIAL'), ('1,000', 'RIAL'), ('5', ''),
            ('123456789012345.000000000000000001', 'RIAL'),
            ('9223372036854775808', 'RIAL'),
        ]:
            with self.subTest(amount=amount, currency=currency), self.assertRaises(ImportValidationError):
                amount_to_rial(amount, currency)

    def test_hidden_or_control_characters_in_amount_reject_the_whole_csv(self):
        for amount in ('1\u200b2', '1\u202e2', '1\u0301', '1\u20dd', '1\ufe0f', '\t1', '\n1', '1\u2028', '\u00a81'):
            with self.subTest(amount=repr(amount)), transaction.atomic():
                self.write_csv([self.row, {**self.row, 'source_record_id': 'bad', 'amount': amount}])
                with self.assertRaises(ImportValidationError) as error:
                    self.stage(commit=True)
                self.assertNotIn(amount, str(error.exception))
                self.assertEqual(PriceCandidate.objects.count(), 0)
                transaction.set_rollback(True)
        self.write_csv([{**self.row, 'amount': ' ۱۲۳ '}])
        self.stage(commit=True)
        self.assertEqual(PriceCandidate.objects.get().amount_rial, 1230)

    def test_legacy_candidate_with_hidden_amount_is_withheld_from_comparison(self):
        from .comparisons import price_revision_context
        from .reviews import ReviewConflict, ensure_candidate_integrity

        self.write_csv([self.row])
        self.stage(commit=True)
        candidate = PriceCandidate.objects.get()
        fields = dict(candidate.source_fields)
        fields['amount'] = '1\u200b2'
        payload = json.dumps({'source_name': candidate.source_name, 'fields': fields},
                             sort_keys=True, ensure_ascii=False, separators=(',', ':'))
        digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        # Simulate a coherent historical row accepted by the old normalizer.
        PriceCandidate.objects.filter(pk=candidate.pk).update(
            source_fields=fields, original_amount=fields['amount'], amount_rial=120, payload_sha256=digest)
        candidate.refresh_from_db()
        with self.assertRaises(ReviewConflict):
            ensure_candidate_integrity(candidate)
        self.assertFalse(price_revision_context(candidate)['available'])
        self.assertEqual(PriceCandidate.objects.count(), 1)

    def test_compatibility_digit_amount_staging_and_invalid_file_is_atomic(self):
        self.write_csv([{**self.row, 'amount': '⑩.0', 'currency': 'RIAL'},
                        {**self.row, 'source_record_id': 'bad', 'amount': '1.' + '⑩' * 48, 'currency': 'RIAL'}])
        with self.assertRaises(ImportValidationError):
            self.stage(commit=True)
        self.assertEqual(PriceCandidate.objects.count(), 0)
        self.write_csv([{**self.row, 'amount': '⑩.0', 'currency': 'RIAL'}])
        self.stage(commit=True)
        candidate = PriceCandidate.objects.get()
        self.assertEqual((candidate.original_amount, candidate.amount_rial), ('⑩.0', 10))
        self.assertEqual(candidate.source_fields['amount'], '⑩.0')
        self.assertEqual(self.stage(commit=True)['duplicates'], 1)
        self.assertEqual(PriceCandidate.objects.count(), 1)

    def test_partial_updates_keep_irc_and_search_projection_in_sync(self):
        self.product.irc = '9999'  # not included in partial save; must not leak into derived fields
        self.product.name_fa = 'تغییر موقت'
        self.product.source_name = 'منبع جدید'
        self.product.save(update_fields=['source_name'])
        self.product.refresh_from_db()
        self.assertEqual(self.product.irc, '001234')
        self.assertEqual(self.product.irc_normalized, '001234')
        self.assertNotIn('تغییر موقت', self.product.search_text)
        self.write_csv([self.row])
        self.assertEqual(self.stage()['suggested'], 1)

    def test_stale_identifier_projection_never_suggests_wrong_product(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(irc='different-code')
        self.write_csv([self.row])
        self.assertEqual(self.stage()['unmatched'], 1)

    def test_backfill_handles_persian_digits_without_truncation(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(irc='۰۰۱۲۳۴', irc_normalized='')
        migration = importlib.import_module('catalog.migrations.0002_productpresentation_irc_normalized')
        migration.backfill_irc(apps, SimpleNamespace(connection=connection))
        self.product.refresh_from_db()
        self.assertEqual(self.product.irc_normalized, '001234')
