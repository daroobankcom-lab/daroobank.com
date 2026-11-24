"""Real collision canaries on an authorized disposable PostgreSQL cluster only."""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch
from uuid import uuid4

from django.core.exceptions import ImproperlyConfigured
from django.db import DatabaseError, connection
from django.db.backends.postgresql.creation import DatabaseCreation as PostgreSQLDatabaseCreation
from django.test import SimpleTestCase, TransactionTestCase

from .isolated_postgresql.creation import DatabaseCreation

ROOT = Path(__file__).resolve().parent.parent


class IsolatedCreationGuardTests(SimpleTestCase):
    def test_create_attempt_is_single_and_unexpected_error_is_not_retried(self):
        db = Mock()
        db.ops.quote_name.return_value = 'quoted-name'
        creation = DatabaseCreation(db)
        name = 'test_daroobank_synthetic_' + 'a' * 32
        cursor = MagicMock()
        context = MagicMock()
        context.__enter__.return_value = cursor
        with patch.object(creation, '_get_test_db_name', return_value=name), \
             patch.object(creation, 'sql_table_creation_suffix', return_value=''), \
             patch.object(creation, '_nodb_cursor', return_value=context), \
             patch.object(creation, '_execute_create_test_db', side_effect=DatabaseError('synthetic failure')) as create:
            with self.assertRaisesMessage(DatabaseError, 'synthetic failure'):
                creation._create_test_db(verbosity=0, autoclobber=True)
        create.assert_called_once_with(cursor, {'dbname': 'quoted-name', 'suffix': ''}, keepdb=False)
        cursor.execute.assert_not_called()  # No DROP or retry after a failed attempt.
        with patch.object(PostgreSQLDatabaseCreation, '_destroy_test_db') as drop:
            with self.assertRaises(ImproperlyConfigured):
                creation._destroy_test_db(name, verbosity=0)
            drop.assert_not_called()  # Ambiguous CREATE did not yield a record.

    def test_only_recorded_name_is_destroyed_once_even_on_drop_error(self):
        name = 'test_daroobank_synthetic_' + 'a' * 32
        other = 'test_daroobank_synthetic_' + 'b' * 32
        for drop_error in (None, DatabaseError('ambiguous synthetic drop failure')):
            with self.subTest(drop_error=drop_error):
                db = Mock()
                db.ops.quote_name.return_value = 'quoted-name'
                creation = DatabaseCreation(db)
                context = MagicMock()
                with patch.object(creation, '_get_test_db_name', return_value=name), \
                     patch.object(creation, 'sql_table_creation_suffix', return_value=''), \
                     patch.object(creation, '_nodb_cursor', return_value=context), \
                     patch.object(creation, '_execute_create_test_db'):
                    self.assertEqual(creation._create_test_db(verbosity=0, autoclobber=True), name)
                    with self.assertRaises(ImproperlyConfigured):
                        creation._create_test_db(verbosity=0, autoclobber=True)
                with patch.object(PostgreSQLDatabaseCreation, '_destroy_test_db', side_effect=drop_error) as drop:
                    for invalid in (other, 'postgres', None):
                        with self.assertRaises(ImproperlyConfigured):
                            creation._destroy_test_db(invalid, verbosity=0)
                    drop.assert_not_called()
                    if drop_error:
                        with self.assertRaisesMessage(DatabaseError, 'ambiguous synthetic drop failure'):
                            creation._destroy_test_db(name, verbosity=0)
                    else:
                        creation._destroy_test_db(name, verbosity=0)
                    drop.assert_called_once_with(name, 0)
                    with self.assertRaises(ImproperlyConfigured):
                        creation._destroy_test_db(name, verbosity=0)
                    drop.assert_called_once()

    def test_direct_reuse_clone_and_unscoped_names_fail_before_database_access(self):
        db = Mock()
        creation = DatabaseCreation(db)
        with patch.object(creation, '_nodb_cursor') as cursor:
            with self.assertRaises(ImproperlyConfigured):
                creation._create_test_db(verbosity=0, autoclobber=True, keepdb=True)
            with self.assertRaises(ImproperlyConfigured):
                creation._clone_test_db('2', verbosity=0)
            for name in ('postgres', 'test_daroobank_synthetic_', 'test_daroobank_browser_' + 'z' * 32,
                         'test_daroobank_restore_' + 'a' * 32 + 'extra'):
                with self.subTest(name=name), patch.object(creation, '_get_test_db_name', return_value=name):
                    with self.assertRaises(ImproperlyConfigured):
                        creation._create_test_db(verbosity=0, autoclobber=True)
            cursor.assert_not_called()


