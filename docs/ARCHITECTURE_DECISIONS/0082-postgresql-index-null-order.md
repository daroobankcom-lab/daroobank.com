# ADR 0082: selected PostgreSQL index null-order clues

Status: development-only implementation, 24 November 2026; extends [ADR 0081](0081-postgresql-index-directions.md). [ADR 0083](0083-postgresql-index-operator-class.md) adds default operator-class clues, superseding that limitation below.

## Decision

For supported plain named model indexes, the read-only inspector compares each key's PostgreSQL null-order bit to the default generated for that declared direction: ascending uses `NULLS LAST`, descending uses `NULLS FIRST`. A mismatch contributes to the existing missing-named-index count and causes `attention`. This remains part of the same catalog statement, with aggregate output only and no automatic repair. Field-index coverage remains direction- and null-order-agnostic.

A mismatch is a conservative metadata clue, not necessarily a functional difference for a non-null column or a performance problem. Collation, operator class, included columns and complete definitions remain unchecked; supported index metadata does not mean all possible database index variants are compared. A clean report is neither migration equivalence nor production readiness. Unsupported model index declarations still cause attention.

## Evidence

Rolled-back DDL in a disposable PostgreSQL database tests altered null ordering on both an ascending and a descending key, while the unmodified migrated index supplies a passing baseline. An otherwise matching index using a different operator class intentionally passes, illustrating a remaining blind spot. These tests use synthetic data and are not a production migration or repair procedure.
