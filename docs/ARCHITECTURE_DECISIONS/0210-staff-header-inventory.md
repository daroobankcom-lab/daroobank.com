# 0210 — Every staff response carries exactly one pinned header inventory

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_staff_header_inventory.py` (6 tests, ~17 s)
Companion: 0200 (authorization matrix), 0202 (public route privacy), 0205 (identifier
parity), 0207 (CSRF gate), 0209 (method sweep)

## Context

ADR 0200 asserted that a *denied* staff request carries `Cache-Control: private,
no-store, max-age=0`, `X-Robots-Tag: noindex, nofollow` and `Referrer-Policy:
same-origin`. ADR 0202 asserted the same for public routes that must not leak
staff links. Both read the header set as a property of the *denial path*.

The real property is narrower than that framing suggests and worth pinning on its
own. The seven headers come from three different places in `MIDDLEWARE`:
`ContentSecurityPolicyMiddleware` (first in the chain) sets `Content-Security-Policy`
with `setdefault`; `SecurityMiddleware` sets `X-Content-Type-Options: nosniff` and
`Cross-Origin-Opener-Policy: same-origin`; and `StaffPrivacyHeadersMiddleware`
applies `_staff_headers` — `Cache-Control`, `Pragma`, `X-Robots-Tag: noindex,
nofollow` (note: public routes get `noindex, follow`) and `Referrer-Policy` — to
every response whose path matches `_is_staff_path`. So the set is a property of the
staff **area**, not of any outcome, and it depends on three middlewares all running
and none of them being short-circuited. ADR 0209 then showed that a route answers as
many as six different methods with four different status codes — 200, 302, 403,
405 — and each of those is a separate chance to ship a response that skips one.

Two things could break it silently. A route that raises before the middleware runs
would be caught by nothing else here. And a *new* header appearing — a
`Set-Cookie` on a 405, an `ETag`, a `Content-Security-Policy-Report-Only`, a
`Strict-Transport-Security` with a wrong max-age — is exactly the kind of drift
that only shows up in a production capture. This suite makes the header surface
itself the assertion.

## Decision

Sweep **43 staff routes × 7 methods × 4 accounts** (anonymous, no permissions,
view-only, full) = 1 204 requests and pin the complete header inventory.

**Seven pinned headers, on every single response regardless of route, method,
account or status:**

| Header | Value |
| --- | --- |
| `Cache-Control` | `private, no-store, max-age=0` |
| `Pragma` | `no-cache` |
| `X-Robots-Tag` | `noindex, nofollow` |
| `Referrer-Policy` | `same-origin` |
| `X-Content-Type-Options` | `nosniff` |
| `Cross-Origin-Opener-Policy` | `same-origin` |
| `Content-Security-Policy` | the exact `DEVELOPMENT_CSP` from `daroobank/middleware.py` |

The first four come from `_staff_headers`, the last three from `SecurityMiddleware`
and `ContentSecurityPolicyMiddleware`.

**Nine further headers may appear, but only in a pinned shape** (`VARIABLE_HEADERS`:
`Allow`, `Content-Type`, `Content-Disposition`, `Location`, `Content-Length`,
`Date`, `Expires`, `Vary`, `Set-Cookie`):

- `Allow` — one of the five exact values ADR 0209 recorded, and only on a
  response whose status is 405 or a 200 OPTIONS answer. The 200-with-`Allow`
  set is exactly `{staff_login, staff_logout}`, the two class-based endpoints;
  every one of the 43 routes must refuse at least one swept method, so the 405
  branch covers the whole surface.
- `Content-Type` — `text/html; charset=utf-8` on every 200 except the two sample
  downloads (`staff_product_sample`, `staff_price_sample`), which are the only
  routes that may emit `text/csv; charset=utf-8`. Non-200 responses are HTML
  too: a redirect, a denial or a method rejection never carries a document type.
  Both sample routes must really render 200 for the fully permitted account, so
  the CSV branch cannot be satisfied vacuously.
- `Content-Disposition` — the two sample routes only, each with its exact
  synthetic filename (`product_candidates.synthetic.csv`,
  `price_candidates.synthetic.csv`).
- `Location` — a 302 always points at the staff login or, for logout, at `home`,
  and the part of the target after the first `/staff/` contains no `://`, so a
  `next` parameter cannot turn the redirect into an off-host one.

**Any other header name fails the suite.** The tolerated set is exactly
`PINNED_HEADERS ∪ VARIABLE_HEADERS`; there is no escape hatch for
deployment-dependent headers (see Limitations). Every header name the sweep
observes must also belong to a route in the resolver-derived inventory, and all
seven pinned headers must actually have been seen, so neither assertion can pass
on an empty sweep.

Statuses are constrained but not counted: every response must be in
`{200, 302, 400, 403, 404, 405, 409}` — no 5xx and no permanent redirect — and
the sweep must really reach 200, 403 and 405. The exact per-route status
distribution is deliberately **not** asserted here: ADR 0200, 0205 and 0209 own
those numbers, and duplicating them would make every future behavioral change
fail in three suites at once.

Finally, the sweep writes nothing: the 14 counted write and audit models hold the
same row counts before and after all 1 204 requests.

## Red check

Removing the single line `response['Pragma'] = 'no-cache'` from `_staff_headers`
in `daroobank/middleware.py` makes the suite report **1 205 failures**: one for
each of the 1 204 swept responses, plus the vacuity guard in
`test_no_response_carries_a_header_outside_the_inventory`, which notices that a
pinned header was never observed at all. The line was restored from a backup and
`git diff --stat` is empty afterwards.

## Limitations

- **`X-Frame-Options` and `Strict-Transport-Security` are absent, not exempt.**
  The synthetic settings inherit `daroobank/settings.py`, where `DEBUG` is `True`
  (from `DAROOBANK_DEBUG`); `XFrameOptionsMiddleware` is inserted into `MIDDLEWARE`
  only `if not DEBUG`, `SECURE_SSL_REDIRECT` is set only in that same branch, and
  `SECURE_HSTS_SECONDS` is `0 if DEBUG`, so `SecurityMiddleware` emits no HSTS
  header either. `CSRF_COOKIE_SECURE` and `SESSION_COOKIE_SECURE` are off for the
  same reason, which is why `Set-Cookie` is tolerated without a `Secure` attribute
  assertion here. Both names are therefore *not* in `VARIABLE_HEADERS`: running this
  suite against a non-debug configuration fails the closed-set assertion on purpose,
  forcing the inventory to be reviewed rather than silently widening. The non-debug
  behavior — `X-Frame-Options: DENY` plus `Content-Security-Policy: frame-ancestors
  'none'` — is covered by `daroobank/test_nondebug_frame_guard.py`, which boots a
  real server subprocess.
- The sweep uses the Django test client, which does not send `TRACE` or
  `CONNECT`; those two methods are unobserved here (same gap as ADR 0209).
- `Content-Security-Policy` is pinned to `DEVELOPMENT_CSP` **by import**, not by
  literal. If the production CSP diverges from the development one, this suite
  keeps passing while the deployed header changes. That divergence is a settings
  concern, not a middleware concern, and is not tested here.
- Header *order* is not asserted. HTTP treats repeated headers as unordered
  except for a few (notably `Set-Cookie`), and the test client preserves order
  only incidentally.
- Only the seven pinned values are compared exactly. A future header that must
  vary per request (an `ETag`, a `Last-Modified`) would have to be added to
  `VARIABLE_HEADERS` — the closed-set assertion is designed to force that
  decision to be explicit.
