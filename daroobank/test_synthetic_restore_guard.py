"""Safety guards for the opt-in, synthetic-only restore drill."""
import runpy
import sys
from unittest.mock import Mock, patch

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from . import settings as base_settings
from . import test_synthetic_restore as restore


class RestoreDrillGuardTests(SimpleTestCase):
    def test_restore_settings_reject_reuse_and_parallel(self):
        for args in (['manage.py', 'test', '--keepdb'], ['manage.py', 'test', '--parallel'],
                     ['manage.py', 'test', '--parallel=2']):
            with self.subTest(args=args), patch.object(sys, 'argv', args), self.assertRaises(ImproperlyConfigured):
                runpy.run_module('daroobank.restore_test_settings')

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
