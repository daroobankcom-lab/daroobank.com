# ADR 0202: public-route inventory and private-data leakage matrix

Status: **development-only synthetic evidence**, not a privacy review, a data classification decision or an approval to publish anything. The `API and permissions` release gate remains open.

## Context

ADR 0200–0201 cover the 41 `staff_*` routes. The other half of the exposure surface — the 12 non-staff routes — had per-feature tests but no single place that answered two questions: has a new public route been added without an explicit privacy expectation, and can private staff data reach a public response body? Both are exactly the failure modes that appear quietly, through a template change or a new serializer field, rather than loudly.

## Decision

Add `daroobank/test_public_route_privacy_matrix.py`. It:

1. **Inventories** every non-staff route from `get_resolver().reverse_dict` and asserts the declared list matches it in both directions, so adding or renaming a public route fails the suite until an explicit expectation exists.
2. **Creates one private row per marker** through the normal services — a source claim, a product candidate, a price candidate, a clinical draft, an ingredient draft and an import receipt — each carrying a distinctive `MARKER-…-7d41` string, plus one published presentation carrying its own marker.
3. **Probes all 17 route/query combinations** with an anonymous client and with a fully permitted staff client, asserting the declared status for both.
4. **Asserts marker absence**: none of the ten private markers may appear in any public response body. Three probes that put a marker in the query string are excluded from this check and covered separately, because the search page echoes its query back and echoing is not a leak.
5. **Keeps two positive controls** so the absence assertions cannot pass vacuously: a test that every marker is actually stored in the private model it came from and that the only published presentation is the marker one, and a test that searching for the published marker renders its public URL in HTML and returns its ID from the JSON API, while searching for a private candidate name or draft title returns the empty state and `[]`.
6. **Re-checks public privacy headers** (`no-store`, `noindex, follow`, `no-referrer`) on the five known public read routes for both account shapes, and covers the health probes in both settings states.

A red check confirmed detection: publishing one private marker as the presentation `source_name` failed four assertions before the change was reverted.

## Limits and consequences

- **Text matching, not classification.** The suite looks for ten literal markers in response bodies. Private data that was never marked, is derived rather than copied, is split across fields, appears in a header or in a URL fragment, or is encoded differently (escaped, transliterated, base64) is invisible to it.
- **One row per marker, one presentation published.** Bulk content, pagination, cursor traversal, projection repair output, error pages for malformed public requests and the OpenAPI schema's treatment of real fields are not enumerated.
- The `health_ready` expectation is `503 unavailable` because a `TestCase` wraps the probe in a transaction and the probe deliberately refuses inside one. That is a test-harness consequence, documented in the test; readiness behavior itself stays in `test_health_probes.py` with `TransactionTestCase`.
- Public read eligibility is enforced by read-side checks, not by this suite; a route that is authorized correctly but serves a stale index still fails nothing here.
- The inventory is name-based. A view registered under a `staff_*` name but reachable on a public path, or a public view mounted inside the staff prefix, would be classified by its name.
- Synthetic data on a development-only portal. No production readiness, threat model, independent review or real-data privacy conclusion follows.

## Selected evidence

`daroobank/test_public_route_privacy_matrix.py` (8 tests) passes on synthetic PostgreSQL in normal and optimized mode, including as part of the 544-test `daroobank` app suite.
