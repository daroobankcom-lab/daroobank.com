"""Opt-in synthetic search experiment, not a release or production benchmark."""
import json
import math
import os
import statistics
import time
from unittest import skipUnless
from uuid import uuid4

from django.db import connection, transaction
from django.db.models import F, Value
from django.db.models.functions import Concat
from django.test import TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import PRESENTATION_SEARCH_FIELDS, ProductPresentation
from .normalization import normalize_search
from .services import public_candidates

ROWS = 100_000
SAMPLES = 30
WRITE_SAMPLES = 5
QUERIES = {'common': 'ساختگی', 'rare': '۰۹۹۹۹۹', 'absent': 'بیسابقه', 'short': 'ن', 'literal_percent': '%'}


def percentiles(samples):
    ordered = sorted(samples)
    return {'p50_ms': round(statistics.median(ordered), 3),
            'p95_ms': round(ordered[math.ceil(len(ordered) * .95) - 1], 3)}


def summarize_plan(plan):
    nodes = []

    def visit(node):
        nodes.append({'node': node['Node Type'], 'index': node.get('Index Name'),
                      'actual_rows': node.get('Actual Rows'), 'actual_loops': node.get('Actual Loops'),
                      'actual_ms': node.get('Actual Total Time'),
                      'shared_hit': node.get('Shared Hit Blocks'), 'shared_read': node.get('Shared Read Blocks')})
        for child in node.get('Plans', []):
            visit(child)
    visit(plan['Plan'])
    return {'planning_ms': plan['Planning Time'], 'execution_ms': plan['Execution Time'], 'nodes': nodes}


