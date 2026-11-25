# ADR 0052: lock the latest existing product-candidate review during triage

Status: development-only, 23 November 2026. This narrows a selected review-token race; it does not validate or lock the entire history.

## Decision

The product triage writer locks and validates the staged candidate and then compares the client's latest-review ID. Synthetic PostgreSQL tests initially reproduced bulk updates and deletions of the latest existing review while the writer was about to create its next review. After the candidate lock and validation, the writer now locks just the latest existing review ID with one ordered, limited `SELECT FOR UPDATE` on the candidate's database. The helper requires an atomic transaction and holds the lock through the outermost commit or rollback. No review row is locked when none exists.

The token still checks only the prior ID, not prior review contents, reviewer or authorization. The private product detail page states that history is not validated and concurrent or subsequent changes remain possible. This introduces no approval, publication, source rights or real product verification.

## Evidence and limits

Separate-connection synthetic PostgreSQL tests exercise update and delete timeout against the selected row, release after commit or failed-write rollback, outer transaction lifetime, query and atomic boundaries, and an uncommitted deletion becoming a conflict. An earlier uncommitted update is waited for but can still be accepted with the same ID, demonstrating that content is not checked. Older rows remain unlocked. A bypass can insert a later review under deferred constraints and commit after the writer; this row lock is not a predicate lock or immutability guarantee. Same-transaction bypass, absent/future rows, later writes, concurrent account changes and other schedules remain out of scope.

The additional lock can wait or participate in deadlocks. No production timeout or retry policy is introduced. These synthetic tests do not establish product accuracy, source rights, reviewer qualifications, immutable history, snapshot consistency or production readiness.
