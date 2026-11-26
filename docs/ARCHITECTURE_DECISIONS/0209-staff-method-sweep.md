# ADR 0209: HTTP method sweep across every staff route

Status: **development-only synthetic evidence**, not a method-level security review or an approval. The `API and permissions` release gate remains open.

## Context

ADR 0200 and ADR 0205 exercised GET and POST. Four methods were never sent to most of the surface: HEAD, OPTIONS, PUT, PATCH and DELETE. An accepted `DELETE` on a staff route would be a way to destroy rows that no authorization suite would notice, and an `Allow` header that advertises a method the route does not implement is its own small leak.

## Decision

Add `daroobank/test_staff_method_sweep.py`, which sends GET, HEAD, OPTIONS, PUT, PATCH and DELETE to all 43 `staff_*` routes with real rows in place, for five account shapes, and pins the result. Route groups are taken from the view decorators and asserted at 27 `require_safe` / 9 `require_http_methods(['GET', 'POST'])` / 5 `require_POST` / 2 class-based authentication endpoints.

Recorded behavior:

| Probe | Result |
| --- | --- |
| PUT, PATCH, DELETE on all 41 matrix routes and on logout | **405 with an empty body** for every authenticated shape, and the method is never named in `Allow`; an anonymous request is redirected to the login before the method is considered |
| `Allow` on a rejected method | exactly `GET, HEAD` (27), `GET, POST` (9), `POST` (5), `POST, OPTIONS` (logout), `GET, POST, PUT, HEAD, OPTIONS` (login) — no route advertises a method it does not implement |
| HEAD | mirrors GET in status, `Cache-Control` and privacy headers with an empty body on the 27 `require_safe` routes and on the class-based login view; answers **405** on the 9 dual-method routes, the 5 POST-only routes and logout, because those decorators do not list HEAD |
| OPTIONS | 405 on every function-based route; 200 with an `Allow` header on the two class-based endpoints |
| method rejection vs authorization | an account with all 16 permissions and one with none receive a **byte-identical** response for every non-GET/HEAD method, so the method answer reveals nothing about access |
| PUT on the login form | accepted with 200: Django's `ProcessFormView.put` delegates to `post`. An empty submission creates no session |
| throttling of that PUT | measured in a separate `TransactionTestCase`, because the opt-in throttle is a no-op inside a test transaction: ten PUT attempts fill the shared window and a following POST with **correct** credentials returns 429 without authenticating, and ten POST attempts block a following PUT the same way |

Sweeping every route with every method for all five shapes leaves the fourteen write and audit model counts unchanged.

A red check confirmed detection: widening `catalog/quality_views.py::quality_irc` from `@require_safe` to `@require_http_methods(['GET', 'HEAD', 'DELETE'])` failed the destructive-method, `Allow` and method-parity assertions before the change was reverted.

## Limits and consequences

- **HEAD is not uniformly supported**, and this suite records that rather than fixing it. `require_http_methods(['GET', 'POST'])` omits HEAD, so nine form routes and five review routes answer 405 to it. Caches, link checkers and monitors that use HEAD will see a rejection on those routes; that is an availability detail, not an authorization one.
- The login form accepting PUT is Django framework behavior. CSRF protection covers unsafe methods including PUT (ADR 0207), and the throttle applies because `put` delegates to the overridden `post`; neither property is re-derived here beyond the two throttle tests.
- TRACE and CONNECT were not sent. The test client does not expose them and Django rejects unknown methods at the dispatcher, so no route-specific claim is made about them.
- Bodies for PUT and PATCH are an empty JSON document, so route-specific payload validation is not exercised; the upload, revise and review suites cover real submissions.
- The `Allow` expectations are pinned to today's decorators. Adding a method to any staff view requires updating them, which is intended.
- Synthetic data on a development-only portal. No production readiness, threat model, independent review or real-data permission follows.

## Selected evidence

`daroobank/test_staff_method_sweep.py` (9 tests, roughly 20 seconds) passes on synthetic PostgreSQL in normal and optimized mode.
