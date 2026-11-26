# ADR 0198: extend the shared actor recheck to the identity workspace writes

Status: **development-only, partial mitigation**, not session revocation or an account lifecycle solution. ADR 0191 remains an unresolved production blocker.

## Context

ADRs 0195–0197 put the shared `daroobank.actor_recheck.recheck_actor` helper behind the guarded review services, the bulk staging paths and the clinical draft/reference writes. The synthetic identity workspace was still authorized only against the caller-supplied actor object: `create_ingredient`, `create_formulation`, `create_product`, `create_package`, `revise_package`, `revise_identity` and `review_package` in `catalog/identity.py`. A writer whose account was disabled, destaffed or deleted after the request began, whose add or review permission was removed while the request object kept a primed Django permission cache, or whose password was invalidated mid-request could still create an assertion, a correction branch or a package review.

## Decision

1. All seven identity write services accept an optional keyword `session_auth_hash`.
2. Each calls `recheck_actor` with its own permission pair — `(VIEW, ADD)` for the create and revise services, `(VIEW, REVIEW)` for `review_package` — before any row is written: inside the existing `_identity_atomic()` transaction and before the first row lock for the transactional services, and immediately before the single `create` call for `create_ingredient`, which has no transaction of its own.
3. The rechecks are **unlocked**, like every adoption except `record_claim`. These services lock their target and ancestor rows (ingredient rows, formulation, product, package, existing reviews) in a documented order; adding an account row lock would introduce another order against `record_claim`'s account-then-target order and could deadlock.
4. The four identity staff write views — create (all four kinds), package revise, component correction and package review — pass `request.session.get(HASH_SESSION_KEY)`. Omitting the hash keeps direct service calls, test helpers such as `catalog.test_identity.build`, and management paths working, and authenticates nothing.
5. Tests follow the corrected evidence convention from ADR 0196: permission removals go through a **second** user instance so the request actor keeps its stale cache and only the fresh database recheck can deny it. Denial cases compare row counts against a recorded baseline rather than asserting emptiness, because formulation components protect their ingredient rows and the HTTP fixtures already build a chain.

No new table, migration, setting, dependency or route is introduced.

## Limits and consequences

- **Not durable revocation and not race-free.** The rechecks are point-in-time reads. A selected synthetic test parks a package revision inside its guarded transaction, then disables the account, invalidates its password and re-enables it; the revision still commits. A flag-only disable/reactivate with the password unchanged also still lets a parked HTTP ingredient create and a parked package review commit.
- The hash covers the password field only. Logout, session deletion or rotation, group and permission changes committed after the read, alternate authentication backends, MFA factors and incident recovery are out of scope, and the compared value is the one read from the session store when the request started.
- Coverage is now sixteen services across fourteen staff routes: source-claim creation, source review, price review, clinical review, product review, product staging, price staging, clinical draft create/revise, clinical reference create, and the seven identity writes. Inspection, lineage and read services, the catalog projection repair command, arbitrary SQL, bulk ORM operations, other databases and a deployed multi-database router remain untouched. Permission changes are still not serialized anywhere.
- Each recheck adds one account query per identity write, at the start of the guarded transaction and therefore while its row locks are held afterwards. No deadline, lock timeout or retry policy is added; operational timeouts, lock order and load require review.
- The identity workspace is a synthetic development draft area, never a published catalogue or an equivalence claim. The staff portal remains development-only. This does not establish production readiness, replace MFA, or permit real accounts or data.

## Selected evidence

`catalog/test_identity_actor_recheck.py` covers a matching hash across the whole create chain, omitted hashes for direct service calls, stale/empty/integer/list hashes denied for all six write entry points in one matrix, password rotation before a write, disabled or destaffed writers behind a stale instance, an add permission and a review permission removed through a second instance, a deleted writer, and a parked package revision showing that a credential change committed after the recheck still writes. `daroobank/test_staff_inflight_identity_writes.py` parks CSRF-valid ingredient-create and package-review POSTs at their service entry: disable plus password invalidation plus reactivation yields 403 with unchanged row counts and a login redirect for the next request, a flag-only disable/reactivate still commits, and a missing CSRF token is rejected. These are synthetic PostgreSQL tests of selected orderings, not exhaustive security evidence.
