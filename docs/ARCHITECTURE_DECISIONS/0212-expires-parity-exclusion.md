# 0212 — Exclude the per-second `Expires` stamp from parity comparisons

Date: 2026-11-26
Status: accepted
Fixes: the CI failure of `daroobank.test_staff_method_sweep.StaffMethodSweepTests.test_the_method_gate_runs_before_authorization`
Suites touched: `daroobank/test_staff_denial_parity.py` (shared `VOLATILE_HEADERS`),
`daroobank/test_staff_method_sweep.py` (new guard test)

## Context

CI run `45832496897` for commit `bad5999` failed on exactly one test: the ADR 0209
assertion that a wrong-method answer is byte-identical for a fully permitted account
and for accounts with no permissions. The same suite had passed locally many times,
had passed CI on `b870959` (`45828594577`), and a full 1 515-test regression on
`bad5999` passed locally at seed `464201` while that CI run was failing. So the
failure was not caused by the two suites added in `0134e26`/`bad5999`; it was a
latent timing dependency in the comparison itself.

The cause is visible in the response headers. `LoginView.dispatch` and
`LogoutView.dispatch` are wrapped in `never_cache`, which stamps `Expires` with
**second** granularity. Measured directly:

```
/staff/logout/  GET      405  Expires: Thu, 26 Nov 2026 14:01:20 GMT
/staff/logout/  GET      405  Expires: Thu, 26 Nov 2026 14:01:21 GMT   -> comparable() == False
/staff/logout/  OPTIONS  200  Expires: Thu, 26 Nov 2026 14:01:21 GMT
/staff/logout/  OPTIONS  200  Expires: Thu, 26 Nov 2026 14:01:22 GMT   -> comparable() == False
/staff/login/   OPTIONS  200  Expires: Thu, 26 Nov 2026 14:01:22 GMT
/staff/login/   OPTIONS  200  Expires: Thu, 26 Nov 2026 14:01:23 GMT   -> comparable() == False
```

`comparable()` in `daroobank/test_staff_denial_parity.py` — shared by the ADR 0204,
0205, 0206, 0207 and 0209 suites — excluded only `Date` and `Set-Cookie`. Two
identical requests to logout that happened to straddle a second boundary therefore
compared unequal, and the parity assertion failed for a reason that has nothing to do
with authorization. A fast local machine almost always stays inside one second; a
loaded CI runner almost always does not.

Scope measured across the surface: of the 43 staff routes, **only `staff_login` and
`staff_logout` emit `Expires`**. The 41 function-view routes do not, because
`never_cache` decorates the two class-based views and nothing else, and CSRF
rejections are produced by middleware before any view runs — which is why the ADR 0207
suites, which compare token-less POSTs across all 43 routes, were never affected.

## Decision

Add `expires` to `VOLATILE_HEADERS`, the single exclusion set behind `comparable()`,
with a comment recording why. All five parity suites inherit the fix.

Add a deterministic guard in `daroobank/test_staff_method_sweep.py`
(`test_the_comparison_ignores_the_per_second_expires_stamp`) so the exclusion cannot
be silently reverted and cannot go vacuous: for each of the two auth endpoints it
takes an OPTIONS answer, asserts `Expires` is really present, sleeps 1.1 s, takes the
same answer again, asserts the two `Expires` values **differ**, and asserts the two
responses are still `comparable()`-equal. Cost: about 2.2 s; the suite is now 10
tests, roughly 22 s.

### Alternatives rejected

- **Skip `staff_logout` in the parity test.** It would remove the flake by removing
  the guarantee: logout is one of the 43 routes, and "a method rejection reveals
  nothing about the account" is exactly the property being pinned.
- **Stop the views stamping `Expires`.** `never_cache` on the authentication endpoints
  is deliberate production behavior; changing it to make a test comparison convenient
  would weaken caching protection for no security gain.
- **Normalize the header value before comparing.** Same effect as excluding it, but it
  hides the reason and invites someone to "fix" the normalization later.
- **Freeze the clock.** No time-mocking dependency is pinned in this project, and
  patching the clock inside a suite that also measures real request flow costs more
  than the guarantee it buys.

## Consequences

- Parity comparisons now ignore `Expires` on every route, so a route that began
  emitting a *wrong* `Expires` would not be caught by the parity suites. Caching
  behavior stays pinned elsewhere: ADR 0210 requires `Cache-Control: private,
  no-store, max-age=0` and `Pragma: no-cache` with exact values on all 1 204 swept
  staff responses, and requires every header name to belong to a closed inventory.
- The exclusion is a **test-side** decision. No production code changed; nothing about
  what the application sends was altered.
- The earlier green CI runs for `b870959` and `0134e26` were timing luck, not
  evidence that the comparison was sound. Any suite that compares responses from a
  `never_cache`-decorated view inherits this hazard, and the guard test now covers the
  two endpoints that exist today.

## Limitations

- The guard test depends on a wall-clock `sleep(1.1)`; on a machine whose clock jumps
  it could produce a false failure. It asserts the observed difference explicitly, so
  a false failure would name `Expires` rather than look like an authorization leak.
- Only `Expires` was added. Any other per-request or per-second header a future view
  might emit (an `ETag`, a `Last-Modified`, a request-id) would have to be added the
  same way; the failure mode is a flaky parity test, not a wrong guarantee.
