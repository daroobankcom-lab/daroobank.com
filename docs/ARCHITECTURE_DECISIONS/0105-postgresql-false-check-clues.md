# ADR 0105: selected constant-false check clues

Status: development-only implementation, 24 November 2026; extends [ADR 0104](0104-postgresql-constant-check-clues.md).

## Decision

For selected explicitly named model check constraints, the single catalog statement now also counts exact PostgreSQL deparsed `false` expressions as `canonical_reject_all_named_checks`. Such a check rejects every attempted insert or update reaching it. A nonzero count yields `attention`, without names or expressions. This is separate from the true/null accept-all count. A deliberately empty domain or intentional check can be flagged, and a `NOT VALID` false check can also contribute to the existing unvalidated count.

Only the exact selected expression is recognized: equivalent `CHECK (NOT true)` and many other always-false expressions can pass this clue. Unexpected or differently named checks are outside this metric. Deparser output may vary by PostgreSQL version; no general semantic comparison, schema equivalence, data validation, repair or production-readiness claim is made. Use only authorized synthetic development databases.

## Evidence

On synthetic PostgreSQL 16, a valid source row succeeds under the original check but fails after a rolled-back replacement with same-named `CHECK (false)`, which the full command flags without names. A same-named `CHECK (NOT true)` also rejects the valid row but is not flagged by this exact clue or the full command, demonstrating the remaining blind spot. A synthetic `NOT VALID` false replacement produces both unvalidated and false-check counts; extra unexpected true/false constraints do not produce these selected named-check counts. Clean-schema and one-statement read-only tests remain. A small local PostgreSQL 16.2 probe interleaved 30 `EXPLAIN ANALYZE` samples each of the earlier `0bd5159` inspector and the current inspector (which also includes ADRs 0103 and 0104), against the same 31-table synthetic database while other tests ran. Median execution was 89.226 ms and 99.323 ms, with sample p95 of 135.904 ms and 158.845 ms respectively; median planning was 5.552 ms and 13.771 ms. This cached single-machine sample excludes client/ORM overhead and does not establish causation or a general performance bound. These examples are not exhaustive.
