# ADR 0104: selected constant check-constraint clues

Status: development-only implementation, 24 November 2026; extends [ADR 0074](0074-postgresql-check-constraint-names.md).

## Decision

For explicitly named managed-model check constraints resolved by table, name and PostgreSQL constraint type, the single read-only catalog statement also flags PostgreSQL's exact deparsed constant expressions `true` and `NULL::boolean`. A PostgreSQL `CHECK` rejects false but accepts both true and null, so either expression accepts every row. The aggregate `canonical_accept_all_named_checks` produces `attention` without displaying names or expressions. An unvalidated constant check can be counted by both the existing unvalidated count and this new count. Intentionally trivial expected checks will also be flagged.

This is not expression equivalence or full constraint comparison: `CHECK (1 = 1)`, `CHECK (NOT false)` and many other accepting expressions are outside the exact subset, and differently named or unexpected checks are not evaluated by this new count. PostgreSQL deparser representations can vary by version. It does not verify actual table data, provenance, security, migrations or production readiness, and performs no repair. Use an authorized synthetic development database only.

## Evidence

On synthetic PostgreSQL 16, a normal model constraint rejects a scope-free source claim. Rolled-back replacements with same-named `CHECK (true)` and `CHECK (NULL)` accept that row but yield attention with no names. A same-named `CHECK (1 = 1)` also accepts the row yet remains unflagged, including by the full command, explicitly demonstrating the semantic blind spot. A separate extra, unexpected `CHECK (true)` is not counted by the selected named-check metric. Clean-schema and one-statement read-only checks remain in place. These examples do not cover all expressions, schema states or server versions.
