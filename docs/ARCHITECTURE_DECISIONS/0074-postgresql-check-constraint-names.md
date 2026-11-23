# ADR 0074: PostgreSQL named check-constraint clues

Status: development-only implementation, 23 November 2026; extends [ADR 0070](0070-postgresql-catalog-clues.md).

## Decision

For each explicitly named `CheckConstraint` in managed model metadata, the read-only catalog inspection counts missing table/name pairs or a relation's matching name with the wrong PostgreSQL constraint type. It also already counts all observed unvalidated constraints on in-scope tables. Missing named checks report `attention`; outputs remain aggregate-only. Unresolved tables can be counted both as unresolved and as missing checks. Equivalent checks under different names are conservatively flagged.

This does **not** compare SQL expressions: a validated `CHECK (true)` with the expected name passes the name/type test despite enforcing nothing. A synthetic regression intentionally demonstrates that failure to detect semantic drift. It also does not inspect database-generated field checks, model validation, names/definitions of unscoped checks or migration history. The check cannot prove data integrity, source rights, security or production readiness; no automatic fix is attempted. Use only authorized synthetic development databases.

## Evidence and limits

On a disposable PostgreSQL test database, tests remove a named constraint, replace it with an equivalent differently named check, replace it with a wrong constraint type, and replace it with an unvalidated check. They verify missing/validation counts and nonzero command behavior. A separately replaced validated `CHECK (true)` illustrates the semantic blind spot. Database schema changes during operation can produce transient observations; the catalog query sees one statement snapshot, not a full historical audit.
