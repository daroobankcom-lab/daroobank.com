# ADR 0194: reviewer recheck and session hash binding for synthetic source reviews

Status: **development-only, partial mitigation**, not session revocation or an account lifecycle solution. ADR 0191 remains an unresolved production blocker.

## Context

ADR 0192 and ADR 0193 hardened one write path: `record_claim` locks and reloads its actor's account row and, when the staff view supplies it, rechecks the requesting session's password hash. The sibling review path did not. `review_claim` authorized only against the caller-supplied actor object, so a synthetic reviewer whose account was disabled, destaffed, deleted or whose review permission was removed after the request began could still record a review, and a password invalidation committed mid-request was invisible to it. A synchronized synthetic HTTP test confirmed the review committed after disable, password invalidation and reactivation.

## Decision

`review_claim` accepts an optional keyword `session_auth_hash`, and the development staff review view passes `request.session.get(HASH_SESSION_KEY)`. Inside the existing writer transaction, immediately after the claim row lock is taken and before any review row is created, the service:

1. rejects a non-integer or out-of-range actor primary key;
2. loads the reviewer's current database row **without a row lock** and repeats the active, staff and required-permission checks against that fresh instance, so cached Django permissions on the request actor are not trusted;
3. when a session hash is supplied, compares it in constant time with the fresh account's `get_session_auth_hash()` and denies a non-string or mismatching value.

Any failure raises `PermissionDenied`, which this route surfaces as HTTP 403 without creating a review. Omitting the hash keeps direct service calls, management paths and existing tests working; those calls are not authenticated by this check. No new table, setting, dependency or route is introduced. [ADR 0195](0195-shared-write-actor-recheck.md) later moved these checks into one shared helper and extended the same pattern to the pricing and clinical review services.

The reviewer read is deliberately **unlocked**. `record_claim` locks the account row before the claim row; taking an account lock after the claim lock here would invert that order across the two services and could deadlock under concurrency. Preserving a single lock order was judged more important than serializing this read.

## Limits and consequences

- Applies only to source-claim review through `review_claim` reached from the staff review view. Other apps' review services, reads, arbitrary SQL, other databases and a deployed multi-database router are untouched.
- **Not serialization and not durable revocation.** Because the reviewer read takes no lock, an account or credential change committed after that read still races the write. A selected synthetic test parks a review after the recheck, then disables the account, invalidates its password and re-enables it; the review is still created. Similarly, a flag-only disable/reactivate with the password unchanged still lets a parked HTTP review commit, and a later request from that unexpired session is accepted.
- The hash covers the password field only in this Django version. Logout, session deletion or rotation, group and permission changes, alternate authentication backends, MFA factors and incident recovery are not covered.
- The compared value is the one read from the session store when the request started; session-store compromise, fixation or cookie theft defeat it. Those boundaries are separate work.
- This adds one extra account query per review, inside the claim lock, lengthening the time the claim row is held. No deadline, lock timeout or retry policy is added; operational timeouts, lock order and load require review.
- The staff portal remains development-only and synthetic. This does not establish production readiness, replace MFA, or permit real accounts or data.

## Selected evidence

`sources/test_review_session_binding.py` covers a matching hash and an omitted hash, stale/empty/integer/list hashes, password rotation before the review, a disabled or destaffed reviewer whose stale instance still looks active, a removed review permission behind a primed permission cache, a deleted reviewer, and a parked-writer race in which a credential change after the recheck still commits. `daroobank/test_staff_inflight_write.py` parks a CSRF-valid review POST inside input validation: disable plus password invalidation plus reactivation yields 403 with no review and a login redirect for the next request, while a flag-only disable/reactivate still commits, documenting the remaining gap. These are synthetic PostgreSQL tests of selected orderings, not exhaustive security evidence.
