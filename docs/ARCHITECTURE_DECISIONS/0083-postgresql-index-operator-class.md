# ADR 0083: selected PostgreSQL index operator-class clues

Status: development-only implementation, 24 November 2026; extends [ADR 0082](0082-postgresql-index-null-order.md). [ADR 0084](0084-postgresql-index-collation-and-include.md) adds limited index-collation and included-column clues, superseding those limitations below.

## Decision

For a supported plain named model B-tree index, require every key's catalog operator class to be marked default (`pg_opclass.opcdefault`). A nondefault operator class makes that named index count as missing and causes `attention`. This is still one read-only catalog statement and aggregate-only output. The field-index coverage check is unchanged, and model declarations with explicit operator classes remain unsupported and counted separately.

A default flag means default for the operator class's input type and access method; it is not an exact comparison against the operator class PostgreSQL would choose for each model field or proof of equivalent behavior. Collation, included columns, full definitions, query plans and performance remain unchecked. There may be useful nondefault alternatives; investigate rather than automatically repair. A clean result is not migration equivalence or production readiness.

## Evidence

With synthetic data in a disposable PostgreSQL database, rolled-back DDL replaces a named index with `varchar_pattern_ops` and the report flags it. The normal migrated index remains accepted. A separate test replaces its first-key collation with a catalog-distinct collation and shows that it still passes, documenting a remaining blind spot. No production migration or repair is implied.
