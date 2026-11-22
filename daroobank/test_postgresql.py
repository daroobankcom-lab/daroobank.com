"""PostgreSQL integration checks with synthetic data only."""
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import DataError, IntegrityError, close_old_connections, connection, transaction
from django.test import SimpleTestCase, TestCase, TransactionTestCase

from catalog.models import ProductCandidate, ProductPresentation
from clinical.models import ClinicalDraft, ClinicalDraftReview
from clinical.services import DraftConflict, create_draft, review_draft
from tools.wait_for_database import wait_for_database

ROOT = Path(__file__).resolve().parent.parent


class PostgreSQLConfigurationTests(SimpleTestCase):
    def test_only_postgresql_backend_configured(self):
        self.assertEqual({db['ENGINE'] for db in settings.DATABASES.values()}, {'django.db.backends.postgresql'})
        self.assertTrue(settings.DATABASES['default']['CONN_HEALTH_CHECKS'])

    def test_missing_required_configuration_fails_closed(self):
        env = {**os.environ, 'DAROOBANK_DEBUG': '1'}
        env.pop('POSTGRES_DB', None)
        proc = subprocess.run([sys.executable, str(ROOT / 'manage.py'), 'check'], env=env,
                              capture_output=True, text=True, timeout=15)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn('POSTGRES_DB is required for PostgreSQL', proc.stderr)

    def test_wait_retries_only_database_operational_errors(self):
        from django.db import OperationalError
        with patch('tools.wait_for_database.connections') as connections, patch('tools.wait_for_database.time.sleep'):
            connections.__getitem__.return_value.cursor.side_effect = [OperationalError('unavailable'),
                                                                        connections.__getitem__.return_value.cursor.return_value]
            self.assertTrue(wait_for_database(timeout=1, interval=0))
            self.assertEqual(connections.__getitem__.return_value.close.call_count, 1)
        with patch('tools.wait_for_database.connections') as connections:
            connections.__getitem__.return_value.cursor.side_effect = OperationalError('unavailable')
            self.assertFalse(wait_for_database(timeout=0))


