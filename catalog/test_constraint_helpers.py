"""Transactional, synthetic-test-only schema mutation for bypass-defense tests."""
import re

from django.db import connection


def omit_publication_date_constraint_for_test():
    """Rollback by the surrounding TestCase transaction; never use on real data."""
    config = connection.settings_dict
    if (connection.vendor != 'postgresql' or config.get('ENGINE') != 'daroobank.isolated_postgresql'
            or not re.fullmatch(r'test_daroobank_synthetic_[0-9a-f]{32}', str(config.get('NAME', '')))
            or not connection.in_atomic_block):
        raise RuntimeError('Constraint mutation requires a transactional isolated synthetic test database.')
    with connection.cursor() as cursor:
        cursor.execute('ALTER TABLE catalog_productpresentation DROP CONSTRAINT catalog_published_requires_verified')
