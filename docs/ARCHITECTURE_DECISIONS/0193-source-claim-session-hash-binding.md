# ADR 0193: bind the synthetic source-claim write to the session authentication hash

Status: **development-only, partial mitigation**, not session revocation or an account lifecycle solution. ADR 0191 remains an unresolved production blocker.

## Context

ADR 0192 re-reads the actor's account row inside the source-claim writer transaction, but a synchronized synthetic HTTP test still let a parked, already-authorized CSRF-valid write commit after account disable, password invalidation and reactivation all committed before the guard. Django's `AuthenticationMiddleware` verifies the session authentication hash once, when the request's user is first resolved; a password or credential change committed after that point is not re-checked inside the same request. The guard therefore compared flags and permissions, not the credential state the request was authorized with.

## Decision

`record_claim` accepts an optional keyword `session_auth_hash`. The development staff create view passes `request.session.get(HASH_SESSION_KEY)`. Inside the existing writer transaction, after the locked fresh actor reload and its active/staff/permission recheck, a supplied hash is compared with the freshly loaded account's `get_session_auth_hash()` using a constant-time comparison. A non-string value or a mismatch raises `PermissionDenied`, which this route surfaces as HTTP 403 without creating a claim. Callers that omit the hash keep the previous behavior; direct service calls, management paths and existing tests are not authenticated by this check. No new table, setting, dependency or route is introduced.

## Limits and consequences

- Applies only to source-claim creation/replay through `record_claim` reached from the staff create view. Other services and routes, other apps, arbitrary SQL, other databases and a deployed multi-database router are untouched. Review keeps its existing lock order (claim row first) and deliberately gains no account-row lock here, to avoid inverting that order against `record_claim`; [ADR 0194](0194-source-review-actor-session-recheck.md) later extends the same session-hash binding to review with an unlocked reviewer recheck.
- **This is not durable revocation.** The hash covers the password field only. A synthetic test asserts that disabling and re-enabling the account flags without changing the password still lets the parked in-flight write commit, and a later request from the same unexpired session is accepted. Logout, session deletion or rotation, group and permission changes, alternate authentication backends, MFA factors and incident recovery are not covered by this check.
- The value compared is the one already read from the session store when the request started. Session-store compromise, session fixation, cookie theft or a modified in-memory session defeat it; those boundaries are separate work.
- The comparison is a point-in-time check, not an ordering guarantee: a password change committing after the comparison still races the write. No deadline, lock timeout or retry policy is added.
- `get_session_auth_hash()` performs a password-hasher round per guarded write and depends on `SECRET_KEY` stability and the configured hashers; a secret rotation invalidates existing sessions for this route as it already does for authentication.
- The staff portal remains development-only and synthetic. This does not establish production readiness, replace MFA, or permit real accounts or data. A complete lifecycle design covering all read and write paths, credential changes, session stores, in-flight work and independent security review is still required.

## Selected evidence

`daroobank/test_staff_inflight_write.py` parks a CSRF-valid source-claim POST inside validation, commits disable plus password invalidation plus reactivation, and then asserts 403 with no claim and a login redirect for the next request from the same session; a distinct case commits a flag-only disable/reactivate with the password unchanged and asserts that the parked write still commits, documenting the remaining gap; CSRF and fresh-request negative controls are included. `sources/test_claim_actor_status_boundary.py` asserts that a matching hash is accepted, an omitted hash keeps direct service calls working, stale/empty/integer/list hashes are denied for an otherwise active and permitted actor, and a password rotation before the guard denies the previous hash while accepting the new one. These are synthetic PostgreSQL tests of selected orderings, not exhaustive security evidence.
