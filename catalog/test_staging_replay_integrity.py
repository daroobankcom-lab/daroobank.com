"""Selected product staging replay checks on synthetic PostgreSQL data."""
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from ingestion.exceptions import StagingConflict
from ingestion.models import ImportReceipt, ImportReceiptItem
from ingestion.receipts import stage_product_with_receipt
from .intake import stage_products
from .models import ProductCandidate
from .test_intake import make_csv

NAME, URL = 'منبع ساختگی', 'https://example.org/product-replay'
ROW = {'source_record_id': 'replay-001', 'name_fa': 'فرآورده ساختگی', 'name_en': '',
       'manufacturer': 'سازنده فرضی', 'strength': '5 mg', 'dosage_form': 'قرص',
       'package_description': '10 عدد', 'irc': '001'}


def actor(name):
    user = get_user_model().objects.create_user(name, is_staff=True)
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog',
        codename__in=['view_productcandidate', 'add_productcandidate']))
    return user


def stage(rows, user):
    return stage_product_with_receipt(io.BytesIO(make_csv(rows)), NAME, URL, actor=user, rights_attested=True)


@override_settings(STAFF_PORTAL_ENABLED=True)
class ProductReplayIntegrityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = actor('product-replay-author')
        cls.other = actor('product-replay-other')

    def test_valid_replay_preserves_original_author_and_creates_duplicate_receipt(self):
        stage([ROW], self.author)
        counts, receipt = stage([ROW, ROW], self.other)
        original = ProductCandidate.objects.get()
        self.assertEqual(original.staged_by_id, self.author.pk)
        self.assertEqual((counts['created'], counts['duplicates']), (0, 2))
        self.assertEqual(receipt.items.count(), 2)
        self.assertEqual(set(receipt.items.values_list('product_candidate_id', flat=True)), {original.pk})

    def test_replay_refuses_inconsistent_payload_projection_or_attestation(self):
        stage([ROW], self.author)
        original = ProductCandidate.objects.get()
        variants = [dict(source_fields={**ROW, 'name_fa': 'دستکاری ساختگی'}),
                    dict(irc_normalized='wrong'), dict(source_rights_attested=False)]
        for changes in variants:
            with self.subTest(changes=changes), transaction.atomic():
                ProductCandidate.objects.filter(pk=original.pk).update(**changes)
                with self.assertRaises(StagingConflict):
                    stage([ROW], self.other)
                self.assertEqual(ImportReceipt.objects.count(), 1)
                self.assertEqual(ImportReceiptItem.objects.count(), 1)
                transaction.set_rollback(True)

    def test_replay_refuses_missing_current_recorder(self):
        stage([ROW], self.author)
        with patch('catalog.intake.current_account_exists', return_value=False):
            with self.assertRaises(StagingConflict):
                stage([ROW], self.other)
        self.assertEqual(ImportReceipt.objects.count(), 1)

    def test_corrupt_later_duplicate_rolls_back_earlier_new_candidate(self):
        stage([ROW], self.author)
        original = ProductCandidate.objects.get()
        ProductCandidate.objects.filter(pk=original.pk).update(irc_normalized='wrong')
        with self.assertRaises(StagingConflict):
            stage([{**ROW, 'source_record_id': 'new-first'}, ROW], self.other)
        self.assertEqual(ProductCandidate.objects.count(), 1)
        self.assertEqual(ImportReceipt.objects.count(), 1)
        self.assertEqual(ImportReceiptItem.objects.count(), 1)

    def test_same_request_rechecks_after_internal_callback_mutation(self):
        def mutate(candidate_id, source_id, payload, created, status):
            if created:
                ProductCandidate.objects.filter(pk=candidate_id).update(irc_normalized='wrong')
        with self.assertRaises(StagingConflict):
            stage_products(io.BytesIO(make_csv([ROW, ROW])), NAME, URL, actor=self.author,
                           commit=True, rights_attested=True, on_staged=mutate)
        self.assertFalse(ProductCandidate.objects.exists())

    def test_replay_rejects_a_disappeared_candidate(self):
        stage_products(io.BytesIO(make_csv([ROW])), NAME, URL, actor=self.author, commit=True, rights_attested=True)
        original = ProductCandidate.objects.get()
        ProductCandidate.objects.filter(pk=original.pk).delete()
        with patch('catalog.intake._find_or_create_candidate', return_value=(original, False)):
            with self.assertRaises(StagingConflict):
                stage_products(io.BytesIO(make_csv([ROW])), NAME, URL, actor=self.other, commit=True, rights_attested=True)
        self.assertFalse(ProductCandidate.objects.exists())

    def test_http_corrupt_replay_returns_private_conflict(self):
        stage([ROW], self.author)
        ProductCandidate.objects.update(source_fields={**ROW, 'name_fa': 'محتوای خصوصی ساختگی'})
        self.client.force_login(self.other)
        response = self.client.post(reverse('staff_product_upload'), {
            'source_name': NAME, 'source_url': URL, 'action': 'stage', 'rights_attested': 'on',
            'csv_file': SimpleUploadedFile('data.csv', make_csv([ROW]), content_type='text/csv'),
        })
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'ناسازگاری رکورد قبلی', status_code=409)
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertNotContains(response, 'محتوای خصوصی ساختگی', status_code=409)
        self.assertEqual(ImportReceipt.objects.count(), 1)


