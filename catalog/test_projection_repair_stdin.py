"""Synthetic projection repair can consume bounded tokens without argv exposure."""
import io
import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import connection
from django.test import TestCase, TransactionTestCase, override_settings

from .models import ProductPresentation
from .projection_repair import MAX_TOKEN_LENGTH, preview_projection

ROOT = Path(__file__).resolve().parent.parent


@override_settings(DEBUG=True, SECRET_KEY='synthetic-test-secret-key')
class ProjectionRepairStdinTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='محصول ساختگی', name_en='Synthetic', manufacturer='سازنده ساختگی',
            strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic')

    def setUp(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(irc='002')
        self.token = preview_projection(presentation_id=self.product.pk)['token']

    def call(self, **kwargs):
        out = io.StringIO()
        call_command('repair_catalog_projection', presentation_id=self.product.pk, stdout=out, **kwargs)
        return json.loads(out.getvalue())

    def test_commit_with_stdin_token_and_optional_single_line_ending(self):
        for ending in ('', '\n', '\r\n'):
            with self.subTest(ending=repr(ending)):
                ProductPresentation.objects.filter(pk=self.product.pk).update(irc='002', irc_normalized='001')
                token = preview_projection(presentation_id=self.product.pk)['token']
                with patch('sys.stdin', io.StringIO(token + ending)):
                    result = self.call(commit=True, confirm_synthetic=True, token_stdin=True)
                self.assertEqual(result['status'], 'repaired')
                self.assertEqual(ProductPresentation.objects.get(pk=self.product.pk).irc_normalized, '002')

    def test_short_reads_do_not_truncate_token_or_hide_a_second_line(self):
        class ShortRead(io.StringIO):
            def read(self, size=-1):
                return super().read(min(size, 7))
        with patch('sys.stdin', ShortRead(self.token + '\nextra')):
            with patch('catalog.management.commands.repair_catalog_projection.apply_projection') as apply:
                with self.assertRaises(CommandError):
                    self.call(commit=True, confirm_synthetic=True, token_stdin=True)
                apply.assert_not_called()
        with patch('sys.stdin', ShortRead(self.token + '\n')):
            self.assertEqual(self.call(commit=True, confirm_synthetic=True, token_stdin=True)['status'], 'repaired')

    def test_stream_that_never_ends_is_bounded_when_data_remains_available(self):
        class EndlessStream:
            def __init__(self):
                self.reads = 0
            def isatty(self):
                return False
            def read(self, size):
                self.reads += 1
                return 'x'
        stream = EndlessStream()
        with patch('sys.stdin', stream):
            with self.assertRaises(CommandError):
                self.call(commit=True, confirm_synthetic=True, token_stdin=True)
        self.assertEqual(stream.reads, MAX_TOKEN_LENGTH + 3)

    def test_bad_modes_are_rejected_before_stdin_read_and_without_writes(self):
        cases = [dict(token_stdin=True), dict(token_stdin=True, commit=True),
                 dict(token_stdin=True, confirm_synthetic=True),
                 dict(token_stdin=True, commit=True, confirm_synthetic=True, token=self.token),
                 dict(token_stdin='true', commit=True, confirm_synthetic=True)]
        before = ProductPresentation.objects.values().get(pk=self.product.pk)
        for options in cases:
            with self.subTest(keys=sorted(options)), patch('sys.stdin') as stream:
                stream.read.side_effect = AssertionError('unexpected stdin read')
                with self.assertRaises(CommandError):
                    self.call(**options)
                stream.read.assert_not_called()
            self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)

    def test_invalid_input_is_bounded_and_not_disclosed(self):
        canary = 'synthetic-private-token-canary'
        for payload in ('', '\n', canary + '\nsecond', canary + '\r', canary + 'x' * 10000):
            with self.subTest(length=len(payload)):
                stream = io.StringIO(payload)
                with patch('sys.stdin', stream):
                    with self.assertRaises(CommandError) as caught:
                        self.call(commit=True, confirm_synthetic=True, token_stdin=True)
                self.assertLessEqual(stream.tell(), MAX_TOKEN_LENGTH + 3)
                self.assertNotIn(canary, ''.join(traceback.format_exception(caught.exception)))

    def test_tty_and_read_failure_are_generic_and_no_echo(self):
        for mode in ('tty', 'failure'):
            with self.subTest(mode=mode), patch('sys.stdin') as stream:
                stream.isatty.return_value = mode == 'tty'
                stream.read.side_effect = OSError('synthetic-private-reader-canary')
                with self.assertRaises(CommandError) as caught:
                    self.call(commit=True, confirm_synthetic=True, token_stdin=True)
                self.assertNotIn('synthetic-private-reader-canary', ''.join(traceback.format_exception(caught.exception)))
                if mode == 'tty':
                    stream.read.assert_not_called()

    @override_settings(DEBUG=False)
    def test_nondebug_rejects_before_read(self):
        with patch('sys.stdin') as stream:
            stream.read.side_effect = AssertionError('unexpected stdin read')
            with self.assertRaises(CommandError):
                self.call(commit=True, confirm_synthetic=True, token_stdin=True)
            stream.read.assert_not_called()

    def test_real_cli_invalid_token_never_in_argv_or_traceback(self):
        canary = 'synthetic-private-stdin-token-canary'
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DJANGO_SETTINGS_MODULE='daroobank.settings', DAROOBANK_DEBUG='1',
                   POSTGRES_DB='synthetic', POSTGRES_USER='synthetic', POSTGRES_HOST='not-connected',
                   POSTGRES_PORT='5432')
        args = [sys.executable, 'manage.py', 'repair_catalog_projection', '--traceback', '--id', '1',
                '--commit', '--confirm-synthetic', '--token-stdin']
        self.assertNotIn(canary, args)
        result = subprocess.run(args, cwd=ROOT, env=env, input=canary + '\n', capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Projection request is unavailable', result.stderr)
        self.assertNotIn(canary, result.stdout + result.stderr)


@override_settings(DEBUG=True, SECRET_KEY='synthetic-test-secret-key')
class ProjectionRepairStdinCliTests(TransactionTestCase):
    def test_real_cli_consumes_valid_token_once_on_isolated_synthetic_database(self):
        config = connection.settings_dict
        self.assertRegex(config['NAME'], r'^test_daroobank_synthetic_[0-9a-f]{32}$')
        self.assertEqual(config['ENGINE'], 'daroobank.isolated_postgresql')
        product = ProductPresentation.objects.create(
            name_fa='محصول ساختگی', name_en='Synthetic', manufacturer='سازنده ساختگی',
            strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic')
        ProductPresentation.objects.filter(pk=product.pk).update(irc='002')
        token = preview_projection(presentation_id=product.pk)['token']
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DJANGO_SETTINGS_MODULE='daroobank.synthetic_test_settings', DAROOBANK_DEBUG='1',
                   DAROOBANK_SECRET_KEY='synthetic-test-secret-key', POSTGRES_DB=str(config['NAME']),
                   POSTGRES_USER=str(config['USER']), POSTGRES_PASSWORD=str(config.get('PASSWORD') or ''),
                   POSTGRES_HOST=str(config['HOST']), POSTGRES_PORT=str(config['PORT']))
        args = [sys.executable, 'manage.py', 'repair_catalog_projection', '--id', str(product.pk),
                '--commit', '--confirm-synthetic', '--token-stdin']
        for expected in (0, 1):
            result = subprocess.run(args, cwd=ROOT, env=env, input=token + '\n', capture_output=True,
                                    text=True, timeout=15)
            self.assertEqual(result.returncode, expected, 'Synthetic CLI returned an unexpected status')
            self.assertNotIn(token, result.stdout + result.stderr)
            if expected == 0:
                self.assertEqual(json.loads(result.stdout)['status'], 'repaired')
                self.assertEqual(ProductPresentation.objects.get(pk=product.pk).irc_normalized, '002')
            else:
                self.assertIn('Projection request is unavailable', result.stderr)
