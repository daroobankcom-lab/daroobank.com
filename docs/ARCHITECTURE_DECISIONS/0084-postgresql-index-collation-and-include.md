# ADR 0084: selected PostgreSQL index collation and included-column clues

Status: development-only implementation, 24 November 2026; extends [ADR 0083](0083-postgresql-index-operator-class.md).

## Decision

For supported plain named model indexes, the inspector checks that each index key's catalog collation OID matches the actual indexed column's collation OID (zero for non-collatable types), and that no additional columns are included. A mismatch counts as a missing named index and causes `attention`. The operation is still one read-only catalog statement with aggregate-only output. Field-index coverage remains unchanged, and model indexes with explicit included fields remain unsupported and cause attention.

This compares an index to the current column, not the column's collation to model or migration intent, and does not assess collation version changes. It does not compare the exact operator class, storage options, full definitions, plans or performance. An extra included column or a different collation may be useful despite the conservative flag. A clean result is not migration equivalence, a health certificate or production readiness; do not automatically repair.

## Evidence

Rolled-back DDL in a disposable PostgreSQL database replaces a named index with a catalog-distinct `C` collation on a text key, or adds an included column; both are flagged, while the migrated baseline passes. A storage-option change intentionally passes. Tests use synthetic data and do not authorize production migration or repair.
