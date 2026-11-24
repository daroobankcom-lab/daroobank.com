"""Synthetic partial saves avoid fetching the discarded stored search projection."""
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import time

from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.db.models.signals import pre_save
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext

from . import test_partial_validation as fixtures
from .models import PRESENTATION_SEARCH_FIELDS, ProductPresentation
from .normalization import normalize_search


class PartialProjectionFetchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.PresentationPartialValidationTests.setUpTestData.__func__(cls)

    def assert_locked_projection_omitted(self, queries):
        selects = [q['sql'] for q in queries if q['sql'].lstrip().upper().startswith('SELECT')
                   and 'FROM "catalog_productpresentation"' in q['sql']]
        self.assertEqual(len(selects), 1, selects)
        self.assertIn('FOR UPDATE', selects[0])
        self.assertNotIn('"search_text"', selects[0].split(' FROM ', 1)[0].lower())

    def test_locked_read_ignores_stored_projection_and_rebuilds_current_fields(self):
        instance = ProductPresentation.objects.only('name_fa').get(pk=self.product.pk)
        ProductPresentation.objects.filter(pk=instance.pk).update(
            source_name='منبع تازه', strength='10 mg', search_text='projection-canary' + 'آ' * 1_000_000)
        instance.name_fa = 'نام تازه ساختگی'
        with CaptureQueriesContext(connection) as queries:
            instance.save(update_fields=['name_fa'])
        self.assert_locked_projection_omitted(queries)
        current = ProductPresentation.objects.get(pk=instance.pk)
        self.assertEqual((current.name_fa, current.source_name, current.strength),
                         ('نام تازه ساختگی', 'منبع تازه', '10 mg'))
        self.assertEqual(current.search_text, normalize_search(' '.join(getattr(current, field) for field in PRESENTATION_SEARCH_FIELDS)))
        self.assertNotIn('projection-canary', current.search_text)
        self.assertEqual(instance.search_text, current.search_text)

    def test_invalid_unwritten_field_still_blocks_partial_save_atomically(self):
        instance = ProductPresentation.objects.defer('search_text').get(pk=self.product.pk)
        ProductPresentation.objects.filter(pk=instance.pk).update(source_url='invalid', search_text='آ' * 1_000_000)
        instance.name_fa = 'تغییر نباید ثبت شود'
        seen = []
        def capture(sender, instance, **kwargs):
            seen.append(instance.pk)
        pre_save.connect(capture, sender=ProductPresentation, weak=False)
        try:
            with CaptureQueriesContext(connection) as queries, self.assertRaises(ValidationError):
                instance.save(update_fields=['name_fa'])
        finally:
            pre_save.disconnect(capture, sender=ProductPresentation)
        self.assert_locked_projection_omitted(queries)
        self.assertEqual(seen, [])
        current = ProductPresentation.objects.only('name_fa', 'source_url').get(pk=instance.pk)
        self.assertEqual((current.name_fa, current.source_url), (self.product.name_fa, 'invalid'))

    def test_direct_projection_update_recomputes_instead_of_accepting_caller_text(self):
        instance = ProductPresentation.objects.defer('search_text').get(pk=self.product.pk)
        ProductPresentation.objects.filter(pk=instance.pk).update(search_text='آ' * 1_000_000)
        instance.search_text = 'caller-canary'
        with CaptureQueriesContext(connection) as queries:
            instance.save(update_fields=['search_text'])
        self.assert_locked_projection_omitted(queries)
        current = ProductPresentation.objects.get(pk=instance.pk)
        self.assertEqual(current.search_text, normalize_search(' '.join(getattr(current, field) for field in PRESENTATION_SEARCH_FIELDS)))
        self.assertNotIn('caller-canary', current.search_text)


class PartialProjectionWaitingTests(TransactionTestCase):
    def test_waiting_save_rebuilds_using_committed_fields_without_projection_transfer(self):
        product = ProductPresentation.objects.create(
            name_fa='نام ساختگی', name_en='Synthetic', manufacturer='سازنده فرضی',
            strength='5 mg', dosage_form='قرص', package_description='10 عدد',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic')
        pids = Queue()

        def worker():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                instance = ProductPresentation.objects.only('name_fa').get(pk=product.pk)
                instance.name_fa = 'نام تازه ساختگی'
                with connection.cursor() as cursor:
                    cursor.execute('SELECT pg_backend_pid()')
                    pids.put(cursor.fetchone()[0])
                with CaptureQueriesContext(connection) as queries:
                    instance.save(update_fields=['name_fa'])
                return [q['sql'] for q in queries]
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                ProductPresentation.objects.filter(pk=product.pk).update(
                    strength='10 mg', search_text='waiting-canary' + 'آ' * 100_000)
                future = pool.submit(worker)
                pid = pids.get(timeout=8)
                deadline = time.monotonic() + 4
                blocked = False
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT cardinality(pg_blocking_pids(%s)) > 0', [pid])
                        blocked = cursor.fetchone()[0]
                    if blocked or future.done():
                        break
                    time.sleep(0.05)
                self.assertTrue(blocked, 'partial save did not wait for the selected row lock')
            queries = future.result(timeout=10)
        selects = [sql for sql in queries if 'FROM "catalog_productpresentation"' in sql and sql.startswith('SELECT')]
        self.assertEqual(len(selects), 1)
        self.assertIn('FOR UPDATE', selects[0])
        self.assertNotIn('"search_text"', selects[0].split(' FROM ', 1)[0].lower())
        product.refresh_from_db()
        self.assertEqual((product.name_fa, product.strength), ('نام تازه ساختگی', '10 mg'))
        self.assertEqual(product.search_text, normalize_search(' '.join(getattr(product, f) for f in PRESENTATION_SEARCH_FIELDS)))
        self.assertNotIn('waiting-canary', product.search_text)
