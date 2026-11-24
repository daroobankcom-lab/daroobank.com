"""Selected price staging replay checks on synthetic PostgreSQL data."""
import io
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import CommandError, call_command
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from ingestion.exceptions import StagingConflict
from ingestion.models import ImportReceipt, ImportReceiptItem
from ingestion.receipts import stage_price_with_receipt
from .importer import stage_csv
from .models import PriceCandidate
from .test_workflow import csv_bytes

NAME, URL = 'منبع ساختگی', 'https://example.org/price-replay'
ROW = {'source_record_id': 'replay-001', 'irc': '001', 'manufacturer': 'سازنده فرضی', 'strength': '5 mg',
       'dosage_form': 'قرص', 'package_description': '10 عدد', 'amount': '100', 'currency': 'RIAL',
       'category': 'retail', 'unit': 'package', 'effective_date': '', 'source_published_date': ''}


def actor(name):
    user = get_user_model().objects.create_user(name, is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
        codename__in=['view_pricecandidate', 'add_pricecandidate']))
    return user


def stage(rows, user):
    return stage_price_with_receipt(io.BytesIO(csv_bytes(rows)), NAME, URL, actor=user, rights_attested=True)


def stage_direct(rows, user=None, callback=None):
    return stage_csv(io.BytesIO(csv_bytes(rows)), NAME, URL, commit=True, rights_attested=True,
                     staged_by=user, on_staged=callback)


@override_settings(STAFF_PORTAL_ENABLED=True)
class PriceReplayIntegrityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = actor('price-replay-author')
        cls.other = actor('price-replay-other')

    def test_valid_replay_preserves_original_author_and_duplicate_receipt(self):
        stage([ROW], self.author)
        counts, receipt = stage([ROW, ROW], self.other)
        original = PriceCandidate.objects.get()
        self.assertEqual(original.staged_by_id, self.author.pk)
        self.assertEqual((counts['created'], counts['duplicates']), (0, 2))
        self.assertEqual(receipt.items.count(), 2)
        self.assertEqual(set(receipt.items.values_list('price_candidate_id', flat=True)), {original.pk})

    def test_actorless_cli_candidate_can_still_be_replayed_without_inventing_recorder(self):
        stage_direct([ROW])
        counts, receipt = stage([ROW], self.other)
        self.assertEqual(counts['duplicates'], 1)
        self.assertIsNone(PriceCandidate.objects.get().staged_by_id)
        self.assertEqual(receipt.items.count(), 1)

    def test_replay_rejects_inconsistent_payload_derived_values_and_attestation(self):
        stage([ROW], self.author)
        original = PriceCandidate.objects.get()
        variants = [dict(source_fields={**ROW, 'amount': '200'}), dict(amount_rial=101),
                    dict(original_amount='101'), dict(original_currency='TOMAN'),
                    dict(price_category='wholesale'), dict(unit='tablet'),
                    dict(effective_date='2026-01-02'), dict(source_published_date='2026-01-02'),
                    dict(source_rights_attested=False)]
        for changes in variants:
            with self.subTest(changes=changes), transaction.atomic():
                PriceCandidate.objects.filter(pk=original.pk).update(**changes)
                with self.assertRaises(StagingConflict):
                    stage([ROW], self.other)
                self.assertEqual(ImportReceipt.objects.count(), 1)
                self.assertEqual(ImportReceiptItem.objects.count(), 1)
                transaction.set_rollback(True)

    def test_replay_rejects_missing_current_recorder_if_one_was_recorded(self):
        stage([ROW], self.author)
        with patch('pricing.importer.current_account_exists', return_value=False):
            with self.assertRaises(StagingConflict):
                stage([ROW], self.other)
        self.assertEqual(ImportReceipt.objects.count(), 1)

    def test_later_corrupt_duplicate_rolls_back_earlier_new_candidate(self):
        stage([ROW], self.author)
        PriceCandidate.objects.update(amount_rial=101)
        with self.assertRaises(StagingConflict):
            stage([{**ROW, 'source_record_id': 'new-first'}, ROW], self.other)
        self.assertEqual(PriceCandidate.objects.count(), 1)
        self.assertEqual(ImportReceipt.objects.count(), 1)
        self.assertEqual(ImportReceiptItem.objects.count(), 1)

    def test_same_request_rechecks_after_internal_callback_mutation(self):
        def mutate(candidate_id, source_id, payload, created, status):
            if created:
                PriceCandidate.objects.filter(pk=candidate_id).update(amount_rial=101)
        with self.assertRaises(StagingConflict):
            stage_direct([ROW, ROW], self.author, mutate)
        self.assertFalse(PriceCandidate.objects.exists())

    def test_replay_rejects_disappeared_candidate(self):
        stage_direct([ROW], self.author)
        original = PriceCandidate.objects.get()
        PriceCandidate.objects.filter(pk=original.pk).delete()
        with patch('pricing.importer.PriceCandidate.objects.get_or_create', return_value=(original, False)):
            with self.assertRaises(StagingConflict):
                stage_direct([ROW], self.other)
        self.assertFalse(PriceCandidate.objects.exists())

    def test_cli_corrupt_replay_fails_without_reporting_staged_success(self):
        stage_direct([ROW])
        PriceCandidate.objects.update(amount_rial=101)
        output = io.StringIO()
        with tempfile.NamedTemporaryFile(suffix='.csv') as data:
            data.write(csv_bytes([ROW]))
            data.flush()
            with self.assertRaises(CommandError) as caught:
                call_command('stage_price_csv', data.name, source_name=NAME, source_url=URL,
                             commit=True, attest_authorized=True, stdout=output)
        self.assertNotIn('STAGED', output.getvalue())
        self.assertNotIn('101', str(caught.exception))
        self.assertEqual(PriceCandidate.objects.count(), 1)

    def test_http_corrupt_replay_returns_private_conflict(self):
        stage([ROW], self.author)
        PriceCandidate.objects.update(source_fields={**ROW, 'manufacturer': 'محتوای خصوصی ساختگی'})
        self.client.force_login(self.other)
        response = self.client.post(reverse('staff_price_upload'), {
            'source_name': NAME, 'source_url': URL, 'action': 'stage', 'rights_attested': 'on',
            'csv_file': SimpleUploadedFile('data.csv', csv_bytes([ROW]), content_type='text/csv'),
        })
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'ناسازگاری رکورد قبلی', status_code=409)
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertNotContains(response, 'محتوای خصوصی ساختگی', status_code=409)
        self.assertEqual(ImportReceipt.objects.count(), 1)


