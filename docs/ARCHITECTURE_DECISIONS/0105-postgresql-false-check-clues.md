# ADR 0105: selected constant-false check clues

Status: development-only implementation, 24 November 2026; extends [ADR 0104](0104-postgresql-constant-check-clues.md).

## Decision

For selected explicitly named model check constraints, the single catalog statement now also counts exact PostgreSQL deparsed `false` expressions as `canonical_reject_all_named_checks`. Such a check rejects every attempted insert or update reaching it. A nonzero count yields `attention`, without names or expressions. This is separate from the true/null accept-all count. A deliberately empty domain or intentional check can be flagged, and a `NOT VALID` false check can also contribute to the existing unvalidated count.

Only the exact selected expression is recognized: equivalent `CHECK (NOT true)` and many other always-false expressions can pass this clue. Unexpected or differently named checks are outside this metric. Deparser output may vary by PostgreSQL version; no general semantic comparison, schema equivalence, data validation, repair or production-readiness claim is made. Use only authorized synthetic development databases.

## Evidence

On synthetic PostgreSQL 16, a valid source row succeeds under the original check but fails after a rolled-back replacement with same-named `CHECK (false)`, which the full command flags without names. A same-named `CHECK (NOT true)` also rejects the valid row but is not flagged by this exact clue or the full command, demonstrating the remaining blind spot. Clean-schema and one-statement read-only tests remain. These examples are not exhaustive.
