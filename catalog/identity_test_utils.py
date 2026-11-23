"""Helpers for selected synthetic PostgreSQL identity concurrency tests."""
import time
from threading import Event

from django.db import connection


def publish_backend_pid(cursor, pid_queue):
    if pid_queue is not None:
        cursor.execute('SELECT pg_backend_pid()')
        pid_queue.put(cursor.fetchone()[0])


def assert_blocked_by_current_transaction(testcase, worker_pid):
    """Observe PostgreSQL's blocker relation, rather than inferring a wait from scheduling."""
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_backend_pid()')
        blocker_pid = cursor.fetchone()[0]
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            cursor.execute('SELECT %s = ANY(pg_blocking_pids(%s))', [blocker_pid, worker_pid])
            if cursor.fetchone()[0]:
                return
            Event().wait(0.01)
    testcase.fail('Expected PostgreSQL to report the writer blocked by the current transaction')
