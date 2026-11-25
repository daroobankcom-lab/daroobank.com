# ADR 0049: lock the latest existing clinical review during triage

Status: development-only, 23 November 2026. This narrows one selected review-token race; it is not a history lock, clinical approval or audit guarantee.

## Decision

The clinical triage writer already locks the draft, its immediate parent when present, and bounded existing reference rows. It checks the latest review ID supplied by the client before writing a new preliminary review. Before this change, a bulk writer could update or delete that latest row after the ID was read but before the new review was created. Synthetic PostgreSQL tests first reproduced the unblocked update and deletion.

After the existing draft, parent and reference locks, the writer now selects the latest existing review ID with `ORDER BY pk DESC LIMIT 1 FOR UPDATE` on the draft's database. The helper requires an atomic transaction and holds that row lock through the outermost commit or rollback. If no review exists, no row is locked. The writer still compares only the prior ID: it does not validate the prior review's content, snapshot, reviewer or historical authorization. The private detail page states that this is not complete history validation. No new publication, approval, medical validation or permissions are introduced.

## Evidence and limits

Synthetic separate-connection PostgreSQL tests exercise selected update and delete attempts while review is paused; the bypass writer encounters the tested lock-timeout SQLSTATE, and can update after the review commits. A previously uncommitted deletion is re-read as a conflict, the lock survives an outer transaction, and failed-write rollback releases it. An earlier update with an unchanged ID is waited for but can still be accepted. Other tests check one bounded lock query, its atomic requirement, no prior row, unchanged ID-only semantics, and an older review remaining unlocked. One deferred-constraint bypass inserts a later review while the writer's outer transaction is open and commits after it; this remains possible because the latest-row lock is not a predicate or gap lock. Same-transaction bypass, later writes, absent rows, earlier reviews, account changes and other schedules remain outside the guarantee.

Additional locks can wait or participate in deadlocks; application-level timeouts and retries are not introduced. The tests' timeouts are not deployment settings. The lock does not make history immutable or prove identity, source rights, reviewer qualification, clinical accuracy, snapshot consistency or production readiness. Use synthetic data only.
