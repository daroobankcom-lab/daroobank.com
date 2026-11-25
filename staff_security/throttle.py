"""Opt-in development-only, shared PostgreSQL fixed-window login throttle."""
from datetime import timedelta
from ipaddress import IPv6Address, ip_address

from django.db import DatabaseError, connections, transaction
from django.utils.crypto import salted_hmac

from .models import StaffLoginWindow

ATTEMPT_LIMIT = 10
WINDOW = timedelta(seconds=60)


def _client_key(remote_addr):
    # REMOTE_ADDR is supplied by the server, not a forwarded request header.
    # Scoped IPv6 addresses and alternate syntaxes are not accepted.
    if not isinstance(remote_addr, str) or not 1 <= len(remote_addr) <= 45 or '%' in remote_addr:
        return None
    try:
        address = ip_address(remote_addr)
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return salted_hmac('staff_security.login.client.v1', str(address), algorithm='sha256').hexdigest()


def consume_attempt(remote_addr):
    """Consume an attempt before authentication, returning allowed/limited/unavailable.

    A fixed window is shared across workers through a locked row. Do not touch
    an outer transaction or retain a lock until its eventual commit. Timeouts
    bound selected server-side lock/query waits, not a complete request.
    """
    key = _client_key(remote_addr)
    if key is None:
        return 'unavailable'
    connection = connections['default']
    try:
        if connection.vendor != 'postgresql' or connection.in_atomic_block or not connection.get_autocommit():
            return 'unavailable'
        table = connection.ops.quote_name(StaffLoginWindow._meta.db_table)
        with transaction.atomic(using='default'):
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '1s'")
                cursor.execute("SET LOCAL statement_timeout = '2s'")
                # The conflict UPDATE locks the existing/new row before returning
                # the server clock. Concurrent consumers serialize at this point.
                cursor.execute(f'''INSERT INTO {table} (client_key, started_at, attempts)
                    VALUES (%s, clock_timestamp(), 0)
                    ON CONFLICT (client_key) DO UPDATE SET client_key = EXCLUDED.client_key
                    RETURNING started_at, attempts, clock_timestamp()''', [key])
                started_at, attempts, now = cursor.fetchone()
                if now < started_at:
                    return 'unavailable'  # A backwards clock must not reset the limit.
                if now - started_at >= WINDOW:
                    started_at, attempts = now, 1
                else:
                    attempts = min(attempts + 1, ATTEMPT_LIMIT + 1)
                cursor.execute(f'UPDATE {table} SET started_at = %s, attempts = %s WHERE client_key = %s',
                               [started_at, attempts, key])
                return 'allowed' if attempts <= ATTEMPT_LIMIT else 'limited'
    except DatabaseError:
        # No IP, username, query or exception text is emitted to the client.
        return 'unavailable'
