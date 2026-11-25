# ADR 0174: coordinate synthetic clinical lock observation at the SQL boundary

Status: test-only; no production locking, conflict or retry change.

## Context and decision

One shuffled optimized full synthetic run failed because a clinical oversized-writer test did not observe a blocked backend within its four-second polling window. That run overlapped another full suite; five later focused runs passed. The exact cause of the isolated failure is not established.

The test previously announced its backend PID before loading the actor, checking permissions and reading evidence. It now announces the PID from a test-only Django SQL execution wrapper immediately before the `SELECT ... FOR UPDATE` for the specific child or parent under test. It still requires PostgreSQL `pg_blocking_pids` to show a real blocker, waits for the first transaction to commit, verifies the expected conflict and checks no partial writes. This narrows pre-lock scheduling uncertainty; it does not claim a fix for every intermittent failure, increase the database lock timeout, replace the blocking assertion, or prove all interleavings safe.

## Evidence and limits

The revised synthetic test covers three writers and each of child and immediate parent, supplemented by shuffled normal/optimized focused runs. It does not cover all PostgreSQL versions, production workloads, absent rows, later bypass writes or outer-transaction commit conflicts. Races can still depend on scheduling.
