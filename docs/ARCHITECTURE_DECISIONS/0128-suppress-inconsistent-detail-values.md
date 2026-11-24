# ADR 0128: suppress inconsistent identity and amount panels in private details

Status: development-only presentation change, 24 November 2026.

## Decision

The product and price detail pages already gate comparison, current suggestions and review forms on their respective candidate-consistency checks. They previously still rendered the candidate's current identity fields and price amount in the detail panels when those checks failed. To reduce confusion during preliminary triage, the product detail now replaces the identity panel with a fixed warning if `comparison.available` is false. The price detail replaces its identity and amount panels with a fixed warning if `payload_invalid` is true. The existing generic invalid status, lack of review form and locked write-side recheck remain. GET and the existing invalid/stale POST response paths use the same rendering.

Consistent candidates retain the existing fields; consistency does not prove source authenticity, correct identity, rights, a price or clinical approval. The checks are not transactional snapshots: data can change after fetch. This is not a confidentiality or comprehensive sanitization mechanism: other private pages (including the queues), source metadata, previous review history, logs, context objects and direct database access may still contain or display untrusted values. The database can still transfer oversized JSON before the check. No candidate, review or publication is changed by rendering.

## Evidence

Synthetic tests reproduce inconsistent product/price identity and amount canaries in the previous detail output, then check their suppression on selected GET and HEAD responses and on 400/409 review responses, privacy headers, no review creation, and the normal consistent path. Existing consistency, concurrency, permission and escaping tests remain relevant. These examples do not cover every related panel, historical payload, race, browser or operator interpretation. Do not use real or sensitive data in the development portal.
