# ADR 0155: bound candidate JSON selected for receipt inspection

Status: development-only defensive reads for synthetic data; no schema, writes or authorization change.

## Decision

Private receipt detail (25 items) and the manifest inspector (50 items plus one lookahead) joined entire candidate `source_fields` JSON. Bypassed writes can make this content much larger than accepted intake. Both selected joined queries now defer that JSON and use a SQL CASE to transfer it only when its PostgreSQL textual representation is at most 65,536 characters. The bounded value comes from the same joined row; the deferred field is populated before comparison and cannot trigger a later lazy fetch. A longer value is not passed to the validator, is not called inconsistent, and is shown as an uninspected oversized candidate with its details and link hidden. The inspector offers a separate `oversized` filter, applied only to the current batch, and does not classify its lookahead. Missing joins and bounded malformed JSON remain inconsistent under existing rules. Per-request candidate-validation caching and per-item comparisons remain unchanged.

This is not a limit on database read, decompression or expression work, exact wire bytes, receipt structure aggregation, other candidate fields or other endpoints; SELECT processing can still be expensive. It does not establish file provenance, safety, identity, integrity against an attacker or clinical validity. Counts and rows are not a snapshot, and cursor pages can change across requests.

## Evidence

Synthetic PostgreSQL cases check both domains, exact textual thresholds, malformed JSON, missing joined candidates, conditional SQL shape, filtered continuation and the 51st-row lookahead. Existing manifest caching, pagination, privacy and concurrency tests remain applicable. Chromium checks an oversized price receipt at four selected widths; automated contrast findings still need manual review.
