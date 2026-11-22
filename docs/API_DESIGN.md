# API design

Proposed contract, not running endpoints. Implement OpenAPI 3.x alongside the first API and version compatible changes. All endpoints over HTTPS, UTF-8 JSON, stable opaque IDs, ISO-8601 UTC timestamps; local source dates and timezone are explicit. Public API exposes only approved, non-sensitive fields. Handle Persian and English input in Unicode, without leaking draft data.

## Read surface (`/api/v1`)

- `GET /search?q=&type=&cursor=&limit=` searches normalized, published catalog concepts with type and unambiguous package details. Prefix/fuzzy suggestions cannot decide identity.
- `GET /drugs/{id}` and `/drugs/{id}/monographs?audience=patient|professional`: approved version, references, review time and status.
- `GET /products/{id}` and `/packages/{id}`: identity and provenance; `GET /packages/{id}/prices?category=&unit=&cursor=`: approved publication history and source/verification/freshness. Unknown effective dates remain null.
- `GET /manufacturers/{id}`, `GET /safety-alerts/{id}` are gated by approved data. No interaction endpoint returns a safety result before licensed coverage and validation.

List responses: `{ "data": [], "page": { "next_cursor": null }, "meta": { "as_of": "..." } }`; a stable opaque cursor ties to ordering/filter, max page size documented in OpenAPI. Errors: `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`; no stack trace or PHI. Locale formatting belongs to clients, but currency and unit are explicit.

## Internal/admin surface

Versioned authenticated endpoints can create drafts, attach evidence, list ingestion runs/candidates and approve/reject/withdraw after scope, role, state and separation-of-duties checks. Use optimistic concurrency (version/ETag), reason and transactional audit; idempotency keys for externally retried commands. Suggested routes: `POST /admin/candidates/{id}/decisions`, `/admin/content-versions/{id}/decisions`, `/admin/crawl-runs` and `GET /admin/crawl-runs/{id}`. These are design examples, not permission grants. Schedule changes and manual jobs require crawler-operator permission and an audit event; credentials may not be returned.

## Security and evolution

Public read rate limiting; admin sessions use secure, HttpOnly, SameSite cookies, CSRF protection and MFA. Institutional/mobile API credentials use scoped short-lived tokens with revocation and rate/usage limits, selected after threat review; no secrets in client apps. No patient data in search queries, logs or public API responses. Compatibility: additive fields only in v1, document deprecations, contract tests and deliberate versioning for breaking changes. Python, mobile and future AI services use this contract rather than shared SQL. Consultation interfaces remain disabled and separately authorized; design them only after legal and privacy approval.
