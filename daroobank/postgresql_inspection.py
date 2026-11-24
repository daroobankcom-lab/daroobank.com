"""Read-only, deliberately limited PostgreSQL catalog clues for synthetic development."""
import json
import re

from django.apps import apps
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.db.models import CheckConstraint, Index, UniqueConstraint


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


def _supported_unique_constraint(constraint):
    return (type(constraint) is UniqueConstraint and bool(constraint.fields) and not constraint.expressions
            and constraint.condition is None and not constraint.include and not constraint.opclasses
            and constraint.nulls_distinct is None and constraint.deferrable is None)


def expected_unique_keys():
    """Selected simple managed-model unique keys; unsupported variants are counted separately."""
    result = set()
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if not meta.managed or meta.proxy or meta.swapped:
            continue
        for field in meta.local_fields:
            if field.unique and field.column:
                result.add((meta.db_table, (field.column,), bool(field.primary_key)))
        for group in meta.unique_together:
            result.add((meta.db_table, tuple(meta.get_field(name).column for name in group), False))
        for constraint in meta.constraints:
            if _supported_unique_constraint(constraint):
                result.add((meta.db_table, tuple(meta.get_field(name).column for name in constraint.fields), False))
    recorder = MigrationRecorder.Migration._meta
    if recorder.pk.column:
        result.add((recorder.db_table, (recorder.pk.column,), True))
    return sorted(result)


def unsupported_unique_constraints():
    """Named model unique declarations excluded from the selected key comparison."""
    result = set()
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if not meta.managed or meta.proxy or meta.swapped:
            continue
        for constraint in meta.constraints:
            if isinstance(constraint, UniqueConstraint) and not _supported_unique_constraint(constraint):
                result.add((meta.db_table, constraint.name))
    return sorted(result)


def expected_check_constraints():
    """Explicitly named CheckConstraints from managed model metadata only."""
    result = set()
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if not meta.managed or meta.proxy or meta.swapped:
            continue
        for constraint in meta.constraints:
            if isinstance(constraint, CheckConstraint):
                result.add((meta.db_table, constraint.name))
    return sorted(result)


def _catalog_type(db_type):
    """Map only the explicitly supported Django/PostgreSQL type spellings."""
    if not isinstance(db_type, str):
        return None
    if db_type in {'bigint', 'integer', 'smallint', 'boolean', 'text', 'date', 'jsonb', 'timestamp with time zone'}:
        return db_type
    if db_type == 'varchar':
        return 'character varying'
    match = re.fullmatch(r'varchar\(([1-9][0-9]*)\)', db_type)
    if match:
        return f'character varying({match.group(1)})'
    match = re.fullmatch(r'numeric\(([1-9][0-9]*),\s*([0-9]+)\)', db_type)
    if match:
        return f'numeric({match.group(1)},{match.group(2)})'
    return None


def expected_columns():
    """Concrete managed fields with nullability and supported PostgreSQL types."""
    result = set()
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if not meta.managed or meta.proxy or meta.swapped:
            continue
        for field in meta.local_fields:
            if field.column:
                # Django's auto-created M2M primary-key metadata can differ from
                # the historical migration's physical key type; do not guess.
                skip_type = bool(meta.auto_created and field.primary_key)
                result.add((meta.db_table, field.column, not field.null,
                            None if skip_type else _catalog_type(field.db_type(connection)), skip_type))
    # MigrationRecorder isn't in the installed app registry. Its key type can
    # vary with the setting in effect when the table was first created.
    meta = MigrationRecorder.Migration._meta
    for field in meta.local_fields:
        if field.column:
            skip_type = bool(field.primary_key)
            result.add((meta.db_table, field.column, not field.null,
                        None if skip_type else _catalog_type(field.db_type(connection)), skip_type))
    return sorted(result)


def expected_field_indexes():
    """Local fields whose current model metadata explicitly requests a DB index."""
    result = set()
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if not meta.managed or meta.proxy or meta.swapped:
            continue
        for field in meta.local_fields:
            if field.column and field.db_index:
                result.add((meta.db_table, field.column))
    return sorted(result)


