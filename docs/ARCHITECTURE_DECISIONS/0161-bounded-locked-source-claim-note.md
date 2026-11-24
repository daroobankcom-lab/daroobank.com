# ADR 0161: bound source claim evidence note under writer locks

Status: development-only synthetic-data defense; no schema or authorization policy changes.

## Decision

Source-claim replay and preliminary review previously selected the full evidence-note TextField before checking it. The replay pre-lookup now selects only an existing primary key, and the authoritative duplicate reread and review writer both use the original `SELECT FOR UPDATE` with the 1,001-character prefix helper from ADR 0160. A prefix longer than 1,000 proves the stored value violates the existing field limit; the writer rejects with its existing conflict rather than passing partial data to the full-record validator or creating a review. Existing self-review denial remains before the review conflict. Normal values, data equality checks, missing-account handling, lock order, optimistic token and rollback behavior remain unchanged. New claims still use fully validated input. Test injection hooks follow the new pre-lookup helper.

The read and lock are in the same SELECT, so a pre-lock lookup is not relied on for content. This bounds selected text, not database/decompression work, other fields, other endpoints, account races, absent/future rows or later bypass writes. It does not establish rights, authenticity or clinical validity.

## Evidence

Synthetic PostgreSQL tests cover query shape, no partial validation, self-review denial, HTTP conflicts, rollback and both replay/review lock interleavings with an oversized mutation. Existing write-conflict and latest-review lock suites and a selected Chromium conflict screen are also exercised. This is not comprehensive concurrency or accessibility verification.
