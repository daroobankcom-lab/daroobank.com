"""Development startup retry window; not a hard timeout for connection or query."""
import os
import sys
import time

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'daroobank.settings')
import django

django.setup()
from django.db import OperationalError, connections


def wait_for_database(timeout=60, interval=2):
    deadline = time.monotonic() + timeout
    first_attempt = True
    while first_attempt or time.monotonic() < deadline:
        first_attempt = False
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
    return False


if __name__ == '__main__':
    if not wait_for_database():
        print('PostgreSQL did not become ready during the retry window.', file=sys.stderr)
        sys.exit(1)
    print('PostgreSQL is ready.')
