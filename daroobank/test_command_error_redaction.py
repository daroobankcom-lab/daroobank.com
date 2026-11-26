"""Selected generic maintenance errors omit chained driver details in tracebacks."""
import io
import os
import subprocess
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

from django.core.management import call_command, CommandError
from django.db import DatabaseError
from django.test import TransactionTestCase, override_settings


@override_settings(DEBUG=True)
class CommandErrorRedactionTests(TransactionTestCase):
    def test_selected_database_errors_have_generic_formatted_tracebacks(self):
        cases = (
            ('cleanup_staff_login_windows', 'staff_security.management.commands.cleanup_staff_login_windows.StaffLoginWindow.objects.filter',
             'Synthetic login-window maintenance is unavailable.'),
            ('inspect_postgresql_schema', 'catalog.management.commands.inspect_postgresql_schema.inspect_schema',
             'PostgreSQL catalog inspection could not be completed.'),
            ('inspect_postgresql_access', 'catalog.management.commands.inspect_postgresql_access.inspect_access',
             'PostgreSQL access inspection could not be completed.'),
        )
        for command, target, expected in cases:
            with self.subTest(command=command):
                canary = 'synthetic-driver-private-canary-' + command
                output, errors = io.StringIO(), io.StringIO()
                with patch(target, side_effect=DatabaseError(canary)):
                    with self.assertRaisesMessage(CommandError, expected) as raised:
                        call_command(command, stdout=output, stderr=errors)
                formatted = ''.join(traceback.format_exception(raised.exception))
                self.assertIn(expected, formatted)
                self.assertNotIn(canary, formatted + output.getvalue() + errors.getvalue())

    def test_schedule_cli_traceback_does_not_echo_invalid_instant(self):
        canary = 'synthetic-instant-private-canary'
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DJANGO_SETTINGS_MODULE='daroobank.settings', DAROOBANK_DEBUG='1',
                   POSTGRES_DB='synthetic', POSTGRES_USER='synthetic', POSTGRES_HOST='not-connected',
                   POSTGRES_PORT='5432')
        result = subprocess.run([sys.executable, 'manage.py', 'inspect_ingestion_window', '--traceback', '--at', canary],
                                cwd=Path(__file__).resolve().parent.parent, env=env,
                                capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Invalid or unresolvable schedule or instant.', result.stderr)
        self.assertNotIn(canary, result.stdout + result.stderr)

    def test_cli_traceback_does_not_print_selected_driver_message(self):
        canary = 'synthetic-cli-driver-private-canary'
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG') if key in os.environ}
        env.update(DJANGO_SETTINGS_MODULE='daroobank.settings', DAROOBANK_DEBUG='1',
                   POSTGRES_DB='synthetic', POSTGRES_USER='synthetic', POSTGRES_HOST='not-connected',
                   POSTGRES_PORT='5432')
        script = ("import django; django.setup(); from unittest.mock import patch; "
                  "from django.db import DatabaseError; from django.core.management import execute_from_command_line; "
                  "p=patch('staff_security.management.commands.cleanup_staff_login_windows.connection.get_autocommit', "
                  "side_effect=DatabaseError('synthetic-cli-driver-private-canary')); p.start(); "
                  "execute_from_command_line(['manage.py', 'cleanup_staff_login_windows', '--traceback'])")
        result = subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parent.parent,
                                env=env, capture_output=True, text=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Synthetic login-window maintenance is unavailable.', result.stderr)
        self.assertNotIn(canary, result.stdout + result.stderr)
