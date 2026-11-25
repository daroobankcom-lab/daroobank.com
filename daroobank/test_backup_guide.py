"""Offline guards for the documented synthetic backup/restore shell sequence."""
import subprocess
import tempfile
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parent.parent


class SyntheticBackupGuideTests(SimpleTestCase):
    def run_example(self, failed_step='', existing_dump=False, missing_setting='', archive_setting=None, source_setting=None):
        guide = (ROOT / 'docs/DEVELOPMENT_GUIDE.md').read_text()
        script = guide.split('For a **synthetic development**', 1)[1].split('```sh\n', 1)[1].split('\n```', 1)[0]
        with tempfile.TemporaryDirectory(prefix='daroobank-backup-guide-test-') as directory:
            root = Path(directory)
            bin_dir = root / 'bin'
            bin_dir.mkdir()
            python_dir = root / '.venv/bin'
            python_dir.mkdir(parents=True)
            fake = '''#!/bin/sh
name=${0##*/}
case "$name" in
  pg_dump) step=dump ;;
  pg_restore)
    if [ "$1" = "--list" ]; then step=list; else step=restore; fi
    separator=0
    for argument do [ "$argument" != '--' ] || separator=1; done
    [ "$separator" = 1 ] || exit 98 ;;

  createdb) step=createdb ;;
  python) step=$2 ;;
  *) exit 99 ;;
esac
printf '%s\\n' "$step" >> "$TRACE"
[ "$step" != "$FAIL_STEP" ] || exit 7
[ "$step" != dump ] || printf 'synthetic archive'
exit 0
'''
            for executable in (bin_dir / 'pg_dump', bin_dir / 'pg_restore', bin_dir / 'createdb', python_dir / 'python'):
                executable.write_text(fake)
                executable.chmod(0o700)
            dump = root / 'synthetic archive.dump'
            if existing_dump:
                dump.write_text('do not overwrite')
            env = {'PATH': f'{bin_dir}:/usr/bin:/bin', 'HOME': str(root), 'TRACE': str(root / 'trace'),
                   'FAIL_STEP': failed_step, 'SYNTHETIC_DUMP_FILE': str(dump), 'POSTGRES_HOST': 'synthetic.invalid',
                   'POSTGRES_PORT': '5432', 'POSTGRES_USER': 'synthetic', 'POSTGRES_DB': 'synthetic_source'}
            if archive_setting is not None:
                env['SYNTHETIC_DUMP_FILE'] = archive_setting
            if source_setting is not None:
                env['POSTGRES_DB'] = source_setting
            if missing_setting:
                env.pop(missing_setting)
            result = subprocess.run(['/bin/sh', '-c', script], cwd=root, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
            trace = (root / 'trace').read_text().splitlines() if (root / 'trace').exists() else []
            contents = dump.read_text() if dump.exists() else None
            mode = dump.stat().st_mode & 0o777 if dump.exists() else None
            return result.returncode, trace, contents, mode

    def test_successful_sequence(self):
        code, trace, contents, mode = self.run_example()
        self.assertEqual(code, 0)
        self.assertEqual(trace, ['dump', 'list', 'createdb', 'restore', 'migrate', 'check'])
        self.assertEqual(contents, 'synthetic archive')
        self.assertEqual(mode, 0o600)

    def test_failure_stops_every_later_step(self):
        sequence = ['dump', 'list', 'createdb', 'restore', 'migrate', 'check']
        for index, step in enumerate(sequence):
            with self.subTest(step=step):
                code, trace, _, _ = self.run_example(failed_step=step)
                self.assertNotEqual(code, 0)
                self.assertEqual(trace, sequence[:index + 1])

    def test_existing_archive_is_not_overwritten_or_used(self):
        code, trace, contents, _ = self.run_example(existing_dump=True)
        self.assertNotEqual(code, 0)
        self.assertEqual(trace, [])
        self.assertEqual(contents, 'do not overwrite')

    def test_relative_archive_paths_are_rejected_before_dump(self):
        for path in ('synthetic.dump', '../synthetic.dump', '--help', '-'):
            with self.subTest(path=path):
                code, trace, _, _ = self.run_example(archive_setting=path)
                self.assertNotEqual(code, 0)
                self.assertEqual(trace, [])

    def test_connection_string_database_names_are_rejected_before_dump(self):
        for name in ('postgresql://other.example/production', 'host=other dbname=production',
                     'dbname=other', '-danger', 'db name', 'db-name', 'déb', '١٢', 'x' * 64):
            with self.subTest(name=name):
                code, trace, contents, _ = self.run_example(source_setting=name)
                self.assertNotEqual(code, 0)
                self.assertEqual(trace, [])
                self.assertIsNone(contents)

    def test_simple_ascii_database_name_at_length_limit_is_accepted(self):
        code, trace, contents, _ = self.run_example(source_setting='x' * 63)
        self.assertEqual(code, 0)
        self.assertEqual(trace, ['dump', 'list', 'createdb', 'restore', 'migrate', 'check'])
        self.assertEqual(contents, 'synthetic archive')

    def test_missing_required_setting_stops_before_any_command(self):
        for setting in ('SYNTHETIC_DUMP_FILE', 'POSTGRES_DB', 'POSTGRES_HOST', 'POSTGRES_USER'):
            with self.subTest(setting=setting):
                code, trace, contents, _ = self.run_example(missing_setting=setting)
                self.assertNotEqual(code, 0)
                self.assertEqual(trace, [])
                self.assertIsNone(contents)
