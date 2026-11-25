# ADR 0080: PostgreSQL model-index presence clues

Status: development-only implementation, 24 November 2026; extends [ADR 0070](0070-postgresql-catalog-clues.md). [ADR 0081](0081-postgresql-index-directions.md) adds named-index sort direction checks, superseding that limitation below.

## Decision

The read-only catalog inspection also derives expected field indexes and simple named `Meta.indexes` from current managed models. A field marked `db_index` is considered covered when any valid, ready, live, non-partial, non-expression B-tree index has that field as its leading key; a longer index can satisfy this check. A supported plain named model index must exist under its expected name with the same ordered key columns and the same selected index properties. Missing findings cause `attention`. Unsupported named index declarations (including expressions, conditions, included fields, custom operator classes or index subclasses) are counted and cause `attention`, rather than being silently treated as checked. All results remain aggregate-only and the catalog read remains one statement.

Matching index columns is not a query-plan or performance guarantee. These checks do not compare sort direction, null ordering, operator class, collation, extra included columns, full definitions or migration history. Thus an identically named index with the wrong sort direction can still pass; a logically useful hash, partial or expression index can be conservatively flagged as missing. Automatic `varchar_pattern_ops` variants are not separately expected. The result does not check arbitrary unmodeled indexes, all database work or production suitability; investigate, do not automatically repair.

## Evidence

In a disposable PostgreSQL test database, rolled-back DDL removes both indexes for a synthetic candidate field, substitutes partial or hash indexes, verifies a longer B-tree prefix is accepted, and changes a named index's name or key order. A separate test demonstrates that changing the named index's sort direction is not detected; unsupported metadata produces `attention`. Only synthetic development data is appropriate.
