# ADR 0088: selected unique-key operator and collation clues

Status: development-only implementation, 24 November 2026; extends [ADR 0087](0087-postgresql-unique-enforcement.md).

## Decision

A PostgreSQL index satisfying a selected simple model unique-key expectation must use B-tree, have operator classes marked default for each key, and have each key's catalog collation OID equal the corresponding current column's collation OID. Nonmatching candidates do not satisfy that expectation and can lead to aggregate `attention`. The check remains a single read-only catalog statement. Explicit custom operator classes and other unsupported model unique declarations are separately counted as described in ADR 0086.

These are conservative clues: a nondefault class or collation with a distinct OID may still be suitable, and operators must investigate rather than automatically repair. The default-class flag is not an exact class comparison, column collation is not compared to model or migration intent, and collation versions and full unique-constraint definitions are not checked. Another matching index can hide a mismatching object. A clean result is not schema equivalence, data integrity or production readiness.

## Evidence

Synthetic PostgreSQL 16 tests replace a composite unique constraint in rolled-back transactions with unique indexes whose first or second key uses `varchar_pattern_ops`, or a catalog-distinct `C` collation. Each is flagged while the migrated baseline and a matching standalone B-tree are accepted. These examples do not cover all operator or collation behavior or authorize production repair.
