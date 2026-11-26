# ADR 0197: extend the shared actor recheck to the clinical write paths

Status: **development-only, partial mitigation**, not session revocation or an account lifecycle solution. ADR 0191 remains an unresolved production blocker.

## Context

ADRs 0195 and 0196 put the shared `daroobank.actor_recheck.recheck_actor` helper behind the guarded review services and the bulk staging paths. Two clinical write services were still authorized only against the caller-supplied actor object: `clinical.services.create_draft`, used by both the draft-create and draft-revise routes, and `clinical.evidence.add_reference`. A synthetic writer whose account was disabled, destaffed or deleted after the request began, whose add permission was removed while the request object kept a primed Django permission cache, or whose password was invalidated mid-request could still create a draft, a revision or a supplementary reference assertion.

## Decision

1. `create_draft` and `add_reference` accept an optional keyword `session_auth_hash`.
2. Each calls `recheck_actor(actor, (VIEW, ADD), session_auth_hash=...)` as the first statement inside its existing writer transaction — for `create_draft` before the parent draft lock, for `add_reference` before the draft lock — so no row is written and no lock is taken against a stale actor.
3. The recheck is **unlocked**, like every adoption except `record_claim`. These services lock their draft row (and existing reference rows in PK order) first; adding an account row lock would invert that order against `record_claim`'s account-then-target order and could deadlock.
4. The three clinical staff write views — create, revise and reference create — pass `request.session.get(HASH_SESSION_KEY)`. The review view already did so under ADR 0194. Omitting the hash keeps direct service calls, management paths and existing tests working, and authenticates nothing.
5. Tests follow the corrected evidence convention from ADR 0196: permission removals go through a **second** user instance so the request actor keeps its stale cache and only the fresh database recheck can deny it.

No new table, migration, setting, dependency or route is introduced.

## Limits and consequences

- **Not durable revocation and not race-free.** The recheck is a point-in-time read. Selected synthetic tests park a draft writer inside fingerprinting and a reference writer inside reference fingerprinting, then disable the account, invalidate its password and re-enable it; both writes still commit. A flag-only disable/reactivate with the password unchanged also still lets a parked HTTP create commit.
- The hash covers the password field only. Logout, session deletion or rotation, group and permission changes committed after the read, alternate authentication backends, MFA factors and incident recovery are out of scope, and the compared value is the one read from the session store when the request started.
- Coverage is now nine services across ten staff routes: source-claim creation, source review, price review, clinical review, product review, product staging, price staging, clinical draft create and revise (one service, two routes) and clinical reference create. Identity and revision services in `catalog/identity.py`, inspection and read services, other writes, arbitrary SQL, bulk ORM operations, management commands, other databases and a deployed multi-database router remain untouched. Permission changes are still not serialized anywhere.
- Each recheck adds one account query at the start of the guarded transaction, marginally extending the time the draft row lock is held afterwards. No deadline, lock timeout or retry policy is added.
- The staff portal remains development-only and synthetic. This does not establish production readiness, replace MFA, or permit real accounts or data.

## Selected evidence

`clinical/test_write_actor_recheck.py` covers matching and omitted hashes, stale/empty/integer/list hashes, password rotation before a draft, disabled or destaffed writers behind a stale instance, an add permission removed through a second instance, a deleted writer, and parked races in which a credential change committed after each recheck still creates the draft and the reference. The same file checks the reference path for stale hashes, a disabled writer and a removed permission. `daroobank/test_staff_inflight_clinical_writes.py` parks CSRF-valid draft-create and reference-create POSTs inside service validation: disable plus password invalidation plus reactivation yields 403 with no row and a login redirect for the next request, a flag-only disable/reactivate still commits, and a missing CSRF token is rejected. These are synthetic PostgreSQL tests of selected orderings, not exhaustive security evidence.
