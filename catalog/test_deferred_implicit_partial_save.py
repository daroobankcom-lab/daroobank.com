"""Synthetic deferred presentation saves preserve Django's implicit partial intent."""
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.db.models.signals import pre_save
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from .models import PRESENTATION_SEARCH_FIELDS, ProductPresentation
from .normalization import normalize_search


def product():
    return ProductPresentation.objects.create(
        name_fa='نام ساختگی', name_en='Synthetic', manufacturer='سازنده فرضی', strength='5 mg',
        dosage_form='قرص', package_description='10 عدد', source_name='منبع ساختگی',
        source_url='https://example.org/synthetic')


class DeferredImplicitPartialSaveTests(TestCase):
    def test_implicit_partial_save_uses_one_locked_read_and_reports_changed_fields(self):
        original = product()
        instance = ProductPresentation.objects.only('name_fa').get(pk=original.pk)
        instance.name_fa = 'نام جدید ساختگی'
        instance.source_name = 'منبع جدید ساختگی'  # assigned deferred field is now loaded
        seen = []
        def observe(sender, instance, update_fields, **kwargs):
            seen.append(update_fields)
        pre_save.connect(observe, sender=ProductPresentation, weak=False)
        try:
            with CaptureQueriesContext(connection) as queries:
                instance.save()
        finally:
            pre_save.disconnect(observe, sender=ProductPresentation)
        selected = [query['sql'] for query in queries if query['sql'].startswith('SELECT')
                    and 'FROM "catalog_productpresentation"' in query['sql']]
        self.assertEqual(len(selected), 1, selected)
        self.assertIn('FOR UPDATE', selected[0])
        self.assertNotIn('"search_text"', selected[0].split(' FROM ', 1)[0].lower())
        self.assertEqual(seen, [frozenset({'name_fa', 'source_name', 'search_text', 'irc_normalized'})])
        current = ProductPresentation.objects.get(pk=original.pk)
        self.assertEqual((current.name_fa, current.source_name), ('نام جدید ساختگی', 'منبع جدید ساختگی'))
        self.assertEqual(current.search_text, normalize_search(' '.join(getattr(current, f) for f in PRESENTATION_SEARCH_FIELDS)))

    def test_invalid_current_unloaded_field_rejects_write_without_signals(self):
        original = product()
        instance = ProductPresentation.objects.only('name_fa').get(pk=original.pk)
        instance.name_fa = 'نباید ثبت شود'
        ProductPresentation.objects.filter(pk=original.pk).update(source_url='invalid')
        seen = []
        def observe(sender, instance, **kwargs):
            seen.append(instance.pk)
        pre_save.connect(observe, sender=ProductPresentation, weak=False)
        try:
            with self.assertRaises(ValidationError):
                instance.save()
        finally:
            pre_save.disconnect(observe, sender=ProductPresentation)
        self.assertEqual(seen, [])
        self.assertEqual(ProductPresentation.objects.get(pk=original.pk).name_fa, original.name_fa)

    def test_missing_deferred_row_is_not_reinserted(self):
        original = product()
        instance = ProductPresentation.objects.only('name_fa').get(pk=original.pk)
        ProductPresentation.objects.filter(pk=original.pk).delete()
        instance.name_fa = 'نباید دوباره ساخته شود'
        with self.assertRaises(ProductPresentation.DoesNotExist):
            instance.save()
        self.assertFalse(ProductPresentation.objects.filter(pk=original.pk).exists())

    def test_force_update_still_uses_implicit_partial_fields(self):
        original = product()
        instance = ProductPresentation.objects.only('name_fa').get(pk=original.pk)
        instance.name_fa = 'به‌روزرسانی ساختگی'
        with CaptureQueriesContext(connection) as queries:
            instance.save(force_update=True)
        selects = [q['sql'] for q in queries if 'FROM "catalog_productpresentation"' in q['sql']]
        self.assertEqual(len(selects), 1)
        self.assertIn('FOR UPDATE', selects[0])
        self.assertEqual(ProductPresentation.objects.get(pk=original.pk).name_fa, 'به‌روزرسانی ساختگی')

    def test_primary_key_only_and_cross_database_keep_full_save_intent(self):
        original = product()
        instance = ProductPresentation.objects.only('pk').get(pk=original.pk)
        with patch.object(ProductPresentation, '_save_with_projection', return_value=None) as full_save:
            instance.save()
        self.assertIsNone(full_save.call_args.kwargs['update_fields'])
        deferred = ProductPresentation.objects.only('name_fa').get(pk=original.pk)
        with patch.object(ProductPresentation, '_save_with_projection', return_value=None) as full_save:
            deferred.save(using='other-database')
        self.assertIsNone(full_save.call_args.kwargs['update_fields'])
        self.assertEqual(full_save.call_args.kwargs['using'], 'other-database')

    def test_explicit_empty_update_fields_remains_noop(self):
        original = product()
        instance = ProductPresentation.objects.only('name_fa').get(pk=original.pk)
        instance.name_fa = 'نباید ثبت شود'
        with CaptureQueriesContext(connection) as queries:
            instance.save(update_fields=[])
        self.assertEqual(len(queries), 0)
        self.assertEqual(ProductPresentation.objects.get(pk=original.pk).name_fa, original.name_fa)


class DeferredImplicitPartialWaitingTests(TransactionTestCase):
    def test_waiting_implicit_save_keeps_new_committed_unloaded_field(self):
        original = product()
        instance = ProductPresentation.objects.only('name_fa').get(pk=original.pk)
        instance.name_fa = 'نام جدید ساختگی'
        pids = Queue()

        def worker():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '12s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    pid = cursor.fetchone()[0]
                announced = False
                def observe(execute, sql, params, many, context):
                    nonlocal announced
                    if (not announced and '"catalog_productpresentation"' in sql
                            and ('FOR UPDATE' in sql or sql.lstrip().startswith('UPDATE'))):
                        announced = True
                        pids.put(pid)
                    return execute(sql, params, many, context)
                with connection.execute_wrapper(observe):
                    instance.save()
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                ProductPresentation.objects.filter(pk=original.pk).update(
                    strength='10 mg', search_text='stale-projection-canary' + 'آ' * 100_000)
                future = pool.submit(worker)
                pid = pids.get(timeout=10)
                deadline = time.monotonic() + 4
                blocked = False
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT cardinality(pg_blocking_pids(%s)) > 0', [pid])
                        blocked = cursor.fetchone()[0]
                    if blocked or future.done():
                        break
                    time.sleep(0.05)
                self.assertTrue(blocked, 'implicit save did not wait for the row update')
            future.result(timeout=10)
        current = ProductPresentation.objects.get(pk=original.pk)
        self.assertEqual((current.name_fa, current.strength), ('نام جدید ساختگی', '10 mg'))
        self.assertEqual(current.search_text, normalize_search(' '.join(getattr(current, f) for f in PRESENTATION_SEARCH_FIELDS)))
        self.assertNotIn('stale-projection-canary', current.search_text)
