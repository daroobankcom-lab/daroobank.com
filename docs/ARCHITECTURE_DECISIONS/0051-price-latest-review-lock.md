# ADR 0051: lock the latest existing price review during triage

Status: development-only, 23 November 2026. This narrows one review-token race; it is not a price approval or complete history lock.

## Decision

The price triage writer locks and validates the staged candidate, then compares the client's latest-review ID; accepting a suggestion also locks and checks selected matching product rows. Before this change synthetic PostgreSQL tests reproduced concurrent bulk update and delete of the latest review while the next review was about to be created. The writer now locks the latest existing review ID after locking and validating the candidate and before matching product rows, via a single ordered and limited `SELECT FOR UPDATE` on the candidate database. The helper requires an atomic transaction. The lock lasts until the outer transaction commits or rolls back; no review row is locked if none exists.

Only the prior ID is compared, not the review content, reviewer or historical authorization. The private detail page explains that the history is not validated. This introduces no price publication, approval, legal permission or source access.

## Evidence and limits

Separate-connection synthetic PostgreSQL tests exercise update/delete timeouts, earlier update and deletion, lock lifetime across an outer transaction, release on failed-write rollback, helper query/transaction boundaries and selected non-guarantees. The acceptance path was tested holding both the latest review and a matching existing product lock. An earlier update with an unchanged ID can still be accepted; older reviews remain unlocked. A deferred bypass can insert a later review while the outer writer transaction is open and commit after it. Absent/future matching products also remain outside the existing product row lock, as before. These locks are not predicate locks or history immutability. Same-transaction bypass, later changes, concurrent account changes and other schedules remain outside scope.

Additional locks can wait or contribute to deadlock, especially because product locks follow review locks; no production timeout or retry policy is introduced. Synthetic tests do not establish product uniqueness, source rights, reviewer qualification, clinical accuracy, immutable history or production readiness.
