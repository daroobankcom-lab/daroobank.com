# ADR 0201: staff authorization against existing rows

Status: **development-only synthetic evidence**, not an authorization review or an approval. The `API and permissions` release gate remains open.

## Context

ADR 0200 probes all 41 staff routes with a missing primary key. That shows whether a permission check runs before anything else, but it cannot answer two questions that only real rows can answer: does an unauthorized account receive a *different* answer when the row exists — turning existence into an oracle — and does an authorized account actually reach and render the row, rather than being stopped by some later condition that also produces a non-403 status?

## Decision

Add `daroobank/test_staff_authorization_objects.py`. It builds one real synthetic row per object route in `setUpTestData` — a source claim through `record_claim`, a product candidate and an import receipt through the staging services, a price candidate through `stage_csv`, a clinical draft through `create_draft`, an identity chain through the existing `build` helper, and one published catalog presentation — then reuses the ADR 0200 route table and its `satisfies` helper for the 23 routes whose argument identifies a stored row. `staff_identity_create` is deliberately excluded: its argument is a kind, not an object, and it stays in the missing-key matrix.

Expectations are exact rather than permissive:

| Account shape | Expectation on each object route |
| --- | --- |
| anonymous | 302 to the staff login |
| active non-staff | 403 |
| active staff without the requirement | 403, **identical to the missing-row answer** |
| active staff with the requirement | 200 for a GET, 400 for a POST-only review route posting an empty form |

Authorized responses must also carry the staff privacy headers (`no-store`, `noindex, nofollow`). A final test probes all 23 routes with all five account shapes and asserts that fourteen write and audit models have exactly the same row counts afterwards, so the suite neither writes nor deletes.

## Limits and consequences

- The 400 on review routes comes from an intentionally empty form. It proves the request reached form handling for an existing row; it does not exercise a successful review, which the review suites cover separately.
- Existence-oracle coverage is limited to the status code. Response bodies, headers, timing and error text are not compared between authorized and unauthorized accounts, so a route that leaked existence through content rather than status would not fail here.
- One row per route, created through the normal services with a fully permitted author. Row-level ownership, per-object scoping beyond the import receipt kind filter, unpublished or inconsistent rows, oversized content paths and multi-database routing are not exercised.
- Requirements are declared by the same authors as the code; the suite enforces the declared matrix and does not judge whether each requirement is correct. Group grants, superuser shortcuts, alternate authentication backends and cross-request permission caching are out of scope.
- Synthetic data on a development-only portal. No production readiness, threat model, independent review or real-data permission follows from this.

## Selected evidence

`daroobank/test_staff_authorization_objects.py` (6 tests) passes on synthetic PostgreSQL in normal and optimized mode: 23 object routes × 5 account shapes, with per-route `subTest` labels, exact status expectations for authorized accounts, identical 403s for unauthorized accounts whether or not the row exists, and a before/after row-count assertion over fourteen models.
