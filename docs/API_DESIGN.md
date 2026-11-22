# API design

The local development slice implements `GET /api/v1/search/?q=...` and `GET /api/v1/products/{id}/` for the current package-like presentation model, returning published source-backed fields; search has a 30-result cap and no pagination; it returns no prices or clinical claims. The rest of this document is a proposed contract, not running endpoints. Implement OpenAPI 3.x alongside the first API and version compatible changes. All endpoints over HTTPS, UTF-8 JSON, stable opaque IDs, ISO-8601 UTC timestamps; local source dates and timezone are explicit. Public API exposes only approved, non-sensitive fields. Handle Persian and English input in Unicode, without leaking draft data.

## Read surface (`/api/v1`)

- `GET /search?q=&type=&cursor=&limit=` searches normalized, published catalog concepts with type and unambiguous package details. Prefix/fuzzy suggestions cannot decide identity.
- `GET /drugs/{id}` and `/drugs/{id}/monographs?audience=patient|professional`: approved version, references, review time and status.
- `GET /products/{id}` and `/packages/{id}`: identity and provenance; `GET /packages/{id}/prices?category=&unit=&cursor=`: approved publication history and source/verification/freshness. Unknown effective dates remain null.
- `GET /manufacturers/{id}`, `GET /safety-alerts/{id}` are gated by approved data. No interaction endpoint returns a safety result before licensed coverage and validation.

List responses: `{ "data": [], "page": { "next_cursor": null }, "meta": { "as_of": "..." } }`; a stable opaque cursor ties to ordering/filter, max page size documented in OpenAPI. Errors: `{ "error": { "code": "...", "message": "...", "request_id": "..." } }`; no stack trace or PHI. Locale formatting belongs to clients, but currency and unit are explicit.

## Internal/admin surface

Versioned authenticated endpoints can create drafts, attach evidence, list ingestion runs/candidates and approve/reject/withdraw after scope, role, state and separation-of-duties checks. Use optimistic concurrency (version/ETag), reason and transactional audit; idempotency keys for externally retried commands. Suggested routes: `POST /admin/candidates/{id}/decisions`, `/admin/content-versions/{id}/decisions`, `/admin/crawl-runs` and `GET /admin/crawl-runs/{id}`. These are design examples, not permission grants. Schedule changes and manual jobs require crawler-operator permission and an audit event; credentials may not be returned.

## Security and evolution

Target: public read rate limiting and admin sessions with secure, HttpOnly, SameSite cookies, CSRF protection and MFA. The current development-only staff session uses Django authentication and CSRF, but has no MFA or rate limiting and is disabled outside debug mode. Institutional/mobile API credentials use scoped short-lived tokens with revocation and rate/usage limits, selected after threat review; no secrets in client apps. No patient data in search queries, logs or public API responses. Compatibility: additive fields only in v1, document deprecations, contract tests and deliberate versioning for breaking changes. Python, mobile and future AI services use this contract rather than shared SQL. Consultation interfaces remain disabled and separately authorized; design them only after legal and privacy approval.

## Development endpoint example

`GET /api/v1/search/?q=...` returns `{"data": [...], "meta": {"limit": 30, "candidate_scan_limit": 150, "pagination_available": false}}`. Each result is a package-like presentation with name, manufacturer, strength, form, package description, optional IRC and source URL/name/verification timestamp. The same service backs the HTML search. Empty queries return no records. Only published, dated records with nonblank identity fields, a nonblank source name and a valid HTTPS URL without embedded credentials are returned. At most the first 150 SQL-matched records are inspected and at most 30 returned, so corrupt metadata or a large catalog can hide later matches; there is no completeness guarantee. This filter is **not** a real approval system. Search terms can appear in access logs; avoid personal health details and add production log redaction. API returns `no-store`, `no-referrer` and `noindex`; cursor pagination and OpenAPI are not implemented.

### Current presentation detail

`GET /api/v1/products/{id}/` returns `{"data": {...}}` with the same fields as one search result; IDs are current numeric database IDs, not yet stable opaque identifiers. A nonexistent, unpublished or ineligible record returns HTTP 404 with `{"error":{"code":"not_found","message":"Presentation not found."}}`. Both success and 404 are `no-store`, `no-referrer` and `noindex`. The HTML counterpart `/products/{id}/` is deliberately noindex and not in the sitemap. Neither endpoint exposes prices, clinical content, availability or review events. Do not interpret a published flag or verification timestamp as evidence of clinical approval, source rights, availability or correctness. Bulk writes can bypass model validation and create stale search projections; read-side checks reduce, not eliminate, risk. Source URLs are displayed to users and may include query strings: never store credentials, personal data or sensitive tokens in them. No source is fetched or rights verified by these endpoints.
