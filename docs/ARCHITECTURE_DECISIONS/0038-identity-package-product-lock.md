# ADR 0038: immediate product row lock for identity package review and correction

Status: development-only, 22 November 2026. Narrows the package graph concurrency limitations in ADRs [0012](0012-synthetic-identity-drafts.md), [0013](0013-synthetic-package-revisions.md) and [0037](0037-identity-graph-creator-presence.md).

## Problem and decision

A selected synthetic PostgreSQL race demonstrated that package review locked its package but allowed the directly related product row to change after the graph read and before the review was saved. The older correction code read the product in a join before obtaining its later product lock during child creation. These models' ordinary guards do not prohibit bulk ORM or SQL changes.

Inside the existing transaction, package review and package correction now lock the package first, then separately re-read and `SELECT FOR UPDATE` its immediate product on the same database, replacing any cached product before graph reconstruction. A dangling product conflicts. The same product lock already used by nested package creation is reacquired within the correction transaction. PostgreSQL holds the row locks until the outermost transaction completes. Invalid non-string review decisions now result in `IdentityConflict` after the existing permission check, rather than a type error for unhashable inputs. HTTP form validation continues to return 400.

The product lock is not whole-graph isolation: the formulation, ingredients and component rows are not explicitly locked by these two paths, account checks remain separate and without exclusive user locks, and reads of related records are not a single snapshot. The interface explains the distinction. Other identity writers retain their existing locks and behavior. Package/product lock order adds waiting and may participate in deadlocks with non-cooperating code; no retry is added. Neither a lock nor a hash establishes identity, rights, clinical correctness or historical audit.

## Evidence and limitations

Synthetic separate-connection tests pause review and correction after graph validation: a competing update to the product times out, then succeeds after commit. If a product update holds the lock first, each writer re-reads it after waiting and rejects the now-inconsistent graph. Tests check cached-object replacement, missing-product conflict under restored deferred-FK corruption, an enclosing transaction's lock lifetime, direct validation and HTTP privacy/400 behavior. Another separate-connection test shows an unlocked formulation can change after a review's snapshot is read and the review can still save the earlier graph. These are specific schedules, not proof of no deadlocks or every race; tests do not demonstrate concurrent deletion.

Mutations to unlocked components, uncooperative writes after commit, phantom inserts, deferred constraints, ABA, stale account presence, unrelated identities, parent correction ancestry and database routing beyond the existing setup remain outside this guarantee. More locks can increase latency and lock/deadlock/serialization failures. The developer-only flow uses synthetic data and is not a publication, licensing, medical, security or production-readiness claim.
