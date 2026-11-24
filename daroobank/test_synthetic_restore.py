"""Opt-in, disposable PostgreSQL dump/restore drill with synthetic data only."""
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import skipUnless
from uuid import uuid4

import psycopg
from django.conf import settings
from django.db import connection
from django.test import TransactionTestCase, override_settings

from catalog.identity import digest, package_snapshot, review_package
from catalog.models import IdentityPackageDraft, IdentityPackageReview
from catalog.test_identity import ALL, build, user

ROOT = Path(__file__).resolve().parent.parent


@skipUnless(os.environ.get('DAROOBANK_RESTORE_TESTS') == '1', 'Optional synthetic PostgreSQL restore drill is disabled')
@override_settings(DEBUG=True)
class SyntheticRestoreDrill(TransactionTestCase):
    """Source and target are new, dedicated databases, never an existing database."""

    def test_dump_and_restore_into_new_database(self):
        self.assertTrue(getattr(settings, 'DAROOBANK_RESTORE_ISOLATED', False), 'Use restore_test_settings')
        self.assertEqual(connection.vendor, 'postgresql')
        source = connection.settings_dict['NAME']
        self.assertRegex(source, r'^test_daroobank_restore_[0-9a-f]{32}$')
        self.assertTrue(connection.get_autocommit(), 'Database creation must be outside a transaction')
        for tool in ('pg_dump', 'pg_restore'):
            self.assertIsNotNone(shutil.which(tool), f'{tool} is required on PATH')

        author = user('synthetic-restore-author', *ALL)
        reviewer = user('synthetic-restore-reviewer', *ALL)
        package = build(author)[-1]
        graph_hash = digest(package_snapshot(package))
        event = review_package(actor=reviewer, package_id=package.pk, decision='defer',
            reason='دلیل ساختگی برای تمرین بازگردانی', expected_review=0, expected_graph_hash=graph_hash)
        self.assertEqual(IdentityPackageDraft.objects.count(), 1)
        self.assertEqual(IdentityPackageReview.objects.count(), 1)
        from .synthetic_restore_fixture import build_cross_domain_fixture, verify_cross_domain_fixture
        build_cross_domain_fixture(author, reviewer)
        verify_cross_domain_fixture()

        target = f'test_daroobank_restore_target_{uuid4().hex}'
        self.assertRegex(target, r'^test_daroobank_restore_target_[0-9a-f]{32}$')
        self.assertNotEqual(target, source)
        # Only the generated, successfully created database is ever removed.
        created = False
        config = connection.settings_dict
        child = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'TMPDIR') if key in os.environ}
        child.update(DAROOBANK_DEBUG='1', POSTGRES_DB=source, POSTGRES_HOST=str(config['HOST']),
                     POSTGRES_PORT=str(config['PORT']), POSTGRES_USER=str(config['USER']),
                     PGHOST=str(config['HOST']), PGPORT=str(config['PORT']), PGUSER=str(config['USER']))
        if config.get('PASSWORD'):
            child['POSTGRES_PASSWORD'] = str(config['PASSWORD'])
            child['PGPASSWORD'] = str(config['PASSWORD'])
        sslmode = config.get('OPTIONS', {}).get('sslmode')
        if sslmode:
            child['POSTGRES_SSLMODE'] = str(sslmode)
            child['PGSSLMODE'] = str(sslmode)
        child['PGDATABASE'] = source

        def run(command, env=child):
            # Capture but do not surface command output: DB diagnostics may contain connection details.
            return subprocess.run(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, check=False)

        def target_has_package_table():
            params = {'dbname': target, 'host': config['HOST'], 'port': config['PORT'], 'user': config['USER'],
                      'password': config.get('PASSWORD') or '', 'connect_timeout': 5}
            if sslmode: params['sslmode'] = sslmode
            with psycopg.connect(**params) as db:
                with db.cursor() as cursor:
                    cursor.execute("SELECT to_regclass('public.catalog_identitypackagedraft') IS NOT NULL")
                    return cursor.fetchone()[0]

        try:
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE DATABASE {connection.ops.quote_name(target)}')
            created = True
            with tempfile.TemporaryDirectory(prefix='daroobank-synthetic-restore-') as directory:
                self.assertEqual(stat.S_IMODE(os.stat(directory).st_mode), 0o700)
                archive = Path(directory) / 'synthetic.dump'
                descriptor = os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                os.close(descriptor)
                dumped = run(['pg_dump', '--no-password', '--format=custom', '--no-owner', '--no-acl', '--file', str(archive)])
                self.assertEqual(dumped.returncode, 0, 'Synthetic pg_dump failed')
                self.assertEqual(stat.S_IMODE(archive.stat().st_mode), 0o600)
                self.assertGreater(archive.stat().st_size, 128)
                listed = run(['pg_restore', '--list', str(archive)])
                self.assertEqual(listed.returncode, 0, 'Synthetic archive listing failed')
                self.assertFalse(target_has_package_table())

                # One selected truncated archive must not leave this table partially restored.
                broken = Path(directory) / 'truncated.dump'
                descriptor = os.open(broken, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, 'wb') as stream:
                    contents = archive.read_bytes()
                    stream.write(contents[:len(contents) // 2])
                restored = run(['pg_restore', '--no-password', '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl',
                                '--dbname', target, str(broken)])
                self.assertNotEqual(restored.returncode, 0, 'Truncated archive was unexpectedly accepted')
                self.assertFalse(target_has_package_table(), 'Failed restore left a package table')
                restored = run(['pg_restore', '--no-password', '--exit-on-error', '--single-transaction', '--no-owner', '--no-acl',
                                '--dbname', target, str(archive)])
                self.assertEqual(restored.returncode, 0, 'Synthetic restore failed')
                self.assertTrue(target_has_package_table())

                restored_env = {**child, 'POSTGRES_DB': target, 'PGDATABASE': target,
                                'SYNTHETIC_PACKAGE_ID': str(package.pk), 'SYNTHETIC_REVIEW_ID': str(event.pk),
                                'SYNTHETIC_GRAPH_HASH': graph_hash}
                for args in (['check'], ['migrate', '--check'], ['inspect_postgresql_schema']):
                    check = run([sys.executable, 'manage.py', *args], restored_env)
                    self.assertEqual(check.returncode, 0, f'Restored synthetic database check failed: {args[0]}')
                script = (
                    "import os; from daroobank.synthetic_restore_fixture import "
                    "verify_identity_fixture, verify_cross_domain_fixture, verify_post_restore_writes; "
                    "verify_identity_fixture(int(os.environ['SYNTHETIC_PACKAGE_ID']), "
                    "int(os.environ['SYNTHETIC_REVIEW_ID']), os.environ['SYNTHETIC_GRAPH_HASH']); "
                    "verify_cross_domain_fixture(); verify_post_restore_writes()"
                )
                check = run([sys.executable, 'manage.py', 'shell', '-c', script], restored_env)
                self.assertEqual(check.returncode, 0, 'Restored synthetic ORM graph verification failed')

                # Deliberately rewind one sequence on the throwaway target and
                # prove an ordinary service write detects the resulting collision.
                rewind = (
                    "from django.db import connection; from sources.models import SourceClaim; "
                    "c=connection.cursor(); c.execute(\"SELECT setval(pg_get_serial_sequence('sources_sourceclaim', 'id'), %s, false)\", "
                    "[SourceClaim.objects.order_by('pk').values_list('pk', flat=True).first()])"
                )
                check = run([sys.executable, 'manage.py', 'shell', '-c', rewind], restored_env)
                self.assertEqual(check.returncode, 0, 'Synthetic target sequence setup failed')
                probe = ('from daroobank.synthetic_restore_fixture import verify_source_sequence_probe; '
                         'verify_source_sequence_probe()')
                check = run([sys.executable, 'manage.py', 'shell', '-c', probe], restored_env)
                self.assertNotEqual(check.returncode, 0, 'Rewound synthetic sequence was not detected')
                self.assertIn(b'IntegrityError', check.stderr, 'Sequence probe failed for an unexpected reason')
                reset = (
                    "from django.db import connection; from sources.models import SourceClaim; "
                    "c=connection.cursor(); c.execute(\"SELECT setval(pg_get_serial_sequence('sources_sourceclaim', 'id'), %s, true)\", "
                    "[SourceClaim.objects.order_by('-pk').values_list('pk', flat=True).first()])"
                )
                check = run([sys.executable, 'manage.py', 'shell', '-c', reset], restored_env)
                self.assertEqual(check.returncode, 0, 'Synthetic target sequence reset failed')
                check = run([sys.executable, 'manage.py', 'shell', '-c', probe], restored_env)
                self.assertEqual(check.returncode, 0, 'Synthetic target sequence replay failed')
            self.assertEqual(IdentityPackageReview.objects.count(), 1)
            verify_cross_domain_fixture()
        finally:
            if created:
                with connection.cursor() as cursor:
                    cursor.execute(f'DROP DATABASE {connection.ops.quote_name(target)}')

    def test_cross_domain_verifier_detects_selected_corruption(self):
        from copy import deepcopy
        from ingestion.models import ImportReceiptItem
        from clinical.models import ClinicalDraftReview
        from .synthetic_restore_fixture import build_cross_domain_fixture, verify_cross_domain_fixture

        author = user('synthetic-restore-author', *ALL)
        reviewer = user('synthetic-restore-reviewer', *ALL)
        build_cross_domain_fixture(author, reviewer)
        verify_cross_domain_fixture()
        review = ClinicalDraftReview.objects.get()
        old = deepcopy(review.review_snapshot)
        ClinicalDraftReview.objects.filter(pk=review.pk).update(
            review_snapshot={**old, 'evidence_fingerprint': '0' * 64})
        with self.assertRaises(AssertionError):
            verify_cross_domain_fixture()
        ClinicalDraftReview.objects.filter(pk=review.pk).update(review_snapshot=old)
        item = ImportReceiptItem.objects.first()
        ImportReceiptItem.objects.filter(pk=item.pk).update(payload_sha256='0' * 64)
        with self.assertRaises(AssertionError):
            verify_cross_domain_fixture()

    def test_optimized_verifier_rejects_selected_corruption(self):
        from ingestion.models import ImportReceiptItem
        from .synthetic_restore_fixture import build_cross_domain_fixture

        author = user('synthetic-restore-author', *ALL)
        reviewer = user('synthetic-restore-reviewer', *ALL)
        package = build(author)[-1]
        graph_hash = digest(package_snapshot(package))
        review = review_package(actor=reviewer, package_id=package.pk, decision='defer',
            reason='دلیل ساختگی برای تمرین بازگردانی', expected_review=0, expected_graph_hash=graph_hash)
        build_cross_domain_fixture(author, reviewer)
        config = connection.settings_dict
        self.assertRegex(config['NAME'], r'^test_daroobank_restore_[0-9a-f]{32}$')
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'TMPDIR') if key in os.environ}
        env.update(DAROOBANK_DEBUG='1', POSTGRES_DB=config['NAME'], POSTGRES_HOST=str(config['HOST']),
                   POSTGRES_PORT=str(config['PORT']), POSTGRES_USER=str(config['USER']))
        if config.get('PASSWORD'):
            env['POSTGRES_PASSWORD'] = str(config['PASSWORD'])
        if config.get('OPTIONS', {}).get('sslmode'):
            env['POSTGRES_SSLMODE'] = str(config['OPTIONS']['sslmode'])
        command = [sys.executable, '-O', 'manage.py', 'shell', '-c',
                   'from daroobank.synthetic_restore_fixture import verify_cross_domain_fixture; verify_cross_domain_fixture()']

        def run(args=command, child_env=env):
            return subprocess.run(args, cwd=ROOT, env=child_env, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90, check=False)

        self.assertEqual(run().returncode, 0, 'Optimized verifier rejected the valid synthetic fixture')
        identity_env = {**env, 'SYNTHETIC_PACKAGE_ID': str(package.pk), 'SYNTHETIC_REVIEW_ID': str(review.pk),
                        'SYNTHETIC_GRAPH_HASH': graph_hash}
        identity_command = [sys.executable, '-O', 'manage.py', 'shell', '-c',
            "import os; from daroobank.synthetic_restore_fixture import verify_identity_fixture; "
            "verify_identity_fixture(int(os.environ['SYNTHETIC_PACKAGE_ID']), "
            "int(os.environ['SYNTHETIC_REVIEW_ID']), os.environ['SYNTHETIC_GRAPH_HASH'])"]
        self.assertEqual(run(identity_command, identity_env).returncode, 0, 'Optimized identity verifier rejected valid graph')
        wrong_hash = run(identity_command, {**identity_env, 'SYNTHETIC_GRAPH_HASH': '0' * 64})
        self.assertNotEqual(wrong_hash.returncode, 0, 'Optimized identity verifier accepted a wrong hash')
        self.assertIn(b'AssertionError', wrong_hash.stderr, 'Identity verifier failed for an unexpected reason')
        item = ImportReceiptItem.objects.first()
        ImportReceiptItem.objects.filter(pk=item.pk).update(payload_sha256='0' * 64)
        result = run()
        self.assertNotEqual(result.returncode, 0, 'Optimized verifier accepted a corrupt synthetic receipt')
        self.assertIn(b'AssertionError', result.stderr, 'Verifier failed for an unexpected reason')

    def test_created_target_is_removed_when_dump_fails(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        self.assertTrue(getattr(settings, 'DAROOBANK_RESTORE_ISOLATED', False))
        source = connection.settings_dict['NAME']
        self.assertRegex(source, r'^test_daroobank_restore_[0-9a-f]{32}$')
        token = uuid4().hex
        target = f'test_daroobank_restore_target_{token}'
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', [target])
            self.assertIsNone(cursor.fetchone(), 'Synthetic target name unexpectedly already exists')
        with patch('daroobank.test_synthetic_restore.uuid4', return_value=SimpleNamespace(hex=token)), \
                patch('daroobank.test_synthetic_restore.subprocess.run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(AssertionError, 'Synthetic pg_dump failed'):
                self.test_dump_and_restore_into_new_database()
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', [target])
            self.assertIsNone(cursor.fetchone(), 'Created target was not cleaned up after the failure')

    def test_target_name_collision_is_not_dropped(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from django.db import DatabaseError

        self.assertTrue(getattr(settings, 'DAROOBANK_RESTORE_ISOLATED', False))
        self.assertRegex(connection.settings_dict['NAME'], r'^test_daroobank_restore_[0-9a-f]{32}$')
        target_token = uuid4().hex
        target = f'test_daroobank_restore_target_{target_token}'
        # The pre-existing target is itself a fresh synthetic database created for this test.
        created = False
        try:
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE DATABASE {connection.ops.quote_name(target)}')
            created = True
            with patch('daroobank.test_synthetic_restore.uuid4', return_value=SimpleNamespace(hex=target_token)):
                with self.assertRaises(DatabaseError):
                    self.test_dump_and_restore_into_new_database()
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1 FROM pg_database WHERE datname = %s', [target])
                self.assertIsNotNone(cursor.fetchone(), 'A pre-existing target was removed')
        finally:
            if created:
                with connection.cursor() as cursor:
                    cursor.execute(f'DROP DATABASE {connection.ops.quote_name(target)}')
