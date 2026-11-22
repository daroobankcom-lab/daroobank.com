import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from unittest import mock

from django.test import SimpleTestCase

from tools.sqlite_snapshot import SnapshotError, snapshot, verify

ROOT = Path(__file__).resolve().parent.parent


class SQLiteSnapshotTests(SimpleTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'source.sqlite3'
        self.dest = self.folder / 'snapshot.sqlite3'
        with sqlite3.connect(self.source) as db:
            db.execute('CREATE TABLE parent (id INTEGER PRIMARY KEY, value TEXT)')
            db.execute('CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))')
            db.execute("INSERT INTO parent VALUES (1, 'synthetic')")
            db.execute('INSERT INTO child VALUES (1, 1)')

    def test_copy_is_new_private_verified_and_isolated(self):
        snapshot(self.source, self.dest)
        verify(self.dest)
        if os.name == 'posix':
            self.assertEqual(self.dest.stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(self.source) as db:
            db.execute("UPDATE parent SET value = 'changed' WHERE id=1")
        restored = self.folder / 'restored.sqlite3'
        snapshot(self.dest, restored)
        with sqlite3.connect(restored) as db:
            self.assertEqual(db.execute('SELECT value FROM parent').fetchone(), ('synthetic',))
            self.assertEqual(db.execute('SELECT parent_id FROM child').fetchone(), (1,))

    def test_wal_committed_rows_are_included_uncommitted_rows_excluded(self):
        with sqlite3.connect(self.source) as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute("INSERT INTO parent VALUES (2, 'committed')")
            db.commit()
            db.execute("INSERT INTO parent VALUES (3, 'uncommitted')")
            snapshot(self.source, self.dest)
            with sqlite3.connect(self.dest) as copy:
                self.assertEqual(copy.execute('SELECT id FROM parent ORDER BY id').fetchall(), [(1,), (2,)])
            db.rollback()

    def test_existing_file_and_symlink_never_overwritten(self):
        self.dest.write_bytes(b'keep')
        with self.assertRaises(SnapshotError): snapshot(self.source, self.dest)
        self.assertEqual(self.dest.read_bytes(), b'keep')
        self.dest.unlink()
        self.dest.symlink_to(self.source)
        with self.assertRaises(SnapshotError): snapshot(self.source, self.dest)
        self.assertTrue(self.dest.is_symlink())
        verify(self.source)
        with self.assertRaises(SnapshotError): snapshot(self.source, self.source)
        verify(self.source)

    def test_rejects_missing_invalid_and_bad_destination(self):
        missing = self.folder / 'missing.sqlite3'
        with self.assertRaises(SnapshotError): snapshot(missing, self.dest)
        self.assertFalse(missing.exists())
        self.assertFalse(self.dest.exists())
        missing.write_bytes(b'not sqlite')
        with self.assertRaises(SnapshotError): verify(missing)
        with self.assertRaises(SnapshotError): snapshot(missing, self.dest)
        missing.write_bytes(b'SQLite format 3\x00' + b'broken' * 100)
        with self.assertRaises(SnapshotError): verify(missing)
        with self.assertRaises(SnapshotError): snapshot(missing, self.dest)
        self.assertFalse(self.dest.exists())
        with self.assertRaises(SnapshotError): snapshot(self.source, self.folder / 'not-ignored.db')
        with self.assertRaises(SnapshotError): snapshot(self.source, self.folder / 'absent' / 'copy.sqlite3')
        with self.assertRaises(SnapshotError): snapshot(self.source, self.dest, deadline_seconds=0)
        self.assertFalse(self.dest.exists())

    def test_foreign_key_failure_removes_partial_copy(self):
        with sqlite3.connect(self.source) as db:
            db.execute('INSERT INTO child VALUES (2, 99)')
        with self.assertRaises(SnapshotError): verify(self.source)
        with self.assertRaises(SnapshotError): snapshot(self.source, self.dest)
        self.assertFalse(self.dest.exists())
        self.assertTrue(self.source.exists())

    def test_failed_cleanup_reports_incomplete_destination(self):
        with sqlite3.connect(self.source) as db:
            db.execute('INSERT INTO child VALUES (2, 99)')
        with mock.patch('pathlib.Path.unlink', side_effect=PermissionError('blocked')):
            with self.assertRaisesRegex(SnapshotError, 'incomplete destination'):
                snapshot(self.source, self.dest)
        self.assertTrue(self.dest.exists())

    def test_deadline_cleanup_and_cli(self):
        with mock.patch('tools.sqlite_snapshot.time.monotonic', side_effect=[0, 31]):
            with self.assertRaises(SnapshotError): snapshot(self.source, self.dest)
        self.assertFalse(self.dest.exists())
        command = [sys.executable, str(ROOT / 'tools/sqlite_snapshot.py')]
        result = subprocess.run([*command, 'copy', str(self.source), str(self.dest)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('synthetic', result.stdout)
        result = subprocess.run([*command, 'verify', str(self.dest)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = subprocess.run([*command, 'copy', str(self.source), str(self.dest)], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        verify(self.dest)

    def test_migrated_django_database_restore_drill(self):
        settings = self.folder / 'drill_settings.py'
        settings.write_text("from daroobank.settings import *\nimport os\nDATABASES = {'default': {'ENGINE': 'django.db.backends.sqlite3', 'NAME': os.environ['DRILL_DB_PATH']}}\n")
        env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'drill_settings', 'DAROOBANK_DEBUG': '1',
               'DRILL_DB_PATH': str(self.folder / 'django.sqlite3'),
               'PYTHONPATH': os.pathsep.join([str(self.folder), str(ROOT)])}
        def manage(*args):
            return subprocess.run([sys.executable, str(ROOT / 'manage.py'), *args], env=env,
                                  capture_output=True, text=True, timeout=60)
        result = manage('migrate', '--noinput', '--verbosity', '0')
        self.assertEqual(result.returncode, 0, result.stderr)
        with sqlite3.connect(env['DRILL_DB_PATH']) as db:
            db.execute("INSERT INTO django_session (session_key, session_data, expire_date) VALUES ('synthetic', 'fixture', '2099-01-01')")
        snapshot(env['DRILL_DB_PATH'], self.dest)
        restored = self.folder / 'drill-restored.sqlite3'
        snapshot(self.dest, restored)
        env['DRILL_DB_PATH'] = str(restored)
        result = manage('migrate', '--check')
        self.assertEqual(result.returncode, 0, result.stderr)
        result = manage('check')
        self.assertEqual(result.returncode, 0, result.stderr)
        with sqlite3.connect(restored) as db:
            self.assertEqual(db.execute('SELECT session_data FROM django_session WHERE session_key=?', ('synthetic',)).fetchone(), ('fixture',))
