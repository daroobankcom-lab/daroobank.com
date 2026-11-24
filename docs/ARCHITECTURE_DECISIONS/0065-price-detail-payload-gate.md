# ADR 0065: price detail payload consistency gate

Status: development-only, 23 November 2026. Follows the local command check in [ADR 0062](0062-price-cli-payload-check.md). The subsequent selected display suppression is recorded in [ADR 0128](0128-suppress-inconsistent-detail-values.md).

## Decision

The staff price detail uses the existing price payload/derived-value check before computing a fresh suggestion. If the check fails, show the fixed invalid status and a warning, do not run the suggestion lookup, and do not present a new review form. A stale POST remains subject to the independent locked write-side integrity check; it returns a conflict and records nothing when this check fails. Existing review history and selected raw fields remain visible to authorized staff and may contain untrusted content. The warning does not provide confidentiality or guarantee data safety. At this decision the price queue continued to show its historical match status without checking full payload consistency; ADR 0129 adds a page-local consistency check for displayed identity while keeping that historical status.

A consistent payload is not authenticated: a privileged writer may change structured values and recompute the unkeyed digest, and the source URL is not covered by that digest. Consistency is not review eligibility, permission, source rights, clinical validation or price approval. Current values may change immediately after the read. No records, historical decisions, receipt outcomes or public prices are altered by the detail check. Only synthetic data is suitable.

The queue and detail no longer join the stored historical suggested-product object because neither uses its fields. Detail still independently queries a current suggestion after payload validation. This is a query/data-minimization change, not a proof that the stored reference is intact or historically meaningful.

## Evidence

Synthetic tests reproduce a current suggestion and review form for a changed derived amount, then check that the invalid state suppresses both without attempting current matching, and that a stale POST records no review. They cover changed hash, JSON and source URL, a normal payload, privacy headers, and SQL inspection showing candidate queries no longer join the historical product. A test changes the candidate after its fetch and observes that the in-flight page may still offer a stale suggestion and form, while a later read detects the inconsistency. This is not a concurrency snapshot, full Unicode check, production authorization or provenance audit.