class PriceReplayLockTests(TransactionTestCase):
    def setUp(self):
        self.author = actor('price-lock-author')
        self.other = actor('price-lock-other')
        stage([ROW], self.author)
        self.original = PriceCandidate.objects.get()

    def worker(self, func, lock_timeout='300ms'):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('lock_timeout', %s, false)", [lock_timeout])
                cursor.execute("SET statement_timeout = '8s'")
            return func()
        finally:
            connection.close()

    def test_existing_candidate_lock_timeout_is_a_conflict(self):
        with transaction.atomic():
            PriceCandidate.objects.select_for_update().get(pk=self.original.pk)
            with ThreadPoolExecutor(max_workers=1) as executor:
                with self.assertRaises(StagingConflict) as caught:
                    executor.submit(self.worker, lambda: stage_direct([ROW], self.other)).result(timeout=10)
                self.assertIsInstance(caught.exception.__cause__, OperationalError)
                self.assertEqual(caught.exception.__cause__.__cause__.sqlstate, '55P03')
        self.assertEqual(ImportReceipt.objects.count(), 1)

    def test_replay_lock_lasts_until_outer_transaction_ends(self):
        with transaction.atomic():
            stage_direct([ROW], self.other)
            with ThreadPoolExecutor(max_workers=1) as executor:
                with self.assertRaises(OperationalError) as caught:
                    executor.submit(self.worker, lambda: PriceCandidate.objects.filter(pk=self.original.pk).update(
                        amount_rial=101)).result(timeout=10)
                self.assertEqual(caught.exception.__cause__.sqlstate, '55P03')
        self.assertEqual(PriceCandidate.objects.get().amount_rial, 100)

    def test_locked_reread_observes_concurrent_mutation_after_lookup(self):
        lookup = PriceCandidate.objects.get_or_create
        seen = Event()

        def lookup_then_signal(*args, **kwargs):
            result = lookup(*args, **kwargs)
            seen.set()
            return result

        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch('pricing.importer.PriceCandidate.objects.get_or_create', side_effect=lookup_then_signal):
                with transaction.atomic():
                    PriceCandidate.objects.filter(pk=self.original.pk).update(amount_rial=101)
                    future = executor.submit(self.worker, lambda: stage([ROW], self.other), '4s')
                    self.assertTrue(seen.wait(3), 'Replay did not complete its pre-lock lookup')
                with self.assertRaises(StagingConflict):
                    future.result(timeout=10)
        self.assertEqual(PriceCandidate.objects.get().amount_rial, 101)
        self.assertEqual(ImportReceipt.objects.count(), 1)
