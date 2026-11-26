# ADR 0206: query-parameter parity on staff routes

Status: **development-only synthetic evidence**, not an authorization review or an approval. The `API and permissions` release gate remains open.

## Context

ADR 0204–0205 covered the identifier in the path and the HTTP method. Query parameters are the remaining caller-controlled input on staff routes: the receipt kind filter, pagination, manifest scan offsets and categories, search terms and date-window arguments. Nine shapes were chosen — the empty case, both legitimate receipt kinds, an HTML-injection attempt, negative and absurd pagination, a non-numeric scan offset with a NUL category, a 5,000-character term, and malformed date-window values — and asked of all 41 staff routes.

## Decision

Add `daroobank/test_staff_query_parity.py`, which builds one receipt per kind with a distinct source name and URL (the list renders the name, the detail renders the URL, so a cross-kind leak is visible in both) and asserts:

| Question | Expectation |
| --- | --- |
| Can a query parameter change an unauthorized denial? | No. For four unauthorized account shapes × 41 routes × 9 variants the response is one identical 403 in status, body and headers. |
| Can a query parameter cause a server error for an authorized account? | No 500 for any of 9 variants on any route the account satisfies; every response keeps `no-store` and `noindex, nofollow`. |
| Can a query parameter change the anonymous answer? | No: 302 to the staff login for all 41 × 9. |
| Can a filter widen an account beyond its own kind? | No. A product-only account listing `?kind=product` sees its own receipt's name and never the price receipt's name or URL; `?kind=price` is a 403 whose body contains neither; the price receipt by primary key is answered **byte-identically to a receipt that does not exist**, on both the detail and the manifest inspection routes. |
| Does any of it write? | No: fourteen write and audit model counts are unchanged after every shape probes every route with every variant. |

One query-driven 403 is legitimate and is pinned as the only one: `staff_import_receipts?kind=price` for an account whose visible kinds exclude price. The test allows a 403 from an authorized account only on that route with that parameter, and asserts the denial body does not contain the filtered kind's name.

A red check confirmed detection: dropping the `kind__in=kinds` filter from `ingestion/staff_views.py::receipt_detail` made the cross-kind receipt render for the product-only account and failed the parity assertion before the change was reverted.

## Limits and consequences

- **Nine variants are a sample, not fuzzing.** No generator, dictionary or coverage measurement is involved, so absence of failures is not evidence that query handling is robust — only that these nine shapes behave as recorded.
- The suite asserts statuses, headers and selected marker absence. It does not validate that each route *interprets* its parameters correctly; pagination bounds, scan limits and window arithmetic have their own suites, and a route that silently ignored a parameter would pass here.
- A 500 would fail the suite, but so would any new legitimate status; the allowed set (200/302/400/404/405/409) is pinned and must be reviewed if a route starts answering differently.
- Query parameters are appended raw for POST routes, so encoding of hostile values on that path is the test client's, not a browser's or a proxy's.
- Markers are synthetic strings. Real source names and URLs are out of scope, and the comparison says nothing about whether a permitted account *should* see the content it receives.
- Timing is not compared, for the reason given in ADR 0204.
- Synthetic data on a development-only portal. No production readiness, threat model, independent review or real-data permission follows.

## Selected evidence

`daroobank/test_staff_query_parity.py` (5 tests, roughly 35 seconds) passes on synthetic PostgreSQL in normal and optimized mode.
