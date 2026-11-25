"""Bounded synthetic cleanup for pseudonymous development login windows."""
import io
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from queue import Queue

from django.core.management import call_command, CommandError
from django.db import close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.utils import timezone

from staff_security.models import StaffLoginWindow


@override_settings(DEBUG=True)
class StaffLoginCleanupTests(TransactionTestCase):
    def command(self, *args):
        out = io.StringIO()
        call_command('cleanup_staff_login_windows', *args, stdout=out)
        return json.loads(out.getvalue())

    def test_dry_run_then_bounded_cleanup_only_expired_rows(self):
        old = timezone.now() - timedelta(days=2)
        recent = timezone.now() - timedelta(minutes=1)
        StaffLoginWindow.objects.bulk_create([
            StaffLoginWindow(client_key=f'{i:064x}', started_at=old, attempts=1) for i in range(510)] + [
            StaffLoginWindow(client_key=f'{i:064x}', started_at=recent, attempts=1) for i in range(510, 520)])
        result = self.command()
        self.assertEqual(result, {'mode': 'dry_run', 'eligible': 500, 'more': True, 'limit': 500})
        self.assertEqual(StaffLoginWindow.objects.count(), 520)
        result = self.command('--apply')
        self.assertEqual(result, {'mode': 'delete', 'deleted': 500, 'limit': 500})
        self.assertEqual(StaffLoginWindow.objects.count(), 20)
        self.assertEqual(self.command('--apply')['deleted'], 10)
        self.assertEqual(StaffLoginWindow.objects.count(), 10)
        self.assertEqual(self.command(), {'mode': 'dry_run', 'eligible': 0, 'more': False, 'limit': 500})

    @override_settings(DEBUG=False)
    def test_cleanup_refuses_outside_debug_even_for_dry_run(self):
        with self.assertRaisesMessage(CommandError, 'synthetic development'):
            self.command()
        with self.assertRaisesMessage(CommandError, 'synthetic development'):
            self.command('--apply')

    def test_concurrent_refreshed_window_is_not_deleted(self):
        key = 'a' * 64
        StaffLoginWindow.objects.create(client_key=key, started_at=timezone.now() - timedelta(days=2), attempts=4)
        ready = Queue()
        def worker():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    pid = cursor.fetchone()[0]
                announced = False
                def observe(execute, sql, params, many, context):
                    nonlocal announced
                    if not announced and sql.lstrip().upper().startswith('DELETE') and 'staff_security_staffloginwindow' in sql:
                        announced = True
                        ready.put(pid)
                    return execute(sql, params, many, context)
                with connection.execute_wrapper(observe):
                    return self.command('--apply')
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                StaffLoginWindow.objects.filter(pk=key).update(started_at=timezone.now(), attempts=1)
                future = pool.submit(worker)
                pid = ready.get(timeout=8)
                blocked = False
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    with connection.cursor() as cursor:
                        cursor.execute('SELECT cardinality(pg_blocking_pids(%s)) > 0', [pid])
                        blocked = cursor.fetchone()[0]
                    if blocked or future.done():
                        break
                    time.sleep(.05)
                self.assertTrue(blocked, 'cleanup did not wait for the window row')
            self.assertEqual(future.result(timeout=10)['deleted'], 0)
        self.assertTrue(StaffLoginWindow.objects.filter(pk=key).exists())
