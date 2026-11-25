# ADR 0050: lock the latest existing source review during triage

Status: development-only, 23 November 2026. This narrows a selected review-token race; it does not establish source rights or protect the entire review history.

## Decision

The source triage writer locks the claim and validates its current fingerprint and recorder, then compares the client's latest-review ID. Synthetic PostgreSQL tests initially reproduced concurrent bulk updates and deletions of the latest existing review while the writer was about to create a new one. The writer now locks just the latest existing review by primary key, after locking and checking the claim, with one ordered, limited `SELECT FOR UPDATE` on the claim's database. The helper requires an atomic transaction and the lock lasts until the outer transaction commits or rolls back. No row is locked when none exists.

The comparison remains ID-only: the writer does not validate the prior review's contents, reviewer or historical authorization. The private source detail page states that history is not validated and concurrent or subsequent changes remain possible. No permission, legal approval or automated source access is implied.

## Evidence and limits

Tests on separate PostgreSQL connections cover update and delete timeout against the locked latest row, release on commit or failed-write rollback, survival until outer commit, the helper's transaction and bounded query, and an uncommitted deletion becoming a conflict. An uncommitted update is waited for but can still be accepted with the same ID, demonstrating that content is not checked. Older rows are not locked. A bypass can insert a new review with deferred constraints and commit after the writer, so this row lock is neither a predicate lock nor an immutability guarantee. Same-transaction bypass, missing rows, later changes, concurrent account changes and other schedules are outside the guarantee.

The extra lock can wait or participate in deadlocks; no production timeout or retry policy is added. These synthetic tests do not establish source rights, reviewer qualification, immutable history, snapshot consistency or production readiness.
