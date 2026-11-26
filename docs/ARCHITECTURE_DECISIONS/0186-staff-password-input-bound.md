# ADR 0186: bound staff-login password input

Status: development-only staff form hardening; not a production authentication policy.

The staff authentication form rejects cleaned passwords longer than 4,096 Unicode characters before calling the authentication backend, using the same generic invalid-login error as a bad credential. Exactly 4,096 characters remain eligible. The bound does not truncate or alter passwords; it is a compatibility change for any existing synthetic account whose password exceeds that size. Disabled fields follow Django's server-side initial-value semantics. Existing duplicate-credential rejection precedes the backend too. If the opt-in synthetic IP throttle is enabled, the CSRF-valid POST still consumes one attempt.

This is a backend input bound after Django receives and parses the request, not an HTTP body limit, a maximum byte count, an account lockout, a timing-enumeration defense, MFA or resistance to distributed abuse. Other authentication forms and direct authentication calls are not covered. Configure actual request limits and independently reviewed abuse controls at the deployment boundary. No password should be logged; this change tests selected response paths but is not a complete logging audit. The staff portal remains debug-only and synthetic.