def expected_named_indexes():
    """Named simple model indexes; unsupported declarations remain explicit."""
    result = set()
    for model in apps.get_models(include_auto_created=True):
        meta = model._meta
        if not meta.managed or meta.proxy or meta.swapped:
            continue
        for index in meta.indexes:
            supported = (type(index) is Index and bool(index.fields) and not index.expressions
                         and index.condition is None and not index.include and not index.opclasses)
            columns = tuple(meta.get_field(name.lstrip('-')).column for name in index.fields) if supported else ()
            descending = tuple(name.startswith('-') for name in index.fields) if supported else ()
            result.add((meta.db_table, index.name, columns, descending, bool(supported)))
    return sorted(result)


def inspect_schema(table_names, foreign_keys=(), unique_keys=(), check_constraints=(), columns=(), field_indexes=(),
                   named_indexes=(), unsupported_uniques=()):
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
            ), matching_fk AS (
                SELECT DISTINCT c.oid, c.condeferrable, c.condeferred, c.confupdtype, c.confdeltype
                FROM expected_fk f JOIN pg_catalog.pg_constraint c
                    ON c.contype = 'f' AND c.conrelid = f.src_oid AND c.confrelid = f.dst_oid
                JOIN pg_catalog.pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
                JOIN pg_catalog.pg_attribute b ON b.attrelid = c.confrelid AND b.attnum = c.confkey[1]
                WHERE pg_catalog.cardinality(c.conkey) = 1 AND pg_catalog.cardinality(c.confkey) = 1
                  AND a.attname = f.col AND b.attname = f.dst_col
            ), expected_unique AS (
                SELECT pg_catalog.to_regclass(pg_catalog.format('%%I', name)) AS table_oid, columns, is_primary
                FROM pg_catalog.jsonb_to_recordset(%s::jsonb) AS u(name text, columns jsonb, is_primary boolean)
            ), expected_checks AS (
                SELECT pg_catalog.to_regclass(pg_catalog.format('%%I', table_name)) AS table_oid, constraint_name
                FROM pg_catalog.jsonb_to_recordset(%s::jsonb) AS c(table_name text, constraint_name text)
            ), expected_columns AS (
                SELECT pg_catalog.to_regclass(pg_catalog.format('%%I', table_name)) AS table_oid, table_name, column_name, not_null, expected_type, skip_type
                FROM pg_catalog.jsonb_to_recordset(%s::jsonb) AS c(table_name text, column_name text, not_null boolean, expected_type text, skip_type boolean)
            ), expected_indexes AS (
                SELECT pg_catalog.to_regclass(pg_catalog.format('%%I', table_name)) AS table_oid, column_name
                FROM pg_catalog.jsonb_to_recordset(%s::jsonb) AS i(table_name text, column_name text)
            ), expected_named AS (
                SELECT pg_catalog.to_regclass(pg_catalog.format('%%I', table_name)) AS table_oid, index_name, columns, descending, supported
                FROM pg_catalog.jsonb_to_recordset(%s::jsonb) AS i(table_name text, index_name text, columns jsonb, descending jsonb, supported boolean)
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
                      AND a.attname = f.col AND b.attname = f.dst_col)),
                (SELECT COUNT(*) FROM matching_fk WHERE NOT condeferrable OR NOT condeferred),
                (SELECT COUNT(*) FROM matching_fk WHERE confupdtype <> 'a' OR confdeltype <> 'a'),
                (SELECT COUNT(*) FROM expected_unique),
                (SELECT COUNT(*) FROM expected_unique u WHERE NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_index i
                    JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
                    JOIN pg_catalog.pg_am am ON am.oid = idx.relam
                    WHERE i.indrelid = u.table_oid AND i.indisunique AND i.indisvalid AND i.indisready AND i.indislive
                      AND i.indimmediate AND am.amname = 'btree'
                      -- The catalog field was introduced in PostgreSQL 15; absent means the older default.
                      AND NOT COALESCE((pg_catalog.to_jsonb(i)->>'indnullsnotdistinct')::boolean, false)
                      AND (NOT u.is_primary OR i.indisprimary) AND i.indpred IS NULL AND i.indexprs IS NULL
                      AND i.indnkeyatts = pg_catalog.jsonb_array_length(u.columns)
                      AND (SELECT pg_catalog.count(*) = i.indnkeyatts AND pg_catalog.bool_and(opc.opcdefault)
                           FROM pg_catalog.unnest(i.indclass::oid[]) WITH ORDINALITY AS c(opclass_oid, ordinal)
                           JOIN pg_catalog.pg_opclass opc ON opc.oid = c.opclass_oid
                           WHERE c.ordinal <= i.indnkeyatts)
                      AND (SELECT pg_catalog.count(*) = i.indnkeyatts AND pg_catalog.bool_and(i.indcollation[(k.ordinal - 1)::integer] = a.attcollation)
                           FROM pg_catalog.unnest(i.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ordinal)
                           JOIN pg_catalog.pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                           WHERE k.ordinal <= i.indnkeyatts)
                      AND (SELECT pg_catalog.array_agg(a.attname::text ORDER BY k.ordinal)
                           FROM pg_catalog.unnest(i.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ordinal)
                           JOIN pg_catalog.pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                           WHERE k.ordinal <= i.indnkeyatts)
                          = ARRAY(SELECT pg_catalog.jsonb_array_elements_text(u.columns)))),
                (SELECT COUNT(*) FROM expected_checks),
                (SELECT COUNT(*) FROM expected_checks e WHERE NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_constraint c
                    WHERE c.conrelid = e.table_oid AND c.conname = e.constraint_name AND c.contype = 'c')),
                (SELECT COUNT(*) FROM expected_columns),
                (SELECT COUNT(*) FROM expected_columns e WHERE NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_attribute a
                    JOIN tables t ON t.oid = a.attrelid
                    WHERE a.attrelid = e.table_oid AND a.attname = e.column_name AND a.attnum > 0 AND NOT a.attisdropped)),
                (SELECT COUNT(*) FROM expected_columns e JOIN pg_catalog.pg_attribute a
                    ON a.attrelid = e.table_oid AND a.attname = e.column_name AND a.attnum > 0 AND NOT a.attisdropped
                    JOIN tables t ON t.oid = a.attrelid WHERE a.attnotnull <> e.not_null),
                (SELECT COUNT(*) FROM expected_columns WHERE expected_type IS NULL AND NOT skip_type),
                (SELECT COUNT(*) FROM expected_columns WHERE skip_type AND table_name <> 'django_migrations'),
                (SELECT COUNT(*) FROM expected_columns WHERE skip_type AND table_name = 'django_migrations'),
                (SELECT COUNT(*) FROM expected_columns e JOIN pg_catalog.pg_attribute a
                    ON a.attrelid = e.table_oid AND a.attname = e.column_name AND a.attnum > 0 AND NOT a.attisdropped
                    JOIN tables t ON t.oid = a.attrelid WHERE e.expected_type IS NOT NULL
                    AND pg_catalog.format_type(a.atttypid, a.atttypmod) <> e.expected_type),
                (SELECT COUNT(*) FROM expected_indexes),
                (SELECT COUNT(*) FROM expected_indexes e WHERE NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_index i
                    JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
                    JOIN pg_catalog.pg_am am ON am.oid = idx.relam
                    JOIN pg_catalog.pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = i.indkey[0]
                    WHERE i.indrelid = e.table_oid AND a.attname = e.column_name
                      AND i.indisvalid AND i.indisready AND i.indislive AND i.indnkeyatts >= 1
                      AND i.indpred IS NULL AND i.indexprs IS NULL AND am.amname = 'btree')),
                (SELECT COUNT(*) FROM expected_named),
                (SELECT COUNT(*) FROM expected_named WHERE NOT supported),
                (SELECT COUNT(*) FROM expected_named e WHERE e.supported AND NOT EXISTS (
                    SELECT 1 FROM pg_catalog.pg_index i
                    JOIN pg_catalog.pg_class idx ON idx.oid = i.indexrelid
                    JOIN pg_catalog.pg_am am ON am.oid = idx.relam
                    WHERE i.indrelid = e.table_oid AND idx.relname = e.index_name AND am.amname = 'btree'
                      AND i.indisvalid AND i.indisready AND i.indislive AND i.indpred IS NULL AND i.indexprs IS NULL
                      AND i.indnkeyatts = pg_catalog.jsonb_array_length(e.columns)
                      AND i.indnatts = i.indnkeyatts
                      AND (SELECT pg_catalog.count(*) = i.indnkeyatts AND pg_catalog.bool_and(i.indcollation[(k.ordinal - 1)::integer] = a.attcollation)
                           FROM pg_catalog.unnest(i.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ordinal)
                           JOIN pg_catalog.pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                           WHERE k.ordinal <= i.indnkeyatts)
                      AND (SELECT pg_catalog.count(*) = i.indnkeyatts AND pg_catalog.bool_and(opc.opcdefault)
                           FROM pg_catalog.unnest(i.indclass::oid[]) WITH ORDINALITY AS c(opclass_oid, ordinal)
                           JOIN pg_catalog.pg_opclass opc ON opc.oid = c.opclass_oid
                           WHERE c.ordinal <= i.indnkeyatts)
                      AND (SELECT pg_catalog.array_agg(a.attname::text ORDER BY k.ordinal)
                           FROM pg_catalog.unnest(i.indkey::smallint[]) WITH ORDINALITY AS k(attnum, ordinal)
                           JOIN pg_catalog.pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.attnum
                           WHERE k.ordinal <= i.indnkeyatts)
                          = ARRAY(SELECT pg_catalog.jsonb_array_elements_text(e.columns))
                      AND (SELECT pg_catalog.array_agg((o.option & 1) = 1 ORDER BY o.ordinal)
                           FROM pg_catalog.unnest(i.indoption::smallint[]) WITH ORDINALITY AS o(option, ordinal)
                           WHERE o.ordinal <= i.indnkeyatts)
                          = ARRAY(SELECT pg_catalog.jsonb_array_elements_text(e.descending)::boolean)
                      AND (SELECT pg_catalog.array_agg((o.option & 2) = 2 ORDER BY o.ordinal)
                           FROM pg_catalog.unnest(i.indoption::smallint[]) WITH ORDINALITY AS o(option, ordinal)
                           WHERE o.ordinal <= i.indnkeyatts)
                          = ARRAY(SELECT pg_catalog.jsonb_array_elements_text(e.descending)::boolean)))
        ''', [table_names,
              json.dumps([dict(zip(('src', 'col', 'dst', 'dst_col'), item)) for item in foreign_keys]),
              json.dumps([{'name': table, 'columns': columns, 'is_primary': primary}
                          for table, columns, primary in unique_keys]),
              json.dumps([{'table_name': table, 'constraint_name': name} for table, name in check_constraints]),
              json.dumps([{'table_name': table, 'column_name': name, 'not_null': not_null,
                           'expected_type': data_type, 'skip_type': skip_type}
                          for table, name, not_null, data_type, skip_type in columns]),
              json.dumps([{'table_name': table, 'column_name': name} for table, name in field_indexes]),
              json.dumps([{'table_name': table, 'index_name': name, 'columns': keys,
                           'descending': descending, 'supported': supported}
                          for table, name, keys, descending, supported in named_indexes])])
        values = cursor.fetchone()
    keys = ('expected_tables', 'unresolved_tables', 'non_table_relations', 'unvalidated_constraints',
            'invalid_indexes', 'disabled_triggers', 'expected_foreign_keys', 'missing_foreign_keys',
            'nondeferred_foreign_keys', 'nondefault_action_foreign_keys', 'expected_unique_keys', 'missing_unique_keys',
            'expected_check_constraints', 'missing_check_constraints', 'expected_columns', 'missing_columns',
            'column_nullability_mismatches', 'unsupported_column_types', 'skipped_auto_m2m_pk_types',
            'skipped_migration_pk_types', 'column_type_mismatches',
            'expected_field_indexes', 'missing_field_indexes', 'expected_named_indexes', 'unsupported_named_indexes',
            'missing_named_indexes')
    result = dict(zip(keys, values))
    # This is a model-metadata coverage count, not a separate database query.
    result['unsupported_unique_constraints'] = len(unsupported_uniques)
    result['status'] = ('attention' if any(result[key] for key in (
        'unresolved_tables', 'non_table_relations', 'unvalidated_constraints', 'invalid_indexes',
        'disabled_triggers', 'missing_foreign_keys', 'nondeferred_foreign_keys',
        'nondefault_action_foreign_keys', 'missing_unique_keys', 'unsupported_unique_constraints', 'missing_check_constraints', 'missing_columns',
        'column_nullability_mismatches', 'unsupported_column_types', 'column_type_mismatches',
        'missing_field_indexes', 'unsupported_named_indexes', 'missing_named_indexes')) else 'no_selected_issues')
    return result
