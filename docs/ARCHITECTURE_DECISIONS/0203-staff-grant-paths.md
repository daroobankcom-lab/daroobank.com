# ADR 0203: staff grant paths — groups, superuser, alternate backend and stale actors

Status: **development-only synthetic evidence**, not an authorization review or an approval. The `API and permissions` release gate remains open.

## Context

ADR 0200–0201 grant permissions directly to an account. Real deployments grant them through groups, Django grants everything to an active superuser, and an alternate authentication backend can change which accounts authenticate at all. Each of those paths can produce a different answer from the same route, and none of them was measured.

## Decision

Add `daroobank/test_staff_grant_paths.py`, which reuses the ADR 0200 route table and `satisfies` helper over the same 41 routes with five further account shapes. Expectations are derived from a freshly loaded account so no permission cache is reused. Recorded behavior:

| Account shape | Observed behavior on all 41 routes |
| --- | --- |
| staff, group holding all 16 permissions | reaches **41/41** — identical to the same grant applied directly |
| staff, group holding the 7 view permissions | reaches **25/41** — identical to the direct view-only grant |
| active superuser, `is_staff=True`, no explicit grant | reaches **41/41**; Django grants every permission, so least privilege does not apply to this shape |
| active superuser, `is_staff=False` | **403 on all 41**; the `is_staff` gate still holds |
| deactivated staff in the full group | never served content: 302 to login or 403 |
| deactivated staff in the full group, authenticated through `AllowAllUsersModelBackend` | a real session **is** established (`_auth_user_id` present), yet all 41 routes return **403**, with a body byte-identical to the default backend's denial of an active non-staff account |

Two further tests pin the surrounding hazards:

* **Stale in-memory actor.** After priming an object's permission cache and revoking the group grant through a second object, the stale object still reports `has_perm(...) == True`, while `recheck_actor` denies — with and without a matching `session_auth_hash` — and accepts again once the grant is restored. This is why the guarded services reload the account rather than trusting the caller's object.
* **Denial parity.** Every denial, whatever its reason, carries the staff privacy headers (`no-store`, `noindex, nofollow`), so a probing client cannot distinguish the reason from the response.

A red check confirmed the suite is not vacuous: dropping `is_staff=True` from the full-group account produced 42 failures before the change was reverted.

## Limits and consequences

- **The superuser result is a finding, not an endorsement.** A single superuser account reaches every staff route, including review and publication-adjacent ones. Separation of author and reviewer is enforced per-operation inside the services, not by the route matrix, so a superuser who is also an author still cannot review their own row — but that is a service-level guarantee this suite does not re-measure here.
- The alternate-backend case shows authentication succeeding for a deactivated account. Denial depends on every destination checking `is_active` itself; a new route that only checks permissions would serve content. No backend other than `AllowAllUsersModelBackend` was exercised, and no custom backend was written.
- Group grants are measured at the route level only. Nested groups, permission grants through custom managers, and row-level or object-level permissions (`has_perm(perm, obj)`) are out of scope; the routes take no object for the permission check.
- Routes are probed with the matrix's missing primary keys, so 404 is the normal authorized outcome for detail routes here; ADR 0201 covers existing rows.
- The stale-actor test proves the helper reloads. It does not make revocation durable: an unlocked recheck is a point-in-time read and ADR 0191 remains an open release blocker.
- Synthetic data on a development-only portal. No production readiness, threat model, independent review or real-data permission follows.

## Selected evidence

`daroobank/test_staff_grant_paths.py` (7 tests) passes on synthetic PostgreSQL in normal and optimized mode, together with the ADR 0200–0202 suites as a 29-test group.
