# ADR 0069: product detail consistency gate

Status: development-only implementation, 23 November 2026; complements the price detail gate in [ADR 0065](0065-price-detail-payload-gate.md).

## Decision

The product-candidate detail already calculates a bounded comparison context and marks it unavailable when the observed current candidate's source, fields, payload hash, source-record ID or normalized IRC are inconsistent. Reuse that result to suppress the review form with an explicit warning in that request. The comparison logic and read-side query count are unchanged; the service still independently validates the candidate under its write lock. An invalid POST remains a 400, and a previously valid but stale POST returns the existing 409 and does not create a review.

Raw current fields and past review history remain visible to authorized staff. The checks do not establish source permission, identity, truth, historical actor identity or authenticity; a coherent rewrite and recomputed hash can pass. The current candidate, comparisons, accounts and receipts are separate reads, not a snapshot: a selected test changes the candidate after it was fetched and the in-flight response still exposes a form. A later request or writer can observe the inconsistency. This is a usability guard rather than a concurrency guarantee, confidentiality filter, safety validation or production readiness. Only synthetic data is suitable.

## Evidence and limits

Synthetic HTTP tests exercise inconsistent hash, field set, source URL, derived IRC and source ID, private headers, invalid input and stale submission, a coherent rewrite and a selected non-snapshot read. They do not cover all races or maliciously altered related rows. The existing comparison caps bound displayed rows, not database work or time.