class ProductReplayLockTests(TransactionTestCase):
    def setUp(self):
        self.author = actor('product-lock-author')
        self.other = actor('product-lock-other')
        stage([ROW], self.author)
        self.original = ProductCandidate.objects.get()

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
            ProductCandidate.objects.select_for_update().get(pk=self.original.pk)
            with ThreadPoolExecutor(max_workers=1) as executor:
                with self.assertRaises(StagingConflict) as caught:
                    executor.submit(self.worker, lambda: stage_products(io.BytesIO(make_csv([ROW])), NAME, URL,
                        actor=self.other, commit=True, rights_attested=True)).result(timeout=10)
                self.assertIsInstance(caught.exception.__cause__, OperationalError)
                self.assertEqual(caught.exception.__cause__.__cause__.sqlstate, '55P03')
        self.assertEqual(ImportReceipt.objects.count(), 1)

    def test_replay_lock_lasts_until_outer_transaction_ends(self):
        with transaction.atomic():
            stage_products(io.BytesIO(make_csv([ROW])), NAME, URL, actor=self.other, commit=True, rights_attested=True)
            with ThreadPoolExecutor(max_workers=1) as executor:
                with self.assertRaises(OperationalError) as caught:
                    executor.submit(self.worker, lambda: ProductCandidate.objects.filter(pk=self.original.pk).update(
                        irc_normalized='wrong')).result(timeout=10)
                self.assertEqual(caught.exception.__cause__.sqlstate, '55P03')
        self.assertEqual(ProductCandidate.objects.get().irc_normalized, '001')

    def test_locked_reread_rejects_oversized_json_committed_after_lookup(self):
        from catalog.intake import _find_or_create_candidate
        seen = Event()

        def lookup_then_signal(*args, **kwargs):
            result = _find_or_create_candidate(*args, **kwargs)
            seen.set()
            return result

        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch('catalog.intake._find_or_create_candidate', side_effect=lookup_then_signal):
                with transaction.atomic():
                    ProductCandidate.objects.filter(pk=self.original.pk).update(source_fields={'race-canary': 'آ' * 100_000})
                    future = executor.submit(self.worker, lambda: stage([ROW], self.other), '4s')
                    self.assertTrue(seen.wait(3), 'Replay did not complete its pre-lock lookup')
                with self.assertRaises(StagingConflict):
                    future.result(timeout=10)
        self.assertEqual(len(ProductCandidate.objects.get(pk=self.original.pk).source_fields['race-canary']), 100_000)
        self.assertEqual(ImportReceipt.objects.count(), 1)
        self.assertEqual(ImportReceiptItem.objects.count(), 1)

    def test_locked_reread_observes_concurrent_mutation_after_lookup(self):
        from catalog.intake import _find_or_create_candidate
        lookup = _find_or_create_candidate
        seen = Event()

        def lookup_then_signal(*args, **kwargs):
            result = lookup(*args, **kwargs)
            seen.set()
            return result

        with ThreadPoolExecutor(max_workers=1) as executor:
            with patch('catalog.intake._find_or_create_candidate', side_effect=lookup_then_signal):
                with transaction.atomic():
                    ProductCandidate.objects.filter(pk=self.original.pk).update(irc_normalized='wrong')
                    future = executor.submit(self.worker, lambda: stage([ROW], self.other), '4s')
                    self.assertTrue(seen.wait(3), 'Replay did not complete its pre-lock lookup')
                with self.assertRaises(StagingConflict):
                    future.result(timeout=10)
        self.assertEqual(ProductCandidate.objects.get().irc_normalized, 'wrong')
        self.assertEqual(ImportReceipt.objects.count(), 1)
