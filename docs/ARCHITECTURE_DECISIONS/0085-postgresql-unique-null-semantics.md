# ADR 0085: selected PostgreSQL unique-key null semantics

Status: development-only implementation, 24 November 2026; extends [ADR 0073](0073-postgresql-unique-key-clues.md).

## Decision

For the simple unique keys already selected by the inspector, require the default PostgreSQL `NULLS DISTINCT` semantics. A `NULLS NOT DISTINCT` replacement does not satisfy the expected key and causes aggregate `attention`. The read-only, single-statement inspection uses the catalog row's optional `indnullsnotdistinct` property; the property is absent on PostgreSQL before version 15, which did not offer that index option. PostgreSQL 16 is the tested project stack; compatibility with other server versions is not established by this change.

The rule is conservative even if all indexed fields are non-null and the behavior would be equivalent. It does not add support for model `UniqueConstraint` declarations with explicit null semantics, partial or expression definitions, or complete unique-constraint equivalence. Index order, operator class, collation, deferrability and other properties can still affect equivalence and are not fully compared. No repair is performed, and clean findings do not certify schema or production readiness.

## Evidence

A synthetic PostgreSQL 16 test replaces a model's unique constraint with a same-column `NULLS NOT DISTINCT` unique index inside a rolled-back transaction; it is now flagged, whereas the ordinary migrated baseline passes. Other matching unique indexes may satisfy the selected presence clue. This is not a production migration or repair procedure.
