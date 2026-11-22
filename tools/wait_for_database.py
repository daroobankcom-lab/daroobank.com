"""Bounded startup wait used by the development container; no schema changes."""
import os
import sys
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'daroobank.settings')
import django

django.setup()
from django.db import OperationalError, connections


def wait_for_database(timeout=60, interval=2):
    deadline = time.monotonic() + timeout
    while True:
        try:
            with connections['default'].cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
            return True
        except OperationalError:
            connections['default'].close()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(interval, remaining))


if __name__ == '__main__':
    if not wait_for_database():
        print('PostgreSQL did not become ready within 60 seconds.', file=sys.stderr)
        sys.exit(1)
    print('PostgreSQL is ready.')
