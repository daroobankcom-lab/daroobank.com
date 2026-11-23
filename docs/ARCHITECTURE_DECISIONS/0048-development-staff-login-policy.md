# ADR 0048: development staff login policy

Status: development implementation, 23 November 2026; the inactive-user backend edge was extended in [ADR 0060](0060-inactive-backend-staff-login.md).

## Context and decision

The development-only `/staff/login/` previously accepted valid credentials for an active nonstaff user and created a Django session; the destination then returned 403 because staff status is independently required. The staff authentication form now also rejects a nonstaff account after Django authentication. It uses the same invalid-login form error as bad credentials, and the Persian page displays one generic message. A staff account without any domain-specific permission may still sign in and see the permission-scoped workspace; destination permissions remain mandatory. This does not change Django's authentication backend or any other login mechanism.

## Evidence and limits

Synthetic CSRF-enforcing tests cover a valid nonstaff account with an explicit view permission, an inactive account, invalid credentials and an unknown username: each gets the same visible error and no new authenticated session. A staff account without domain permission can log in but receives 403 for the protected domain; a subsequent staff-status revocation is enforced on the next request. As in Django's default login behavior, submitting invalid credentials while already logged in does not log out or replace the existing session. The form is not an authorization boundary for other authentication paths or existing sessions: all staff routes must continue to check active/staff status and their specific permissions.

Generic visible errors do not establish constant-time authentication or prevent all user enumeration. There is no MFA, throttling, lockout, security audit, account provisioning, production identity assurance or permission-review process. The portal remains disabled outside the development configuration, and no real data or accounts should be used. This change is not a penetration test or production-security approval.
