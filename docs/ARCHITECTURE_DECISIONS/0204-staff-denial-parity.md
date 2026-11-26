# ADR 0204: staff denial parity between existing and missing rows

Status: **development-only synthetic evidence**, not an authorization review or an approval. The `API and permissions` release gate remains open.

## Context

ADR 0201 established that an unauthorized account gets 403 for all 23 staff object routes whether or not the row exists — but it compared *status codes only* and listed the gap itself: response bodies, headers and timing were not compared. A route can return the same status and still leak existence through a longer body, an error message naming the object, or an extra header.

## Decision

Add `daroobank/test_staff_denial_parity.py`. It shares the row fixtures with ADR 0201 — `build_object_rows` was extracted from that suite so both compare the same real rows — and for every object route and every unauthorized account shape asserts that the response for an existing row and the response for a missing primary key are identical in **status, body bytes and all headers except `Date` and `Set-Cookie`**, which legitimately differ between two requests for reasons unrelated to authorization.

Two further comparisons:

* **Across shapes.** For each route, the denial received by an active non-staff account, a staff account with no permissions and a staff account holding other permissions must be byte-identical, so the reason for the denial cannot be read back either. At least two shapes are denied per route, asserted rather than assumed.
* **Against the authorized path.** A fully permitted account must *not* be denied for the same rows (200 on a GET, 400 on a POST-only review route with an empty form), otherwise identical denials would be trivially true.

Privacy headers are re-asserted on every denial (`no-store`, `noindex, nofollow`, `same-origin`), and probing all 23 routes twice with four account shapes must leave the fourteen write and audit model counts unchanged.

A red check confirmed detection: temporarily reordering `ingestion/staff_views.py::receipt_detail` so that an account with no visible kinds gets 404 for a missing receipt and 403 for an existing one failed two parity assertions before the change was reverted.

## Limits and consequences

- **Timing is deliberately not compared.** Wall-clock differences inside a test process measure the harness, not the application, and asserting on them would produce a flaky test that looks like a guarantee. This suite therefore makes no claim about timing channels; establishing one would need repeated measurements, a quiet host and a statistical threshold, none of which a unit test run provides.
- Parity is measured per route against one missing primary key (`999999999`) and one existing row. It does not compare across different kinds of missing input (malformed, negative, oversized, non-numeric identifiers), which several routes reject earlier with 400 or 404 by design.
- The comparison covers the 23 object routes. The 18 remaining staff routes take no primary key, so there is no existing/missing pair to compare; their coverage stays in ADR 0200.
- Headers are compared as rendered by the test client. Anything a real reverse proxy adds, removes or reorders downstream is outside this suite, as is any difference that appears only under HTTPS or with a real session store.
- Bodies are compared byte-for-byte, which is stronger than needed for leakage but will also fail on unrelated template churn; that is intended, since the expectation must be reviewed when a denial page changes.
- Synthetic data on a development-only portal. No production readiness, threat model, independent review or real-data permission follows.

## Selected evidence

`daroobank/test_staff_denial_parity.py` (6 tests) passes on synthetic PostgreSQL in normal and optimized mode, together with the ADR 0201 suite and the whole `ingestion` app as a 109-test group in optimized mode.
