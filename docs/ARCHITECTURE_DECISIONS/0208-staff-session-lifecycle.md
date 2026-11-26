# ADR 0208: session lifecycle across the staff surface

Status: **development-only synthetic evidence**, not a session-management review or an approval. ADR 0191 remains an open release blocker.

## Context

Login and logout are covered where they live, and the write services bind a session hash (ADR 0193–0198). What was not pinned is what an *ended* session means for the rest of the surface: whether every route, not just the one that was tested, refuses a logged-out, replayed, credential-changed or expired session.

## Decision

Add `daroobank/test_staff_session_lifecycle.py`. It drives four lifecycle events against one fully permitted staff account and then walks all 41 matrix routes, requiring a 302 to the staff login with the staff privacy headers on every one:

| Event | Recorded behavior |
| --- | --- |
| explicit logout (POST with a valid token) | 302 to the home page; the session **row is deleted**, not merely the cookie cleared; all 41 routes redirect; the login page stays reachable at 200 and logout stays POST-only at 405 |
| replaying the pre-logout cookie | the session row no longer exists and all 41 routes redirect to login |
| password changed behind the session's back | all 41 routes redirect for the old session; the account keeps `is_active`, `is_staff` and all 16 permissions; a fresh login with the new password works; replaying the old cookie redirects |
| session expiry forced into the past | all 41 routes redirect, and a revived client carrying the same cookie redirects too |

Every walk is preceded by a positive control asserting that the same session reached the workspace **and** a real source-claim detail page moments earlier, so a blanket redirect cannot pass vacuously. The walks use the matrix's declared route arguments, because an ended session is redirected before any argument is examined; the positive control uses a real row. The suite also pins the documented session settings (`SESSION_COOKIE_AGE == 3600`, browser-close expiry, `HttpOnly`, `SameSite=Lax`) and asserts that running all four walks leaves the fourteen write and audit model counts unchanged.

A red check confirmed detection: replacing `StaffLogoutView.post` with a bare redirect that never flushes the session failed the replay assertion and the logout walk before the change was reverted.

## Limits and consequences

- **This is the password field only.** The hash binding covers `password`; deactivating and reactivating an account, changing permissions or groups, removing a backend or rotating a session key without touching the password does not end an existing session. That gap is ADR 0191 and it is still open.
- Expiry is forced by writing `expire_date` directly. Real clock skew, session-store backends other than the database one, and `SESSION_SAVE_EVERY_REQUEST` behavior are not exercised.
- Logout is driven through the view. A server-side session purge, database restore or cache flush is not simulated, and no administrative "log out everywhere" control exists to test.
- The replay case reuses a cookie value in a new test client. It does not model cookie theft over a network, session fixation at login, or a cookie scoped to another host.
- The walks assert the redirect target and privacy headers, not the content of every page a valid session would see; per-route content expectations live in ADR 0200–0207.
- Synthetic data on a development-only portal. No production readiness, threat model, independent review or real-data permission follows.

## Selected evidence

`daroobank/test_staff_session_lifecycle.py` (7 tests) passes on synthetic PostgreSQL in normal and optimized mode, together with the ADR 0207 suite as a 14-test group.
