# ADR 0087: PostgreSQL selected unique-key enforcement timing

Status: development-only implementation, 24 November 2026; extends [ADR 0073](0073-postgresql-unique-key-clues.md) and [ADR 0086](0086-unsupported-unique-declarations.md).

## Decision

For the selected simple model uniqueness expectations, a matching PostgreSQL unique index must have `pg_index.indimmediate` set. A deferrable unique constraint's supporting index therefore does not satisfy this clue, whether the constraint is initially deferred or initially immediate; a later `SET CONSTRAINTS` could change the latter's timing. Missing matches lead to aggregate `attention` without object names. Explicitly deferrable model `UniqueConstraint` declarations remain unsupported and counted separately. The check remains read-only and issues no repair.

The check still accepts a standalone immediate unique index instead of requiring a named SQL constraint, and it does not fully compare operators, collation or definitions. A matching alternate index can mask a mismatch in another object. This is a conservative model-metadata clue, not complete schema equivalence, proof of application concurrency behavior or production readiness.

## Evidence

Synthetic PostgreSQL 16 tests replace a model-declared composite constraint inside rolled-back transactions with deferrable constraints in both initial modes; both are flagged. A separate test verifies that a standalone immediate unique index is still accepted, recording an intentional limitation. The unmodified migrated baseline passes. No production migration or repair is implied.
