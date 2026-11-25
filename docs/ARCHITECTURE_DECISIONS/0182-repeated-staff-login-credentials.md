# ADR 0182: reject repeated staff-login credentials

Status: narrow development-only form hardening, not account-security or production approval.

Django single-value form fields ordinarily select the last repeated value. The development staff authentication form now rejects repeated enabled `username` or `password` POST values before calling any authentication backend, including identical repetitions and prefixed forms. It uses the existing generic invalid-login error and clears any form user cache. Disabled fields retain Django's server-initial behavior. Single-valued credentials and the existing session, CSRF, staff and safe-redirect checks are unchanged. When the optional synthetic throttle is enabled, the CSRF-accepted request consumes one attempt before the form is checked.

This does not prevent every parameter-pollution scenario: `next`, CSRF tokens, other routes and direct authentication calls are outside this change. It does not validate proxy behavior, avoid all timing differences, protect server logs, replace MFA or make the debug-only portal suitable for production. As before, the username may be displayed in the form on error; passwords are not rendered by the standard widget.

Synthetic tests cover repeated conflicting and identical credentials, prefixed/disabled fields, URL-encoded and multipart CSRF-protected requests, no authentication backend call, no password echo or new session, existing-session preservation, and integration with one throttle attempt. They do not establish complete authentication security.
