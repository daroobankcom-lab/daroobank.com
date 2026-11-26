"""Opt-in fixed-window limit on public reads, shared through PostgreSQL.

`staff_security/throttle.py` limits authentication attempts; this module limits
reads of public pages, which the login window never sees. Both are opt-in and
off by default, because `docs/DEPLOYMENT.md` assigns abuse protection to the
edge: this is a development-slice mechanism, not a production defense, and it
has never been load-tested.

Nothing here stores an address. The key is an HMAC of the normalized
REMOTE_ADDR under a scope of its own, so a read window and a login window
cannot be joined on a shared key, and the row holds no path, route, query,
user agent or account.
"""
from datetime import timedelta
from ipaddress import IPv6Address, ip_address
from math import ceil

from django.db import DatabaseError, connections, transaction
from django.utils.crypto import salted_hmac

from .models import PublicReadWindow

READ_LIMIT = 120
WINDOW = timedelta(seconds=60)
SCOPE = 'staff_security.public_read.v1'


def client_key(remote_addr):
    """A keyed digest of a normalized address, or None when it cannot be keyed.

    REMOTE_ADDR is supplied by the server, not by a forwarded request header.
    Scoped IPv6 addresses and alternate syntaxes are not accepted.
    """
    if not isinstance(remote_addr, str) or not 1 <= len(remote_addr) <= 45 or '%' in remote_addr:
        return None
    try:
        address = ip_address(remote_addr)
    except ValueError:
        return None
    if isinstance(address, IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return salted_hmac(SCOPE, str(address), algorithm='sha256').hexdigest()


def consume_read(remote_addr):
    """Consume one read, returning `(outcome, retry_after_seconds)`.

    The outcome is `allowed`, `limited` or `unavailable`. A caller that cannot be
    keyed and a database that cannot answer inside its timeouts are both
    `unavailable`, and a caller must serve the read anyway: on a public read path
    a limiter that fails closed turns one database problem into an outage, which
    is why this differs from the login window, where an unavailable limiter fails
    closed with 503. `retry_after_seconds` is 0 unless the outcome is `limited`.
    """
    key = client_key(remote_addr)
    if key is None:
        return 'unavailable', 0
    connection = connections['default']
    try:
        if (connection.vendor != 'postgresql' or connection.in_atomic_block
                or not connection.get_autocommit()):
            return 'unavailable', 0
        table = connection.ops.quote_name(PublicReadWindow._meta.db_table)
        with transaction.atomic(using='default'):
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '1s'")
                cursor.execute("SET LOCAL statement_timeout = '2s'")
                # The conflict UPDATE locks the existing or new row before returning
                # the server clock, so concurrent readers serialize here.
                cursor.execute(f'''INSERT INTO {table} (client_key, started_at, reads)
                    VALUES (%s, clock_timestamp(), 0)
                    ON CONFLICT (client_key) DO UPDATE SET client_key = EXCLUDED.client_key
                    RETURNING started_at, reads, clock_timestamp()''', [key])
                started_at, reads, now = cursor.fetchone()
                if now < started_at:
                    return 'unavailable', 0  # A backwards clock must not reset the window.
                if now - started_at >= WINDOW:
                    started_at, reads = now, 1
                else:
                    reads = min(reads + 1, READ_LIMIT + 1)
                cursor.execute(
                    f'UPDATE {table} SET started_at = %s, reads = %s WHERE client_key = %s',
                    [started_at, reads, key])
                if reads <= READ_LIMIT:
                    return 'allowed', 0
                elapsed = now - started_at
                return 'limited', max(1, ceil((WINDOW - elapsed).total_seconds()))
    except DatabaseError:
        # No address, path, query or exception text is emitted to the client.
        return 'unavailable', 0
