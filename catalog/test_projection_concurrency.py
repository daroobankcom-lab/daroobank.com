"""Synthetic PostgreSQL tests for presentation projection updates."""
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Event, current_thread
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.db.models.signals import post_save, pre_save
from django.utils.deprecation import RemovedInDjango60Warning

from .models import ProductPresentation
from .normalization import normalize_search
from .quality import SEARCH_FIELDS


class ProjectionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.product = ProductPresentation.objects.create(
            name_fa='نمونه نخست', name_en='Synthetic', manufacturer='سازنده فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', irc='۰۰۱',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic')

    def assert_projection(self):
        product = ProductPresentation.objects.get(pk=self.product.pk)
        self.assertEqual(product.irc_normalized, normalize_search(product.irc))
        self.assertEqual(product.search_text, normalize_search(' '.join(getattr(product, f) for f in SEARCH_FIELDS)))
        return product

    def worker(self, func, lock_timeout='5s'):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('lock_timeout', %s, false)", [lock_timeout])
                cursor.execute("SET statement_timeout = '12s'")
            return func()
        finally:
            connection.close()

    def test_concurrent_partial_saves_serialize_before_projection_read(self):
        paused, resume = Event(), Event()
        first_thread = []
        def pause_normalization(value):
            if first_thread and current_thread() is first_thread[0] and not paused.is_set():
                paused.set()
                if not resume.wait(8):
                    raise TimeoutError('Test failed to resume first update')
            return normalize_search(value)
        def change_name():
            first_thread.append(current_thread())
            p = ProductPresentation.objects.get(pk=self.product.pk)
            p.name_fa = 'نام تازه'
            p.save(update_fields=['name_fa'])
        def change_strength():
            p = ProductPresentation.objects.get(pk=self.product.pk)
            p.strength = '10 mg'
            p.save(update_fields=['strength'])
        with patch('catalog.models.normalize_search', side_effect=pause_normalization):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.worker, change_name)
                try:
                    self.assertTrue(paused.wait(8), 'First update did not reach projection computation')
                    second = pool.submit(self.worker, change_strength, '300ms')
                    with self.assertRaises(OperationalError):
                        second.result(timeout=10)
                finally:
                    resume.set()
                first.result(timeout=10)
                pool.submit(self.worker, change_strength).result(timeout=10)
        product = self.assert_projection()
        self.assertEqual((product.name_fa, product.strength), ('نام تازه', '10 mg'))
        self.assertEqual(ProductPresentation.objects.filter(search_text__contains='10 mg').count(), 1)

    def test_waiting_partial_save_uses_the_committed_first_update(self):
        paused, resume = Event(), Event()
        first_thread = []
        second_pid = Queue()
        def pause_normalization(value):
            if first_thread and current_thread() is first_thread[0] and not paused.is_set():
                paused.set()
                if not resume.wait(8):
                    raise TimeoutError('Test failed to resume first update')
            return normalize_search(value)
        def change_name():
            first_thread.append(current_thread())
            product = ProductPresentation.objects.get(pk=self.product.pk)
            product.name_fa = 'نام هم‌زمان'
            product.save(update_fields=['name_fa'])
        def change_irc():
            product = ProductPresentation.objects.get(pk=self.product.pk)
            product.irc = '۰۰۳'
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_backend_pid()')
                second_pid.put(cursor.fetchone()[0])
            product.save(update_fields=['irc'])
        with patch('catalog.models.normalize_search', side_effect=pause_normalization):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.worker, change_name)
                try:
                    self.assertTrue(paused.wait(8), 'First update did not reach projection computation')
                    second = pool.submit(self.worker, change_irc)
                    pid = second_pid.get(timeout=8)
                    deadline = time.monotonic() + 4
                    blocked = False
                    while time.monotonic() < deadline:
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT cardinality(pg_blocking_pids(%s)) > 0', [pid])
                            blocked = cursor.fetchone()[0]
                        if blocked or second.done():
                            break
                        time.sleep(0.05)
                    self.assertTrue(blocked, 'Second update did not wait on the row lock')
                finally:
                    resume.set()
                first.result(timeout=10)
                second.result(timeout=10)
        product = self.assert_projection()
        self.assertEqual((product.name_fa, product.irc_normalized), ('نام هم‌زمان', '003'))
        from pricing.importer import suggest_product
        match = {'irc': '۰۰۳', 'manufacturer': product.manufacturer, 'strength': product.strength,
                 'dosage_form': product.dosage_form, 'package_description': product.package_description}
        status, matched = suggest_product(match)
        self.assertEqual((status, matched.pk), ('suggested', product.pk))

    def test_waiting_partial_save_validates_against_committed_publication(self):
        from datetime import datetime, timezone

        self.product.verified_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.product.save(update_fields=['verified_at'])
        paused, resume = Event(), Event()
        first_thread = []
        second_pid = Queue()
        stale_loaded = Event()
        start_second = Event()

        def pause_first(value):
            if first_thread and current_thread() is first_thread[0] and not paused.is_set():
                paused.set()
                if not resume.wait(8):
                    raise TimeoutError('Test failed to resume publication')
            return normalize_search(value)

        def publish():
            first_thread.append(current_thread())
            product = ProductPresentation.objects.get(pk=self.product.pk)
            product.published = True
            product.save(update_fields=['published'])

        def remove_verification():
            product = ProductPresentation.objects.get(pk=self.product.pk)
            self.assertFalse(product.published)
            stale_loaded.set()
            if not start_second.wait(8):
                raise TimeoutError('Test failed to start competing save')
            product.verified_at = None
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_backend_pid()')
                second_pid.put(cursor.fetchone()[0])
            product.save(update_fields=['verified_at'])

        with patch('catalog.models.normalize_search', side_effect=pause_first):
            with ThreadPoolExecutor(max_workers=2) as pool:
                second = pool.submit(self.worker, remove_verification)
                try:
                    self.assertTrue(stale_loaded.wait(8))
                    first = pool.submit(self.worker, publish)
                    self.assertTrue(paused.wait(8))
                    start_second.set()
                    pid = second_pid.get(timeout=8)
                    deadline = time.monotonic() + 4
                    blocked = False
                    while time.monotonic() < deadline:
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT cardinality(pg_blocking_pids(%s)) > 0', [pid])
                            blocked = cursor.fetchone()[0]
                        if blocked or second.done():
                            break
                        time.sleep(0.05)
                    self.assertTrue(blocked, 'Second save did not wait for publication')
                finally:
                    start_second.set()
                    resume.set()
                first.result(timeout=10)
                with self.assertRaises(ValidationError):
                    second.result(timeout=10)
        current = self.assert_projection()
        self.assertTrue(current.published)
        self.assertIsNotNone(current.verified_at)

    def test_stale_instance_partial_update_uses_current_other_fields(self):
        stale = ProductPresentation.objects.get(pk=self.product.pk)
        fresh = ProductPresentation.objects.get(pk=self.product.pk)
        fresh.irc = '۰۰۲'
        fresh.strength = '20 mg'
        fresh.save(update_fields=['irc', 'strength'])
        stale.name_fa = 'نام دیگر'
        stale.save(update_fields=['name_fa'])
        product = self.assert_projection()
        self.assertEqual((product.name_fa, product.strength, product.irc_normalized), ('نام دیگر', '20 mg', '002'))
        self.assertEqual(ProductPresentation.objects.filter(irc_normalized='002').count(), 1)

    def test_legacy_positional_update_fields_maintain_projection(self):
        stale = ProductPresentation.objects.get(pk=self.product.pk)
        ProductPresentation.objects.filter(pk=self.product.pk).update(strength='20 mg')
        stale.name_fa = 'نام تازه'
        with self.assertWarns(RemovedInDjango60Warning):
            stale.save(False, False, None, ['name_fa'])
        product = self.assert_projection()
        self.assertEqual((product.name_fa, product.strength), ('نام تازه', '20 mg'))

    def test_failed_write_rolls_back_and_releases_lock(self):
        before = ProductPresentation.objects.values().get(pk=self.product.pk)
        self.product.name_fa = 'تغییر ناموفق'
        with patch.object(ProductPresentation, 'save_base', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaisesRegex(RuntimeError, 'synthetic failure'):
                self.product.save(using='default', update_fields=['name_fa'])
        self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)
        def retry():
            p = ProductPresentation.objects.get(pk=self.product.pk)
            p.name_fa = 'تغییر پس از خطا'
            p.save(using='default', update_fields=['name_fa'])
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(self.worker, retry, '300ms').result(timeout=10)
        self.assertEqual(self.assert_projection().name_fa, 'تغییر پس از خطا')

    def test_bulk_update_bypasses_projection_maintenance(self):
        from .quality import inspect_batch
        ProductPresentation.objects.filter(pk=self.product.pk).update(irc='002', strength='20 mg')
        damaged = inspect_batch()['rows'][0]
        self.assertIn('irc_projection', damaged['issues'])
        self.assertIn('search_projection', damaged['issues'])
        # A later controlled partial save refreshes both projections, but this is
        # not an automatic repair for arbitrary bypassed writes.
        fresh = ProductPresentation.objects.get(pk=self.product.pk)
        fresh.source_name = 'منبع دیگر'
        fresh.save(update_fields=['source_name'])
        self.assert_projection()
        self.assertNotIn('irc_projection', inspect_batch()['rows'][0]['issues'])

    def test_outer_transaction_keeps_row_lock_after_nested_save(self):
        def competing():
            product = ProductPresentation.objects.get(pk=self.product.pk)
            product.strength = '30 mg'
            product.save(update_fields=['strength'])
        with transaction.atomic():
            self.product.name_fa = 'نام در تراکنش'
            self.product.save(update_fields=['name_fa'])
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(OperationalError):
                    pool.submit(self.worker, competing, '300ms').result(timeout=10)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(self.worker, competing).result(timeout=10)
        product = self.assert_projection()
        self.assertEqual((product.name_fa, product.strength), ('نام در تراکنش', '30 mg'))

    def test_partial_save_signals_and_deferred_instance(self):
        events = []
        def before(sender, instance, **kwargs):
            events.append(('pre', kwargs['using'], kwargs['update_fields']))
        def after(sender, instance, **kwargs):
            events.append(('post', kwargs['using'], kwargs['update_fields'], kwargs['created']))
        pre_save.connect(before, sender=ProductPresentation, weak=False)
        post_save.connect(after, sender=ProductPresentation, weak=False)
        try:
            product = ProductPresentation.objects.only('pk', 'name_fa').get(pk=self.product.pk)
            product.name_fa = 'نام دارای سیگنال'
            product.save(using='default', update_fields=['name_fa'])
            product.save(update_fields=[])
        finally:
            pre_save.disconnect(before, sender=ProductPresentation)
            post_save.disconnect(after, sender=ProductPresentation)
        expected = frozenset({'name_fa', 'search_text', 'irc_normalized'})
        self.assertEqual(events, [('pre', 'default', expected), ('post', 'default', expected, False)])
        self.assertEqual(self.assert_projection().name_fa, 'نام دارای سیگنال')

    def test_empty_update_and_invalid_partial_save_leave_database_unchanged(self):
        before = ProductPresentation.objects.values().get(pk=self.product.pk)
        self.product.name_fa = ''
        with CaptureQueriesContext(connection) as queries:
            self.product.save(update_fields=[])
            self.product.save(update_fields=iter(()))
        self.assertEqual(len(queries), 0)
        self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)
        with self.assertRaises(ValidationError):
            self.product.save(update_fields=['name_fa'])
        self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)
        self.assert_projection()
