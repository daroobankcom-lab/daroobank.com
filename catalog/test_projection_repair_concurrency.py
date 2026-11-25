"""Selected real PostgreSQL locking interleavings for projection repair."""
from concurrent.futures import ThreadPoolExecutor
import io
from threading import Event, current_thread
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings

from .models import ProductPresentation
from .projection_repair import ProjectionRepairError, apply_projection, preview_projection


@override_settings(DEBUG=True, SECRET_KEY='synthetic-concurrent-test-key')
class ProjectionRepairConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.product = ProductPresentation.objects.create(
            name_fa='فرآورده ساختگی', manufacturer='سازنده فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', irc='001',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic')
        ProductPresentation.objects.filter(pk=self.product.pk).update(irc='002')
        self.token = preview_projection(presentation_id=self.product.pk)['token']

    def worker(self, func, lock_timeout='5s'):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT set_config('lock_timeout', %s, false)", [lock_timeout])
                cursor.execute("SET statement_timeout = '12s'")
            return func()
        finally:
            connection.close()

    def apply(self):
        return apply_projection(presentation_id=self.product.pk, token=self.token, synthetic_confirmed=True)

    def test_source_writer_blocks_repair_then_stale_token_is_rejected(self):
        with transaction.atomic():
            product = ProductPresentation.objects.select_for_update().get(pk=self.product.pk)
            product.strength = '10 mg'
            product.save(update_fields=['strength'])
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(ProjectionRepairError) as caught:
                    pool.submit(self.worker, self.apply, '300ms').result(timeout=10)
                self.assertIsInstance(caught.exception.__cause__, OperationalError)
                self.assertEqual(caught.exception.__cause__.__cause__.sqlstate, '55P03')
        with self.assertRaises(ProjectionRepairError): self.apply()
        self.product.refresh_from_db()
        self.assertEqual(self.product.strength, '10 mg')
        # The controlled model save itself refreshed the projections.
        self.assertEqual(preview_projection(presentation_id=self.product.pk)['status'], 'consistent')

    def test_cli_real_lock_timeout_reports_generic_error_without_partial_output(self):
        output = io.StringIO()
        before = ProductPresentation.objects.values().get(pk=self.product.pk)
        def command():
            call_command('repair_catalog_projection', presentation_id=self.product.pk, commit=True,
                         token=self.token, confirm_synthetic=True, stdout=output)
        with transaction.atomic():
            ProductPresentation.objects.select_for_update().get(pk=self.product.pk)
            with ThreadPoolExecutor(max_workers=1) as pool:
                with self.assertRaises(CommandError) as caught:
                    pool.submit(self.worker, command, '300ms').result(timeout=10)
        self.assertEqual(str(caught.exception), 'Projection request is unavailable, invalid, unsafe or stale.')
        self.assertNotIn(self.token, str(caught.exception))
        self.assertEqual(output.getvalue(), '')
        self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)
        self.assertEqual(self.apply()['status'], 'repaired')

    def test_repair_locks_row_against_a_concurrent_writer(self):
        from . import projection_repair
        ready, resume = Event(), Event()
        worker_thread = []
        original = projection_repair._state_digest
        def pause_after_lock(row, expected):
            if worker_thread and current_thread() is worker_thread[0]:
                ready.set()
                if not resume.wait(8):
                    raise TimeoutError('Test did not release repair')
            return original(row, expected)
        def do_repair():
            worker_thread.append(current_thread())
            return self.apply()
        def change_source():
            ProductPresentation.objects.filter(pk=self.product.pk).update(strength='different')
        with patch('catalog.projection_repair._state_digest', side_effect=pause_after_lock):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(self.worker, do_repair)
                try:
                    self.assertTrue(ready.wait(8), 'Repair did not reach locked recheck')
                    with self.assertRaises(OperationalError):
                        pool.submit(self.worker, change_source, '300ms').result(timeout=10)
                finally:
                    resume.set()
                self.assertEqual(first.result(timeout=10)['status'], 'repaired')
        self.product.refresh_from_db()
        self.assertEqual((self.product.strength, self.product.irc_normalized), ('5 mg', '002'))
