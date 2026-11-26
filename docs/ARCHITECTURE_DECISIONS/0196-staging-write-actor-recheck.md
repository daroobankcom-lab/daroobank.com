# ADR 0196: extend the shared actor recheck to the staging write paths

Status: **development-only, partial mitigation**, not session revocation or an account lifecycle solution. ADR 0191 remains an unresolved production blocker.

## Context

ADR 0195 put one shared helper, `daroobank.actor_recheck.recheck_actor`, behind five guarded review and claim services. The bulk write paths were still authorized only against the caller-supplied actor: `catalog.intake.stage_products` and `pricing.importer.stage_csv`, and the receipt wrappers `ingestion.receipts.stage_product_with_receipt` and `stage_price_with_receipt` that the staff upload views call. A synthetic stager whose account was disabled, destaffed or deleted after the request began, whose add permission was removed while the request object kept a primed Django permission cache, or whose password was invalidated mid-request could still stage rows and create an import receipt.

While writing these tests, an earlier evidence weakness was found and corrected: the permission-removal cases in the ADR 0192–0195 tests removed permissions through the *same* user instance they then passed to the service. Django clears that instance's permission cache on its own many-to-many change, so the services' pre-existing checks denied the call and the tests did not prove the new recheck worked. Those cases now remove permissions, group membership or group permissions through a **second instance**, leaving the request actor's cache stale so only a fresh database recheck can deny it.

## Decision

1. `stage_products` and `stage_csv` accept an optional keyword `session_auth_hash`. In commit mode only, immediately after the existing source-stage advisory lock and before any row is written, they call `recheck_actor` with their view/add permission pair and the supplied hash. Preview mode writes nothing and is not rechecked.
2. The receipt wrappers accept and forward `session_auth_hash`; the staff product and price upload views pass `request.session.get(HASH_SESSION_KEY)`.
3. The recheck is **unlocked**, like every other adoption except `record_claim`: these services take a source-stage advisory lock and then candidate row locks, and adding an account row lock here would introduce another order against `record_claim`'s account-then-target order.
4. Actor-less price staging keeps its existing behavior and is **not** rechecked. `stage_csv` permits `staged_by=None` for the original importer and CLI paths, which are outside the staff web route; rechecking there would have changed unrelated behavior. The staff routes always supply an actor.
5. `daroobank/test_actor_recheck.py` now derives its near-miss session hash by flipping one character deterministically. The previous fixed replacement digit could coincidentally equal the real hash, and one optimized-mode regression run failed for that reason; the hash comparison itself behaved correctly.

No new table, migration, setting, dependency or route is introduced.

## Limits and consequences

- **Not durable revocation and not race-free.** The recheck is a point-in-time read. Selected synthetic tests park a staging writer at candidate insertion, then disable the account, invalidate its password and re-enable it; the rows and receipt still commit. A flag-only disable/reactivate with the password unchanged also still lets a parked HTTP upload commit.
- The hash covers the password field only. Logout, session deletion or rotation, group and permission changes committed after the read, alternate authentication backends, MFA factors and incident recovery are out of scope, and the compared value is the one read from the session store when the request started.
- Preview mode and actor-less staging are not rechecked, so they remain reachable by a stale session in the ways the existing code already allowed; preview writes nothing, but it does read and validate.
- Coverage is now seven services on seven staff routes (source claim creation and review, source review, price review, clinical review, product review, product staging, price staging). Other writes, identity and revision services, reads, arbitrary SQL, bulk ORM operations, management commands, other databases and a deployed multi-database router are untouched. [ADR 0197](0197-clinical-write-actor-recheck.md) later extended the same helper to clinical draft create/revise and reference create. Permission changes are still not serialized anywhere.
- Each recheck adds one account query while the source-stage advisory lock is held, slightly extending that lock. No deadline, lock timeout or retry policy is added.
- The staff portal remains development-only and synthetic. This does not establish production readiness, replace MFA, or permit real accounts or data.

## Selected evidence

`catalog/test_stage_actor_recheck.py` and `pricing/test_stage_actor_recheck.py` cover matching and omitted hashes, stale/empty/integer/list hashes, password rotation, disabled or destaffed stagers behind a stale instance, an add permission removed through a second instance, deleted stagers (including that pricing's own pre-check rejects an unprimed instance with `ImportValidationError` before the recheck), receipt-wrapper forwarding, and a parked-writer race showing a credential change after the recheck still stages. `daroobank/test_staff_inflight_stage_writes.py` parks CSRF-valid product and price upload POSTs before their guarded transactions: disable plus password invalidation plus reactivation yields 403 with no candidates and no receipt and a login redirect for the next request, a flag-only disable/reactivate still stages, and a missing CSRF token is rejected. These are synthetic PostgreSQL tests of selected orderings, not exhaustive security evidence.