class IsolatedDatabaseCollisionTests(TransactionTestCase):
    def test_teardown_rejects_unrecorded_test_names(self):
        # Never run the destructive canary with Django's ordinary backend.
        self.assertIsInstance(connection.creation, DatabaseCreation)
        name = 'test_daroobank_synthetic_' + uuid4().hex
        quoted = connection.ops.quote_name(name)
        created = False
        probe = None
        try:
            with connection.creation._nodb_cursor() as cursor:
                cursor.execute(f'CREATE DATABASE {quoted}')
                created = True
                cursor.execute('SELECT oid FROM pg_catalog.pg_database WHERE datname = %s', [name])
                original_oid = cursor.fetchone()[0]
            probe = connection.copy(alias='synthetic_teardown_probe')
            probe.settings_dict['NAME'] = name
            with probe.cursor() as cursor:
                cursor.execute('CREATE TABLE teardown_canary (value integer NOT NULL)')
                cursor.execute('INSERT INTO teardown_canary VALUES (789)')
            probe.close()
            # A name in the valid pattern is not enough to authorize deletion.
            for label, creation in (('current', connection.creation), ('fresh', DatabaseCreation(connection))):
                with self.subTest(creation=label):
                    with self.assertRaises(ImproperlyConfigured):
                        creation._destroy_test_db(name, verbosity=0)
                    with connection.creation._nodb_cursor() as cursor:
                        cursor.execute('SELECT oid FROM pg_catalog.pg_database WHERE datname = %s', [name])
                        self.assertEqual(cursor.fetchone(), (original_oid,))
                    with probe.cursor() as cursor:
                        cursor.execute('SELECT value FROM teardown_canary')
                        self.assertEqual(cursor.fetchone(), (789,))
                    probe.close()
            # Django's public teardown wrapper closes the connection before
            # calling the same guard; a fresh wrapper has no creation record.
            with self.assertRaises(ImproperlyConfigured):
                probe.creation.destroy_test_db(verbosity=0)
            with connection.creation._nodb_cursor() as cursor:
                cursor.execute('SELECT oid FROM pg_catalog.pg_database WHERE datname = %s', [name])
                self.assertEqual(cursor.fetchone(), (original_oid,))
            with probe.cursor() as cursor:
                cursor.execute('SELECT value FROM teardown_canary')
                self.assertEqual(cursor.fetchone(), (789,))
            probe.close()
        finally:
            if probe is not None:
                probe.close()
            if created:
                with connection.creation._nodb_cursor() as cursor:
                    cursor.execute(f'DROP DATABASE IF EXISTS {quoted}')

    def test_collision_never_drops_or_reuses_existing_database(self):
        for domain in ('synthetic', 'restore', 'browser'):
            with self.subTest(domain=domain):
                self.assert_collision_preserved(domain)

    def assert_collision_preserved(self, domain):
        suffix = uuid4().hex
        name = f'test_daroobank_{domain}_{suffix}'
        quoted = connection.ops.quote_name(name)
        created = False
        probe = None
        try:
            with connection.creation._nodb_cursor() as cursor:
                cursor.execute(f'CREATE DATABASE {quoted}')
                created = True
                cursor.execute('SELECT oid FROM pg_catalog.pg_database WHERE datname = %s', [name])
                original_oid = cursor.fetchone()[0]
            probe = connection.copy(alias='synthetic_collision_probe')
            probe.settings_dict['NAME'] = name
            with probe.cursor() as cursor:
                cursor.execute('CREATE TABLE collision_canary (value integer NOT NULL)')
                cursor.execute('INSERT INTO collision_canary VALUES (456)')
            probe.close()
            # Force this synthetic test-settings name to collide. Django's
            # default --noinput behavior can delete the existing database.
            script = (
                'import uuid; '
                f'fixed=uuid.UUID(hex="{suffix}"); '
                'uuid.uuid4=lambda: fixed; '
                'from django.core.management import execute_from_command_line; '
                "execute_from_command_line(['manage.py', 'test', "
                "'daroobank.test_postgresql.PostgreSQLIntegrationTests.test_database_driver_encoding_relationships_and_indexes', "
                f"'--settings=daroobank.{domain}_test_settings', "
                "*(__import__('sys').argv[1:]), '--verbosity=0'])"
            )
            for flags in (['--noinput'], []):
                result = subprocess.run([sys.executable, '-c', script, *flags], cwd=ROOT, env=os.environ.copy(),
                                        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
                self.assertNotEqual(result.returncode, 0, 'Collision was silently accepted')
                self.assertIn('Isolated test database already exists; it was not reused or dropped.', result.stderr)
                with connection.creation._nodb_cursor() as cursor:
                    cursor.execute('SELECT oid FROM pg_catalog.pg_database WHERE datname = %s', [name])
                    self.assertEqual(cursor.fetchone(), (original_oid,))
                with probe.cursor() as cursor:
                    cursor.execute('SELECT value FROM collision_canary')
                    self.assertEqual(cursor.fetchone(), (456,))
                probe.close()
        finally:
            if probe is not None:
                probe.close()
            # Only the exact database successfully created by this test is ours.
            if created:
                with connection.creation._nodb_cursor() as cursor:
                    cursor.execute(f'DROP DATABASE IF EXISTS {quoted}')
