"""Real PostgreSQL concurrency tests; all inputs are synthetic."""
import csv
import io
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TransactionTestCase

from catalog.intake import stage_products
from catalog.models import ProductCandidate
from ingestion.locks import lock_source_stage, source_lock_key
from ingestion.models import ImportReceipt
from ingestion.receipts import manifest_context, stage_price_with_receipt, stage_product_with_receipt
from pricing.importer import stage_csv
from pricing.models import PriceCandidate

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = (ROOT / 'examples/product_candidates.synthetic.csv').read_bytes()
PRICE = (ROOT / 'examples/price_candidates.synthetic.csv').read_bytes()


def reverse_rows(data):
    reader = csv.reader(io.StringIO(data.decode('utf-8'), newline=''))
    header = next(reader)
    rows = list(reader)
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(header)
    writer.writerows(reversed(rows))
    return output.getvalue().encode('utf-8')


def thread_try_lock(domain, url):
    close_old_connections()
    try:
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute('SELECT pg_try_advisory_xact_lock(%s)', [source_lock_key(domain, url)])
            return cursor.fetchone()[0]
    finally:
        connection.close()


class SourceStagingLockTests(TransactionTestCase):
    def setUp(self):
        self.url = 'https://example.org/fixtures'
        User = get_user_model()
        self.users = [User.objects.create_user(f'concurrent-stager-{i}', is_staff=True) for i in range(2)]
        for user in self.users:
            for app, codes in [('catalog', ['view_productcandidate', 'add_productcandidate']),
                               ('pricing', ['view_pricecandidate', 'add_pricecandidate'])]:
                user.user_permissions.add(*Permission.objects.filter(content_type__app_label=app, codename__in=codes))

    def test_key_is_stable_scoped_and_requires_a_transaction(self):
        self.assertEqual(source_lock_key('product', self.url), source_lock_key('product', self.url))
        self.assertNotEqual(source_lock_key('price', self.url), source_lock_key('product', self.url))
        self.assertNotEqual(source_lock_key('product', self.url), source_lock_key('product', self.url + '/other'))
        self.assertTrue(-(2**63) <= source_lock_key('price', self.url) < 2**63)
        with self.assertRaises(ValueError): source_lock_key('other', self.url)
        with self.assertRaises(ValueError): source_lock_key('product', '')
        with self.assertRaises(RuntimeError): lock_source_stage('product', self.url)
        with transaction.atomic():
            lock_source_stage('product', self.url)
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertFalse(pool.submit(thread_try_lock, 'product', self.url).result(timeout=10))
                self.assertTrue(pool.submit(thread_try_lock, 'price', self.url).result(timeout=10))
                self.assertTrue(pool.submit(thread_try_lock, 'product', self.url + '/other').result(timeout=10))
        with ThreadPoolExecutor(max_workers=1) as pool:
            self.assertTrue(pool.submit(thread_try_lock, 'product', self.url).result(timeout=10))

    def test_savepoint_rollback_does_not_leave_a_lock(self):
        with transaction.atomic():
            try:
                with transaction.atomic():
                    lock_source_stage('product', self.url)
                    raise ValueError('rollback synthetic staging')
            except ValueError:
                pass
            with ThreadPoolExecutor(max_workers=1) as pool:
                self.assertTrue(pool.submit(thread_try_lock, 'product', self.url).result(timeout=10))

    def test_previews_do_not_wait_for_staging_lock(self):
        def preview(domain):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=self.users[1].pk)
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '2s'")
                    cursor.execute("SET statement_timeout = '5s'")
                if domain == 'product':
                    return stage_products(io.BytesIO(PRODUCT), 'نمونه', self.url, actor=user)
                return stage_csv(io.BytesIO(PRICE), 'نمونه', self.url, staged_by=user)
            finally:
                connection.close()
        for domain in ('product', 'price'):
            with self.subTest(domain=domain), transaction.atomic():
                lock_source_stage(domain, self.url)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    result = pool.submit(preview, domain).result(timeout=10)
                self.assertEqual(result['rows'], 2)
                self.assertEqual(result['created'], 0)
        self.assertEqual(ProductCandidate.objects.count(), 0)
        self.assertEqual(PriceCandidate.objects.count(), 0)
        self.assertEqual(ImportReceipt.objects.count(), 0)

    def test_direct_committed_staging_uses_same_lock_as_receipt_path(self):
        def direct_stage(domain):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.users[0].pk)
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '250ms'")
                    cursor.execute("SET statement_timeout = '5s'")
                if domain == 'product':
                    return stage_products(io.BytesIO(PRODUCT), 'نمونه', self.url, actor=actor,
                                          commit=True, rights_attested=True)
                return stage_csv(io.BytesIO(PRICE), 'نمونه', self.url, staged_by=actor,
                                 commit=True, rights_attested=True)
            finally:
                connection.close()
        for domain in ('product', 'price'):
            with self.subTest(domain=domain), transaction.atomic():
                lock_source_stage(domain, self.url)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with self.assertRaises(OperationalError):
                        pool.submit(direct_stage, domain).result(timeout=10)
        self.assertEqual(ProductCandidate.objects.count(), 0)
        self.assertEqual(PriceCandidate.objects.count(), 0)
        self.assertEqual(ImportReceipt.objects.count(), 0)

    def exercise_reversed_imports(self, domain, *, fail_first=False):
        from ingestion import receipts
        service, data, model = ((stage_product_with_receipt, PRODUCT, ProductCandidate) if domain == 'product'
                                else (stage_price_with_receipt, PRICE, PriceCandidate))
        first_receipt_started, release_first = Event(), Event()
        second_pid = Queue()
        original_write = receipts._write_items

        def paused_write(receipt, outcomes, counts):
            if receipt.actor_id == self.users[0].pk:
                first_receipt_started.set()
                if not release_first.wait(10):
                    raise TimeoutError('Test failed to release first staging transaction')
                if fail_first:
                    raise RuntimeError('synthetic manifest write failure')
            return original_write(receipt, outcomes, counts)

        def worker(user_id, content, pid_queue=None):
            close_old_connections()
            try:
                user = get_user_model().objects.get(pk=user_id)
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '8s'")
                    cursor.execute("SET statement_timeout = '15s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    pid = cursor.fetchone()[0]
                if pid_queue is not None:
                    pid_queue.put(pid)
                counts, receipt = service(io.BytesIO(content), 'منبع ساختگی', self.url, actor=user, rights_attested=True)
                return counts, receipt.pk
            finally:
                connection.close()

        with patch('ingestion.receipts._write_items', side_effect=paused_write):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(worker, self.users[0].pk, data)
                try:
                    self.assertTrue(first_receipt_started.wait(8), 'First stage did not reach receipt creation')
                    second = pool.submit(worker, self.users[1].pk, reverse_rows(data), second_pid)
                    pid = second_pid.get(timeout=8)
                    deadline = time.monotonic() + 5
                    waiting = False
                    while time.monotonic() < deadline:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE pid = %s AND locktype = 'advisory' AND NOT granted)", [pid])
                            waiting = cursor.fetchone()[0]
                        if waiting: break
                        if second.done(): break
                        time.sleep(0.05)
                    self.assertTrue(waiting, 'Second stage did not wait on the transaction advisory lock')
                finally:
                    release_first.set()
                if fail_first:
                    with self.assertRaisesRegex(RuntimeError, 'synthetic manifest write failure'):
                        first.result(timeout=12)
                    second_result = second.result(timeout=12)
                else:
                    first_result, second_result = first.result(timeout=12), second.result(timeout=12)
        if fail_first:
            self.assertEqual((second_result[0]['created'], second_result[0]['duplicates']), (2, 0))
            self.assertEqual(model.objects.count(), 2)
            self.assertTrue(all(row.staged_by_id == self.users[1].pk for row in model.objects.all()))
            self.assertEqual(ImportReceipt.objects.count(), 1)
            receipt = ImportReceipt.objects.get(pk=second_result[1])
            self.assertEqual(receipt.actor_id, self.users[1].pk)
            self.assertEqual(manifest_context(receipt, 1)['status'], 'available')
            return
        self.assertEqual((first_result[0]['created'], first_result[0]['duplicates']), (2, 0))
        self.assertEqual((second_result[0]['created'], second_result[0]['duplicates']), (0, 2))
        self.assertEqual(model.objects.count(), 2)
        first_receipt = ImportReceipt.objects.get(pk=first_result[1])
        second_receipt = ImportReceipt.objects.get(pk=second_result[1])
        self.assertEqual((first_receipt.actor_id, second_receipt.actor_id), (self.users[0].pk, self.users[1].pk))
        self.assertEqual(list(first_receipt.items.values_list('source_record_id', flat=True)),
                         list(reversed(list(second_receipt.items.values_list('source_record_id', flat=True)))))
        self.assertEqual(manifest_context(first_receipt, 1)['status'], 'available')
        self.assertEqual(manifest_context(second_receipt, 1)['status'], 'available')
        self.assertTrue(all(row.staged_by_id == self.users[0].pk for row in model.objects.all()))

    def test_reversed_product_imports_serialize_with_complete_receipts(self):
        self.exercise_reversed_imports('product')

    def test_reversed_price_imports_serialize_with_complete_receipts(self):
        self.exercise_reversed_imports('price')

    def test_product_import_waiter_succeeds_after_first_rolls_back(self):
        self.exercise_reversed_imports('product', fail_first=True)

    def test_price_import_waiter_succeeds_after_first_rolls_back(self):
        self.exercise_reversed_imports('price', fail_first=True)
