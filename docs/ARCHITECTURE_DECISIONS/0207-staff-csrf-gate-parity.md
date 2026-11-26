# ADR 0207: the CSRF gate on every staff route

Status: **development-only synthetic evidence**, not a CSRF review, a penetration test or an approval. The `API and permissions` release gate remains open.

## Context

Individual suites exercise CSRF on the routes they cover — upload, review, login, logout, clinical evidence. Nothing measured the gate across the whole staff surface, so nothing would have noticed a single `csrf_exempt`, a view that answered a token-less POST differently from its neighbours, or a rejection whose body varied with the account's permissions.

## Decision

Add `daroobank/test_staff_csrf_gate.py`, which probes all 43 `staff_*` routes (the 41 matrix routes plus login and logout) with real rows in place, using `Client(enforce_csrf_checks=True)`. The method classification is read from the view decorators rather than recorded from a run, and pinned at **5 POST-only** review routes, **9 dual-method** `require_http_methods(['GET', 'POST'])` form routes and **27 `require_safe`** routes; the suite also asserts that the five POST-only routes are exactly the routes the ADR 0200 matrix marks POST.

Recorded behavior:

| Probe | Result on all 43 routes |
| --- | --- |
| token-less POST, five account shapes (anonymous, non-staff, staff without permissions, view-only staff, full staff) | **one single canonical 403** — 215 requests, one distinct response in status, body and headers, with the staff privacy headers |
| POST with a CSRF cookie but no token, four authenticated shapes | one identical 403 per route and the same body for every shape, so the body reflects the client's cookie state and never its permissions |
| valid token with `Origin: https://evil.example` | identical 403 |
| mangled token, foreign token, empty token header | identical 403 — all five failure modes are indistinguishable |
| valid same-session token | the answer becomes route-specific exactly as the decorators say: **405** with an empty body and `Allow: GET, HEAD` on the 27 safe-only routes, **400** on the 5 POST-only review routes (the empty submission reaches form validation), a rendered form (**200/400**) on the 9 dual-method routes and login, **302** on logout |
| valid token, account without the route's permission | still **403** — the CSRF gate is not the authorization gate |

Probing every route with every variant and every shape, including the valid-token posts, leaves the fourteen write and audit model counts unchanged.

A red check confirmed detection: adding `@csrf_exempt` to `clinical/staff_views.py::review` failed four assertions — the canonical-rejection test, the cookie-parity test and the failure-mode parity test — before the change was reverted.

## Limits and consequences

- **The CSRF ordering is Django's, not this project's.** That the gate runs before authentication and before the method decorators is a framework property; the suite pins the consequence so a future `csrf_exempt`, a custom middleware reordering or a view-level `@requires_csrf_token` change is visible.
- The two rejection bodies differ between a client that holds a CSRF cookie and one that does not. That difference reveals the client's own prior navigation of the portal, not row existence or permissions; it is asserted rather than ignored, because a body that varied with the *account* would be a leak.
- Origin checking was exercised with a single hostile origin and no `Referer`. HTTPS-only referer validation, `CSRF_TRUSTED_ORIGINS` behavior, token rotation, session-bound token masking and double-submit cookie subtleties are not measured here; some are covered by the pricing and proxy suites.
- Valid-token posts send an empty body, so they prove the request reached form handling, not that a real submission succeeds. The revise, review, upload and evidence suites cover those paths, including their actor rechecks.
- The classification counts are pinned; adding a POST-capable staff route without updating the sets fails the suite, which is intended.
- Synthetic data on a development-only portal. No production readiness, threat model, independent review or real-data permission follows.

## Selected evidence

`daroobank/test_staff_csrf_gate.py` (7 tests) passes on synthetic PostgreSQL in normal and optimized mode.
