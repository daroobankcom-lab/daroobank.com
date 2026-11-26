# ADR 0189: privacy headers on selected early errors

Status: selected Django response-header hardening, not a complete privacy or logging policy.

The existing outer known-path privacy middleware previously applied its staff/public policies only to redirects. A non-debug HTTP request with an invalid Host could instead be rejected by `SecurityMiddleware` before inner privacy middleware ran, producing a 400 without those policies. The same outer middleware now applies the existing staff policy to known `/staff` paths and the existing public-read policy to its explicitly recognized search, API, OpenAPI and numeric product paths regardless of response status. The historical middleware class name remains unchanged. Inner resolved-view policies still cover their previous cases.

Synthetic fresh-process tests exercise selected non-debug invalid-host 400 responses and confirm an unrelated route is not newly covered. Existing redirect, CSRF, disabled-staff, health and CSP tests remain relevant. This does not cover every URL, intermediary or static response; matching a path is not an authorization control. Headers cannot remove URLs, query strings or invalid Host values from server/proxy/security logs, and `no-store` is not a substitute for deployment review. Debug and production must not receive sensitive data without separate authorization and controls.
