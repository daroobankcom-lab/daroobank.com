# ADR 0081: selected PostgreSQL index direction clues

Status: development-only implementation, 24 November 2026; extends [ADR 0080](0080-postgresql-index-presence.md).

## Decision

For each supported simple named model index, compare the ascending or descending direction of every key with the corresponding PostgreSQL B-tree `indoption` direction bit, in addition to the existing name, table, key order and selected validity checks. A mismatch contributes to the existing missing-named-index count and causes `attention`; it does not add object names to output. Field-index coverage remains direction-agnostic. The check is a read-only part of the same catalog statement and does not modify indexes.

PostgreSQL can use an index in reverse order, so direction mismatch is only a conservative model-metadata clue, not a diagnosis of a slow query. Null ordering, collation, operator class, included columns and complete definitions remain unchecked. A matching result is neither migration equivalence nor evidence of production readiness. Unsupported declarations remain explicitly counted and require attention; index plans and performance require separate investigation.

## Evidence

Tests in disposable PostgreSQL databases replace a two-key named index within rolled-back transactions and verify that a mismatch on either the first or second key is reported. A replacement with matching directions but different null ordering intentionally passes, recording a remaining blind spot. Existing index, aggregate-output and read-only tests continue to exercise the same command. These tests use synthetic data and are not a production migration or repair procedure.
