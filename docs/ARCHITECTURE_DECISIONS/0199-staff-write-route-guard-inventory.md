# ADR 0199: in-flight guard tests for every staff write route, plus an inventory drift guard

Status: **development-only test coverage**, not a new control. The guards it inventories remain partial mitigations, and ADR 0191 remains an unresolved production blocker.

## Context

ADRs 0192–0198 added a locked or unlocked `recheck_actor` call to sixteen guarded write services. Two weaknesses remained in the evidence rather than the control:

1. HTTP-level in-flight tests existed for eleven of the fourteen staff write routes. The three revision routes — clinical revise, identity package revise and identity component correction — were covered only at service level, so a view that stopped passing `HASH_SESSION_KEY` would not have failed any test on those routes.
2. Coverage was tracked by hand in prose. Nothing failed when a new staff route or write service appeared without a recheck or without an in-flight test, so the documented boundary could silently drift from the code.

## Decision

1. `daroobank/test_staff_inflight_revision_writes.py` adds synchronized HTTP tests for the three remaining revision routes. Each parks a CSRF-valid POST at the **service entry** by patching the module-level `require_staff` of `clinical.services` or `catalog.identity`; the views import that name into their own namespace, so the patch does not disturb the view's own checks and fires only inside the service, before its recheck. While the request is parked, the test commits disable plus password invalidation plus reactivation and asserts 403 with unchanged row counts, then asserts that the next request from the same session is redirected to login. A distinct case commits a flag-only disable/reactivate and asserts the parked write **still commits**, and a missing CSRF token is rejected before any of this. Revision payloads change the assertion, because identity revisions reject identical payloads as no-ops before any actor check matters.
2. `daroobank/test_staff_write_route_inventory.py` enumerates every `staff_*` route name from the URL resolver and requires each to be either:
   - **covered**: mapped to a test module that must actually name the route and contain a parked password-invalidation case, or
   - **classified**: read-only list/detail/inspection/lineage, sample download, or login/logout.
   A new or renamed staff route fails the test until it is explicitly classified, and a stale entry fails too. The test also asserts that `docs/SECURITY.md` still states this is not durable revocation and still links ADR 0191.
3. The fourteen covered routes are: source create, source review, price review, clinical review, product review, product upload, price upload, clinical create, clinical reference create, clinical revise, identity create, identity review, identity package revise and identity component correction.

No production code changed in this step.

## Limits and consequences

- The inventory is **name-based, not behavior-based**. It proves a test module mentions a route and parks a write around a password invalidation; it does not prove that the route's write is guarded, that the guard is correct, or that reads are safe. Read routes are classified, not verified.
- The park point is a test seam. It relies on views importing `require_staff` by name; if a view switches to a module-qualified call, the patch would fire earlier in the view and the affected test would need updating rather than silently passing.
- All fourteen guards remain the same partial mitigations: unlocked point-in-time rechecks (except `record_claim`'s account-row lock), password-hash binding only, no serialization of permission or group changes, no deadline, and no cancellation of a writer already past its recheck. Every flag-only reactivation case in these tests **asserts that the write still happens**.
- The tests are synthetic PostgreSQL tests of selected orderings on a development-only portal. They do not establish production readiness, replace MFA, or permit real accounts or data.

## Selected evidence

`daroobank/test_staff_inflight_revision_writes.py` (6 tests) and `daroobank/test_staff_write_route_inventory.py` (3 tests) pass on synthetic PostgreSQL. The inventory test classifies all 43 `staff_*` route names as 14 covered write routes and 29 non-write routes. Together with `test_staff_inflight_write.py`, `test_staff_inflight_review_writes.py`, `test_staff_inflight_stage_writes.py`, `test_staff_inflight_clinical_writes.py` and `test_staff_inflight_identity_writes.py`, every staff write route now has a synchronized denied case, a documented still-commits case where applicable, and a CSRF negative control.
