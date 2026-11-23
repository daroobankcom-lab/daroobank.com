# ADR 0060: inactive users returned by an authentication backend

Status: development-only, 23 November 2026. This narrows an edge case in [ADR 0048](0048-development-staff-login-policy.md).

## Problem and decision

The configured default Django authentication backend ordinarily rejects inactive accounts before the portal's form sees them. An explicitly permissive backend can instead return an inactive user. Django's base `AuthenticationForm` then rejects login, but its cached user remains accessible through `get_user()` and its validation error differs from the generic bad-credentials error. Existing `LoginView` calls `get_user()` only for a valid form, so this was not a demonstrated HTTP login bypass.

The development staff form now clears the cached user and raises the generic invalid-login error if the base form rejects the authenticated user. Its existing nonstaff rejection remains generic and clears the cache. The form still accepts an active staff user; destination permissions remain independently enforced. This does not change Django's global authentication form or configure a new backend.

## Evidence and limits

Synthetic tests override settings with Django's `AllowAllUsersModelBackend` to exercise the otherwise unconfigured edge: direct form validation for inactive, nonstaff, wrong-password and active staff accounts; generic errors and `get_user()`; private HTTP responses without an established inactive session; and permission enforcement even for an already-authenticated inactive user. The pre-change form test reproduced a cached inactive account. Existing tests cover the actual default backend.

A custom backend can have additional behaviors not represented by this test. Clearing a rejected form's cache does not enforce authorization outside the portal's own views, prevent already-created sessions, add MFA, rate limiting, monitoring, credential-stuffing protection or production security. Real deployments require a separate authentication and authorization review.
