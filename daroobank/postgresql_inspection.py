"""Read-only, deliberately limited PostgreSQL catalog clues for synthetic development."""
import json

from django.apps import apps
from django.db import connection


def expected_tables():
    """Project-managed model tables including implicit many-to-many and migration history."""
    tables = {'django_migrations'}
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if meta.managed and not meta.proxy and not meta.swapped:
            tables.add(meta.db_table)
    return sorted(tables)


def expected_foreign_keys():
    """Single-column declared model FKs between managed tables, including M2M tables."""
    tables = set(expected_tables())
    result = set()
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if not meta.managed or meta.proxy or meta.swapped:
            continue
        for field in meta.local_fields:
            if not (field.many_to_one or field.one_to_one) or not getattr(field, 'db_constraint', False):
                continue
            target = field.target_field
            if target.model._meta.db_table in tables:
                result.add((meta.db_table, field.column, target.model._meta.db_table, target.column))
    return sorted(result)


def inspect_schema(table_names, foreign_keys=()):
    """Return aggregate clues from one PostgreSQL statement, never catalog names or data.

    Resolution follows the active search path. This is not a comparison to the
    full migration schema and cannot establish authenticity or production safety.
    """
    with connection.cursor() as cursor:
        cursor.execute('''
            WITH names AS (
                SELECT DISTINCT name FROM pg_catalog.unnest(%s::text[]) AS input(name)
            ), resolved AS (
                SELECT pg_catalog.to_regclass(pg_catalog.format('%%I', name)) AS oid FROM names
            ), scoped AS (
                SELECT DISTINCT c.oid, c.relkind
                FROM resolved r JOIN pg_catalog.pg_class c ON c.oid = r.oid
            ), tables AS (
                SELECT oid FROM scoped WHERE relkind IN ('r', 'p')
            ), expected_fk AS (
                SELECT pg_catalog.to_regclass(pg_catalog.format('%%I', src)) AS src_oid, col,
                       pg_catalog.to_regclass(pg_catalog.format('%%I', dst)) AS dst_oid, dst_col
                FROM pg_catalog.jsonb_to_recordset(%s::jsonb) AS f(src text, col text, dst text, dst_col text)
            )
            SELECT
                (SELECT COUNT(*) FROM names),
                (SELECT COUNT(*) FROM resolved WHERE oid IS NULL),
                (SELECT COUNT(*) FROM scoped WHERE relkind NOT IN ('r', 'p')),
                (SELECT COUNT(*) FROM pg_catalog.pg_constraint c JOIN tables t ON t.oid = c.conrelid
                    WHERE NOT c.convalidated),
                (SELECT COUNT(*) FROM pg_catalog.pg_index i JOIN tables t ON t.oid = i.indrelid
                    WHERE NOT i.indisvalid OR NOT i.indisready OR NOT i.indislive),
                (SELECT COUNT(*) FROM pg_catalog.pg_trigger g JOIN tables t ON t.oid = g.tgrelid
                    WHERE g.tgenabled = 'D'),
                (SELECT COUNT(*) FROM expected_fk),
                (SELECT COUNT(*) FROM expected_fk f WHERE NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_constraint c
                    JOIN pg_catalog.pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                    JOIN pg_catalog.pg_attribute b ON b.attrelid = c.confrelid AND b.attnum = c.confkey[1]
                    WHERE c.contype = 'f' AND c.conrelid = f.src_oid AND c.confrelid = f.dst_oid
                      AND pg_catalog.cardinality(c.conkey) = 1 AND pg_catalog.cardinality(c.confkey) = 1
                      AND a.attname = f.col AND b.attname = f.dst_col))
        ''', [table_names, json.dumps([dict(zip(('src', 'col', 'dst', 'dst_col'), item)) for item in foreign_keys])])
        values = cursor.fetchone()
    keys = ('expected_tables', 'unresolved_tables', 'non_table_relations', 'unvalidated_constraints',
            'invalid_indexes', 'disabled_triggers', 'expected_foreign_keys', 'missing_foreign_keys')
    result = dict(zip(keys, values))
    result['status'] = ('attention' if any(result[key] for key in (
        'unresolved_tables', 'non_table_relations', 'unvalidated_constraints', 'invalid_indexes',
        'disabled_triggers', 'missing_foreign_keys')) else 'no_selected_issues')
    return result
