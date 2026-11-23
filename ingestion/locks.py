"""PostgreSQL transaction-scoped coordination for development CSV staging."""
import hashlib

from django.db import connection


STAGING_DOMAINS = frozenset({'product', 'price'})


def source_lock_key(domain, source_url):
    """Derive a stable signed bigint from the exact source URL and staging domain.

    A collision can serialize unrelated imports; this key is not a signature,
    authorization mechanism, or substitute for unique constraints.
    """
    if domain not in STAGING_DOMAINS or not isinstance(source_url, str) or not source_url:
        raise ValueError('A staging domain and source URL are required.')
    payload = b'daroobank:csv-stage:v1\0' + domain.encode('ascii') + b'\0' + source_url.encode('utf-8')
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], byteorder='big', signed=True)


def lock_source_stage(domain, source_url):
    """Hold a cooperative per-domain/source lock until the outer transaction ends."""
    if not connection.in_atomic_block:
        raise RuntimeError('A transaction is required for a staging lock.')
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [source_lock_key(domain, source_url)])
