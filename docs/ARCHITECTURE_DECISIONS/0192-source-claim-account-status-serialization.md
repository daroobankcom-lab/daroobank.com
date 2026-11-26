# ADR 0192: narrow account-status serialization for synthetic source claims

Status: **development-only, partial mitigation**, not an account lifecycle or session revocation solution. ADR 0191 remains an unresolved production blocker.

## Context

A synthetic CSRF-valid source-claim POST previously committed after its actor was disabled, when the disable committed after the request's authorization checks but before the insert. Similar issues may exist elsewhere. A request already authorized is not automatically cancelled by a database change.

## Decision

For the existing PostgreSQL `record_claim` service only, after initial authorization and validation, lock and reload the actor's current database row inside the same writer transaction using `FOR NO KEY UPDATE`; repeat the active, staff and required-permission checks against this freshly loaded instance. Hold the lock until that transaction (including any caller's outer transaction) completes. If the account status update commits before the lock is acquired, the write is denied; if the writer acquires the lock first, the account update waits until the writer completes. This orders these operations; it does **not** cancel a writer that already acquired the lock. The weaker PostgreSQL row lock allows foreign-key `KEY SHARE` locks; the synthetic test verifies both that compatibility and a conflicting status update with a deliberately short test-only timeout.

## Limits and consequences

- Applies only to source-claim creation/replay through `record_claim`, not review, other services, arbitrary SQL, other databases or a deployed multi-database router configuration. The project's current database setup uses a single PostgreSQL default database.
- The status check alone does not compare the requesting session's authentication hash or a durable generation. A synchronized synthetic HTTP test showed that a disable, password invalidation and re-enable all committing before the guarded write still let the in-flight old session create a claim; [ADR 0193](0193-source-claim-session-hash-binding.md) now denies that case by binding the write to the session hash. Re-enabling flags without changing the password still permits the parked write. Other credentials, login, MFA and incident recovery are untouched.
- Rechecking a freshly loaded actor avoids trusting an existing request actor's cached Django permissions when a removal has already committed before this second check. Permission and group changes are **not** serialized by the account-row lock: a selected synthetic test removes permissions after the fresh check and the in-flight write still commits. The second check is not durable or race-free permission revocation; this remains a production blocker.
- Initial checks still use the supplied actor and configured authentication backend. Alternate backends, permission caches, other workers and direct services require an explicit, independently reviewed lifecycle design.
- This adds a database round trip and serializes same-account source writes. Locks may wait without a service-level deadline, can be held longer by enclosing transactions and can participate in deadlocks with other operations. Selected database conflict translation is not a complete timeout or retry policy. Operational timeouts, lock order and load require review.
- This does not establish production readiness or permit real data. The staff portal remains development-only. Before a broader rollout, design transaction and authorization semantics across all read and write paths, permission changes, account transitions, direct/bulk changes, session stores and in-flight work, and independently assess them.

## Selected evidence

`daroobank/test_staff_inflight_write.py` synchronizes a CSRF-valid request so disable and password invalidation commit before the guarded write begins; it then asserts 403 and no claim. A CSRF negative control and a fresh disabled-request control are included. `sources/test_claim_actor_status_boundary.py` checks stale or deleted accounts, active-account and group-permission positive controls, the opposite lock ordering, foreign-key lock compatibility, pre-check direct/group/superuser revocation and a distinct permission-removal race after the fresh check. These are synthetic PostgreSQL tests of selected orderings, not exhaustive security evidence.
