# ADR 0195: one shared write-actor recheck for selected guarded services

Status: **development-only, partial mitigation**, not session revocation or an account lifecycle solution. ADR 0191 remains an unresolved production blocker.

## Context

ADRs 0192–0194 hardened two source-claim services: creation locks and reloads its actor, review reloads its reviewer without a lock, and both can bind the write to the requesting session's password hash. The same gap existed in the other guarded review services, which authorized only against the caller-supplied actor object: `pricing.reviews.record_preliminary_review` and `clinical.services.review_draft`. A synthetic reviewer whose account was disabled, destaffed or deleted after the request began, whose review permission was removed behind a primed Django permission cache, or whose password was invalidated mid-request could still record a review. Copying the same inline checks into each service would have repeated the wording, the ordering rationale and the failure modes several times, making them hard to audit and easy to drift.

## Decision

Add one helper, `daroobank/actor_recheck.py::recheck_actor(actor, perms=(), *, session_auth_hash=None, lock=False)`, that:

1. denies a `None` actor and a non-integer or out-of-range primary key;
2. reloads the account, optionally under a PostgreSQL `FOR NO KEY UPDATE` row lock when `lock=True`;
3. denies a missing account and repeats the authenticated, active, staff and listed-permission checks against the fresh instance, so cached permissions on the request actor are not trusted;
4. when a session hash is supplied, denies a non-string value or a constant-time mismatch against the fresh account's `get_session_auth_hash()`;
5. returns the fresh instance.

Adoption in this change:

| Service | Recheck | Lock | Session hash supplied by |
| --- | --- | --- | --- |
| `sources.services.record_claim` | flags + `view`/`add` | account row, `FOR NO KEY UPDATE`, before the claim row | staff create view |
| `sources.services.review_claim` | flags + `view`/`review` | none | staff review view |
| `pricing.reviews.record_preliminary_review` | flags + pricing `view`/`review` | none | staff price review view |
| `clinical.services.review_draft` | flags + clinical `view`/`review` | none | staff clinical review view |

Only `record_claim` takes the account-row lock, because it is the only one of these that locks the account before its target row. Every other service locks its target row first and therefore uses the **unlocked** recheck; acquiring an account lock there would invert the order across services and could deadlock. Omitting `session_auth_hash` keeps direct service calls, management paths and existing tests working, and authenticates nothing. No new table, migration, setting, dependency or route is introduced.

## Limits and consequences

- **Not durable revocation and not race-free.** An unlocked recheck is a point-in-time read: selected synthetic tests park a pricing review and a clinical review after that read, then disable the account, invalidate its password and re-enable it, and the reviews still commit. A flag-only disable/reactivate with the password unchanged also still permits a parked HTTP write, and a later request from that unexpired session is accepted.
- The hash covers the password field only in this Django version. Logout, session deletion or rotation, group and permission changes, alternate authentication backends, MFA factors and incident recovery are out of scope. The compared value is the one read from the session store when the request started; session-store compromise, fixation or cookie theft defeat it.
- Coverage is four services on four routes. Staging and upload paths, other writes, reads, arbitrary SQL, bulk ORM operations, other databases and a deployed multi-database router are untouched, and permission changes are still not serialized anywhere.
- Each unlocked recheck adds one account query inside the target-row lock, lengthening the time that row is held; the locked recheck in `record_claim` additionally serializes same-account source writes. No deadline, lock timeout or retry policy is added, and selected database conflict translation is not a complete timeout policy. Operational timeouts, lock order and load require review.
- The helper is a code-level guard: local code and management commands can call these services without a session hash, and any writer can bypass model guards with bulk ORM or SQL. The staff portal remains development-only and synthetic. This does not establish production readiness, replace MFA, or permit real accounts or data.

## Selected evidence

`daroobank/test_actor_recheck.py` covers the helper directly: a fresh returned instance, absent/anonymous/out-of-range/string actors, disabled or destaffed accounts behind a stale instance, a deleted account, a removed permission behind a primed cache, empty permission tuples, matching/omitted/stale/empty/non-string/near-miss session hashes, password rotation, and that `lock=True` requires an atomic block and takes a `FOR NO KEY UPDATE` lock. `pricing/test_review_actor_recheck.py` and `clinical/test_review_actor_recheck.py` repeat the reviewer cases against their services and each includes a parked-writer race showing a credential change after the unlocked recheck still commits. `sources/test_review_session_binding.py`, `sources/test_claim_actor_status_boundary.py` and `daroobank/test_staff_inflight_write.py` keep covering the source paths after the refactor to the shared helper. `daroobank/test_staff_inflight_review_writes.py` parks CSRF-valid price and clinical review POSTs inside service input validation and checks that disable plus password invalidation plus reactivation before the guard yield 403 with no review and a login redirect for the next request, that a flag-only disable/reactivate still commits, and that a missing CSRF token is rejected; these HTTP cases are what prove the two views actually pass the session hash. These are synthetic PostgreSQL tests of selected orderings, not exhaustive security evidence.
