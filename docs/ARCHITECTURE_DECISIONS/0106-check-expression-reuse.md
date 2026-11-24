# ADR 0106: reuse selected check expressions within one catalog statement

Status: development-only implementation, 24 November 2026; extends [ADR 0104](0104-postgresql-constant-check-clues.md) and [ADR 0105](0105-postgresql-false-check-clues.md).

## Decision

The inspector materializes the already selected named-check deparsed expressions once in its existing read-only PostgreSQL statement and counts the accept-all and reject-all exact constants from that set. The same table/name/type selection, output fields, attention policy and blind spots remain. The query still executes as one statement and does not return expressions or names. Materialization is additional work and memory; it is not a guaranteed optimization for every database or PostgreSQL version.

## Evidence

A synthetic test combines multiple true, null, false, nonconstant, missing, unexpected and unvalidated checks, checks separate aggregate counts and privacy, and verifies that one catalog statement runs. Another synthetic test uses quoted Unicode and SQL-like table/constraint names to verify parameterized resolution and aggregate-only output while a separate table remains intact. Other tests exercise actual permitted/rejected writes and the noncanonical blind spots. On PostgreSQL 16.2, an interleaved local `EXPLAIN ANALYZE` probe on the same 31-table synthetic database compared 30 samples of the prior `fcd10a3` query and 30 of the reused-expression query with other tests running. The measured execution medians were 71.151 ms and 65.524 ms, and sample p95s were 145.495 ms and 127.947 ms; median planning times were 13.732 ms and 7.761 ms. A separate synthetic probe compared the complete aggregate reports of both versions across seven selected catalog states: clean, missing named check, true, null, false, a noncanonical tautology and unvalidated false; all matched. This is not an exhaustive equivalence proof. This small cached sample excludes ORM/network cost, does not establish causation and is not a bound or production benchmark. Neither query validates arbitrary expressions, data or production readiness.
