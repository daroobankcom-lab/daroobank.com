"""Safety guards for the opt-in, synthetic-only restore drill."""
import os
import runpy
import subprocess
import sys
import warnings
from pathlib import Path
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from . import settings as base_settings
from . import test_synthetic_restore as restore


def load_test_settings(module):
    # The active isolated settings can already be imported; re-execution here is intentional.
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message=r"'.*test_settings' found in sys.modules", category=RuntimeWarning)
        return runpy.run_module(module)


class RestoreDrillGuardTests(SimpleTestCase):
    def test_isolated_runner_rejects_parsed_reuse_and_parallel_options(self):
        from django.core.management import call_command
        from .isolated_test_runner import IsolatedTestRunner

        IsolatedTestRunner()
        for options in ({'keepdb': True}, {'parallel': 1}, {'parallel': 2}):
            with self.subTest(options=options), self.assertRaises(ImproperlyConfigured):
                IsolatedTestRunner(**options)
            with self.subTest(call_command=options), override_settings(TEST_RUNNER='daroobank.isolated_test_runner.IsolatedTestRunner'):
                with self.assertRaises(ImproperlyConfigured):
                    call_command('test', 'daroobank.test_synthetic_restore_guard', **options)

    def test_settings_use_isolated_runner_and_leave_base_database_unmodified(self):
        original = base_settings.DATABASES['default'].get('TEST')
        for module in ('daroobank.restore_test_settings', 'daroobank.browser_test_settings',
                       'daroobank.synthetic_test_settings'):
            with self.subTest(module=module):
                config = load_test_settings(module)
                self.assertEqual(config['TEST_RUNNER'], 'daroobank.isolated_test_runner.IsolatedTestRunner')
                self.assertEqual(base_settings.DATABASES['default'].get('TEST'), original)

    def test_cli_abbreviations_are_rejected_before_test_database_setup(self):
        root = Path(__file__).resolve().parent.parent
        for module in ('daroobank.restore_test_settings', 'daroobank.browser_test_settings',
                       'daroobank.synthetic_test_settings'):
            for flag in ('--keepdb', '--keep', '--parallel', '--para=2', '--parallel=1'):
                with self.subTest(module=module, flag=flag):
                    result = subprocess.run(
                        [sys.executable, 'manage.py', 'test', '--settings=' + module, flag, '--noinput'],
                        cwd=root, env=os.environ.copy(), capture_output=True, text=True, timeout=20,
                    )
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Isolated exercises require a fresh, non-parallel database.', result.stderr)
                    self.assertNotIn('Creating test database', result.stderr)

    def test_general_synthetic_settings_make_new_scoped_names(self):
        original = base_settings.DATABASES['default'].get('TEST')
        first = load_test_settings('daroobank.synthetic_test_settings')
        second = load_test_settings('daroobank.synthetic_test_settings')
        first_name = first['DATABASES']['default']['TEST']['NAME']
        second_name = second['DATABASES']['default']['TEST']['NAME']
        self.assertRegex(first_name, r'^test_daroobank_synthetic_[0-9a-f]{32}$')
        self.assertNotEqual(first_name, second_name)
        self.assertEqual(base_settings.DATABASES['default'].get('TEST'), original)

    def test_restore_settings_make_new_scoped_names(self):
        original = base_settings.DATABASES['default'].get('TEST')
        with patch.object(sys, 'argv', ['manage.py', 'test']):
            first = runpy.run_module('daroobank.restore_test_settings')
            second = runpy.run_module('daroobank.restore_test_settings')
        self.assertTrue(first['DAROOBANK_RESTORE_ISOLATED'])
        name1 = first['DATABASES']['default']['TEST']['NAME']
        name2 = second['DATABASES']['default']['TEST']['NAME']
        self.assertRegex(name1, r'^test_daroobank_restore_[0-9a-f]{32}$')
        self.assertNotEqual(name1, name2)
        self.assertEqual(base_settings.DATABASES['default'].get('TEST'), original)

    def test_cross_domain_fixture_guards_run_before_writes(self):
        from . import synthetic_restore_fixture as fixture
        actor = Mock()
        for vendor, name, debug in [('sqlite', 'test_daroobank_restore_' + 'a' * 32, True),
                                    ('postgresql', 'valuable_database', True),
                                    ('postgresql', 'test_daroobank_restore_' + 'a' * 32, False)]:
            with self.subTest(vendor=vendor, name=name, debug=debug), override_settings(DEBUG=debug):
                db = Mock(vendor=vendor, settings_dict={'NAME': name})
                with patch.object(fixture, 'connection', db), self.assertRaises(RuntimeError):
                    fixture.build_cross_domain_fixture(actor, actor)
                actor.user_permissions.add.assert_not_called()
                db.cursor.assert_not_called()
        with override_settings(DEBUG=True, DAROOBANK_RESTORE_ISOLATED=False):
            db = Mock(vendor='postgresql', settings_dict={'NAME': 'test_daroobank_restore_' + 'a' * 32})
            with patch.object(fixture, 'connection', db), self.assertRaises(RuntimeError):
                fixture.build_cross_domain_fixture(actor, actor)
            with patch.object(fixture, 'connection', db), self.assertRaises(RuntimeError):
                fixture.verify_post_restore_writes()
            with patch.object(fixture, 'connection', db), self.assertRaises(RuntimeError):
                fixture.verify_source_sequence_probe()
            actor.user_permissions.add.assert_not_called()
            db.cursor.assert_not_called()

    @override_settings(DAROOBANK_RESTORE_ISOLATED=False)
    def test_unmarked_settings_fail_before_database_access(self):
        db = Mock()
        drill = restore.SyntheticRestoreDrill(methodName='test_dump_and_restore_into_new_database')
        with patch('daroobank.test_synthetic_restore.connection', db):
            with self.assertRaises(AssertionError):
                drill.test_dump_and_restore_into_new_database()
        db.cursor.assert_not_called()

    @override_settings(DAROOBANK_RESTORE_ISOLATED=True)
    def test_wrong_source_name_fails_before_database_access(self):
        drill = restore.SyntheticRestoreDrill(methodName='test_dump_and_restore_into_new_database')
        for name in ('postgres', 'test_daroobank_restore_', 'test_daroobank_restore_' + 'z' * 32,
                     'test_daroobank_restore_' + '0' * 32 + 'x'):
            with self.subTest(name=name):
                db = Mock(vendor='postgresql', settings_dict={'NAME': name})
                with patch('daroobank.test_synthetic_restore.connection', db):
                    with self.assertRaises(AssertionError):
                        drill.test_dump_and_restore_into_new_database()
                db.cursor.assert_not_called()