@skipUnless(os.environ.get('DAROOBANK_SEARCH_BENCHMARK') == '1', 'Opt-in synthetic search benchmark is disabled')
@override_settings(DEBUG=True)
class SyntheticSearchBenchmark(TransactionTestCase):
    def test_compare_default_and_experimental_indexes(self):
        # These checks do not authenticate a host or prove cluster isolation.
        self.assertEqual(os.environ.get('DJANGO_SETTINGS_MODULE'), 'daroobank.synthetic_test_settings')
        self.assertEqual(connection.vendor, 'postgresql')
        self.assertEqual(connection.settings_dict['ENGINE'], 'daroobank.isolated_postgresql')
        self.assertRegex(connection.settings_dict['NAME'], r'^test_daroobank_synthetic_[0-9a-f]{32}$')
        self.assertTrue(connection.get_autocommit())
        self.assertEqual(ProductPresentation.objects.count(), 0)
        with connection.cursor() as cursor:
            cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_trgm'), "
                           "current_setting('server_version'), datcollate FROM pg_catalog.pg_database "
                           "WHERE datname = current_database()")
            available, server_version, collation = cursor.fetchone()
        self.assertTrue(available, 'pg_trgm must be available on the synthetic PostgreSQL server')
        now = timezone.now()
        create_start = time.perf_counter()
        for start in range(0, ROWS, 2000):
            products = []
            for i in range(start, min(start + 2000, ROWS)):
                name = 'نام\u200cساختگی' if i % 2 else 'نام ساختگی'
                values = dict(name_fa=f'{name} {i:06}', name_en='', manufacturer='سازنده ساختگی',
                              strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='')
                products.append(ProductPresentation(**values, source_name='منبع مصنوعی',
                    source_url='https://example.org/synthetic', verified_at=now, published=True,
                    irc_normalized='', search_text=normalize_search(' '.join(values[f] for f in PRESENTATION_SEARCH_FIELDS))))
            ProductPresentation.objects.bulk_create(products, batch_size=1000)
        fixture_seconds = round(time.perf_counter() - create_start, 3)
        self.assertEqual(ProductPresentation.objects.count(), ROWS)
        table = connection.ops.quote_name(ProductPresentation._meta.db_table)
        with connection.cursor() as cursor:
            cursor.execute(f'ANALYZE {table}')

        def exercise():
            results = {}
            endpoint = reverse('search_api')
            for label, query in QUERIES.items():
                # Warm the same synthetic query; measure in-process Django client, not network latency.
                first = self.client.get(endpoint, {'q': query})
                self.assertEqual(first.status_code, 200)
                body = first.json()
                ids = [row['id'] for row in body['data']]
                next_cursor = body['meta']['next_cursor']
                if label in ('common', 'short'):
                    self.assertEqual(len(ids), 30)
                    self.assertIsNotNone(next_cursor)
                    page = self.client.get(endpoint, {'q': query, 'cursor': next_cursor})
                    self.assertEqual(page.status_code, 200)
                    next_ids = [row['id'] for row in page.json()['data']]
                    self.assertEqual(len(next_ids), 30)
                    self.assertTrue(set(ids).isdisjoint(next_ids))
                else:
                    self.assertEqual(len(ids), 1 if label == 'rare' else 0)
                    self.assertIsNone(next_cursor)
                    next_ids = []
                samples = []
                for _ in range(SAMPLES):
                    start = time.perf_counter()
                    response = self.client.get(endpoint, {'q': query})
                    samples.append((time.perf_counter() - start) * 1000)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual([row['id'] for row in response.json()['data']], ids)
                qs = public_candidates().filter(search_text__contains=normalize_search(query)).order_by('name_fa', 'pk')[:151]
                plan = json.loads(qs.explain(format='json', analyze=True, buffers=True))[0]
                results[label] = {'ids': ids, 'next_ids': next_ids, 'latency': percentiles(samples),
                                  'plan': summarize_plan(plan)}
            return results

        # Rollback-only updates compare a tiny selected write workload. They do
        # not measure durable commits, full write traffic or index maintenance.
        ids_to_update = list(ProductPresentation.objects.order_by('pk').values_list('pk', flat=True)[:1000])
        self.assertEqual(len(ids_to_update), 1000)

        def exercise_rolled_back_updates():
            samples = []
            for iteration in range(WRITE_SAMPLES + 1):
                start = time.perf_counter()
                with transaction.atomic():
                    changed = ProductPresentation.objects.filter(pk__in=ids_to_update).update(
                        search_text=Concat(F('search_text'), Value(' probe')))
                    self.assertEqual(changed, 1000)
                    transaction.set_rollback(True)
                if iteration:
                    samples.append((time.perf_counter() - start) * 1000)
            self.assertFalse(ProductPresentation.objects.filter(pk__in=ids_to_update, search_text__endswith=' probe').exists())
            return percentiles(samples)

        baseline = exercise()
        baseline_update = exercise_rolled_back_updates()
        index_name = 'synthetic_search_trgm_' + uuid4().hex
        index = connection.ops.quote_name(index_name)
        with connection.cursor() as cursor:
            cursor.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm')
            start = time.perf_counter()
            cursor.execute(f'CREATE INDEX {index} ON {table} USING gin (search_text gin_trgm_ops)')
            index_seconds = round(time.perf_counter() - start, 3)
            cursor.execute(f'ANALYZE {table}')
            cursor.execute('SELECT pg_relation_size(%s::regclass)', [index_name])
            index_bytes = cursor.fetchone()[0]
        indexed = exercise()
        indexed_update = exercise_rolled_back_updates()

        # A partial ordering index is a separate built-in B-tree candidate, not
        # a migration. The same test DB retains both until the next comparison.
        order_name = 'synthetic_search_order_' + uuid4().hex
        order_index = connection.ops.quote_name(order_name)
        with connection.cursor() as cursor:
            start = time.perf_counter()
            cursor.execute(f'CREATE INDEX {order_index} ON {table} (name_fa, id) '
                           'WHERE published AND verified_at IS NOT NULL')
            order_seconds = round(time.perf_counter() - start, 3)
            cursor.execute(f'ANALYZE {table}')
            cursor.execute('SELECT pg_relation_size(%s::regclass)', [order_name])
            order_bytes = cursor.fetchone()[0]
        both = exercise()
        both_update = exercise_rolled_back_updates()
        # Remove only the exact GIN index this test created, in the test DB.
        with connection.cursor() as cursor:
            cursor.execute(f'DROP INDEX {index}')
            cursor.execute(f'ANALYZE {table}')
        order_only = exercise()
        order_update = exercise_rolled_back_updates()
        phases = {'baseline': baseline, 'experimental_trigram': indexed,
                  'both_indexes': both, 'ordering_index_only': order_only}
        for results in phases.values():
            for label in QUERIES:
                self.assertEqual(baseline[label]['ids'], results[label]['ids'])
                self.assertEqual(baseline[label]['next_ids'], results[label]['next_ids'])
        # Only aggregate measurements and plan node types are printed; no fixture rows.
        for results in phases.values():
            for result in results.values():
                del result['ids'], result['next_ids']
        print('SYNTHETIC_SEARCH_BENCHMARK ' + json.dumps({
            'rows': ROWS, 'samples_per_query_and_phase': SAMPLES, 'fixture_seconds': fixture_seconds,
            'postgresql_version': server_version, 'database_collation': collation,
            'trigram_index_build_seconds': index_seconds, 'trigram_index_bytes': index_bytes,
            'ordering_index_build_seconds': order_seconds, 'ordering_index_bytes': order_bytes,
            'rolled_back_updates': {'rows_per_transaction': 1000, 'samples_per_phase': WRITE_SAMPLES,
                                    'baseline': baseline_update, 'experimental_trigram': indexed_update,
                                    'both_indexes': both_update, 'ordering_index_only': order_update},
            'phases': phases,
        }, sort_keys=True))