class PostgreSQLIntegrationTests(TestCase):
    def test_migrated_models_declared_constraints_indexes_and_foreign_keys(self):
        with connection.cursor() as cursor:
            tables = set(connection.introspection.table_names(cursor))
            for model in apps.get_models(include_auto_created=True):
                table = model._meta.db_table
                with self.subTest(model=model._meta.label):
                    self.assertIn(table, tables)
                    constraints = connection.introspection.get_constraints(cursor, table)
                    for declared in [*model._meta.constraints, *model._meta.indexes]:
                        self.assertIn(declared.name, constraints)
                    for field in model._meta.local_fields:
                        if field.many_to_one and field.db_constraint:
                            self.assertTrue(any(item['foreign_key'] and item['columns'] == [field.column]
                                                for item in constraints.values()), field.name)

    def test_database_driver_encoding_relationships_and_indexes(self):
        self.assertEqual(connection.vendor, 'postgresql')
        connection.ensure_connection()
        self.assertEqual(connection.connection.__class__.__module__.split('.')[0], 'psycopg')
        with connection.cursor() as cursor:
            cursor.execute('SHOW server_encoding')
            self.assertEqual(cursor.fetchone()[0], 'UTF8')
            constraints = connection.introspection.get_constraints(cursor, ProductCandidate._meta.db_table)
        self.assertTrue(constraints['unique_product_source_revision']['unique'])
        self.assertTrue(any(item['index'] and item['columns'] == ['irc_normalized'] for item in constraints.values()))
        self.assertTrue(any(item['foreign_key'] and item['columns'] == ['staged_by_id'] for item in constraints.values()))
        user = get_user_model().objects.create_user('pg-fixture', password='synthetic-test-password')
        product = ProductPresentation.objects.create(name_fa='نام ساختگی فارسی', name_en='Synthetic English',
            manufacturer='شرکت فرضی', strength='۵', dosage_form='قرص', package_description='۱۰ عدد',
            source_name='آزمایشی', source_url='https://example.org')
        candidate = ProductCandidate.objects.create(source_name='آزمایشی', source_url='https://example.org',
            source_record_id='001', source_fields={'name': 'فارسی and English'}, irc_normalized='',
            payload_sha256='a' * 64, staged_by=user)
        self.assertEqual(ProductPresentation.objects.get(pk=product.pk).name_fa, 'نام ساختگی فارسی')
        self.assertEqual(ProductPresentation.objects.get(pk=product.pk).name_en, 'Synthetic English')
        self.assertEqual(ProductCandidate.objects.select_related('staged_by').get(pk=candidate.pk).staged_by_id, user.pk)
        self.assertEqual(ProductCandidate.objects.get(pk=candidate.pk).source_fields['name'], 'فارسی and English')
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductCandidate.objects.create(source_name='other', source_url=candidate.source_url,
                source_record_id='001', source_fields={}, irc_normalized='', payload_sha256='a' * 64, staged_by=user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductCandidate.objects.create(source_name='x', source_url='https://example.org',
                source_record_id='002', source_fields={}, irc_normalized='', payload_sha256='b' * 64, staged_by_id=99999999)
            # PostgreSQL foreign keys are deferred by Django; explicitly check now.
            with connection.cursor() as cursor:
                cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')

    def test_postgresql_rejects_nul_and_unpaired_json_surrogate(self):
        user = get_user_model().objects.create_user('encoding-fixture')
        candidate = ProductCandidate.objects.create(source_name='synthetic', source_url='https://example.org',
            source_record_id='test', source_fields={}, payload_sha256='c' * 64, staged_by=user)
        with self.assertRaises(DataError), transaction.atomic():
            ProductCandidate.objects.filter(pk=candidate.pk).update(source_name='invalid\x00')
        with self.assertRaises(DataError), transaction.atomic():
            ProductCandidate.objects.filter(pk=candidate.pk).update(source_fields={'invalid': '\ud800'})
        self.assertEqual(ProductCandidate.objects.get(pk=candidate.pk).source_fields, {})


class PostgreSQLConcurrentReviewTests(TransactionTestCase):
    def test_two_reviews_from_same_version_produce_one_event(self):
        User = get_user_model()
        author = User.objects.create_user('concurrency-author', is_staff=True)
        author.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical',
                                    codename__in=['view_clinicaldraft', 'add_clinicaldraft']))
        reviewers = [User.objects.create_user(f'concurrency-reviewer-{i}', is_staff=True) for i in range(2)]
        perms = list(Permission.objects.filter(content_type__app_label='clinical',
                                               codename__in=['view_clinicaldraft', 'review_clinicaldraft']))
        for reviewer in reviewers: reviewer.user_permissions.add(*perms)
        draft = create_draft(actor=author, data={'subject': 'فرضی', 'audience': 'patient', 'title': 'نمونه',
            'statement': 'متن ساختگی برای آزمایش.', 'reference_title': 'ارجاع فرضی',
            'reference_url': 'https://example.org', 'reference_location': 'بخش فرضی',
            'reference_author': '', 'reference_version': '', 'reference_published_on': None, 'reference_accessed_on': None})
        barrier = Barrier(2, timeout=10)
        def worker(reviewer_id):
            close_old_connections()
            try:
                reviewer = User.objects.get(pk=reviewer_id)
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                barrier.wait()
                try:
                    review_draft(actor=reviewer, draft_id=draft.pk, decision='defer', reason='توضیح ساختگی برای بررسی',
                                 expected_review=0, expected_hash=draft.payload_sha256)
                    return 'created'
                except DraftConflict:
                    return 'conflict'
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, [u.pk for u in reviewers]))
        self.assertCountEqual(results, ['created', 'conflict'])
        self.assertEqual(ClinicalDraftReview.objects.filter(draft_id=draft.pk).count(), 1)
