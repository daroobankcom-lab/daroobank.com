# ADR 0158: bound current candidate reads in detail and review writers

Status: development-only defensive changes for synthetic data; no schema, role, or normal-case comparison rule changes.

## Decision

Product and price staff detail GETs and the candidate read before a review POST now select `source_fields` through the same conditional, 65,536-character PostgreSQL JSON text bound used for related comparisons (ADR 0156). Invalid forms and conflict responses use a fresh bounded SELECT as well. Larger current candidates are explicitly uninspected rather than inconsistent: candidate fields, price values, current suggestion, review form, and related comparisons are withheld. Existing bounded review history may still be inspected, but its comparison with the current candidate is unknown. Other metadata can still be displayed as unverified. This supersedes ADR 0157's direct-detail limitation for this specific JSON field only; queue link suppression remains in place.

Each preliminary-review writer now reads the candidate with the bound **in its existing `SELECT FOR UPDATE`**, materializes the bounded value without a deferred fetch, retains existing authorization/account checks, and fails closed with a conflict before validation or creation if content is oversized. The lock order, review token checks and ordinary write semantics remain intact. This avoids relying on a potentially stale pre-POST display read. Bounded malformed JSON still follows the existing inconsistency path. Other staging/replay writers and endpoints are not covered.

The bound limits selected characters, not exact memory/wire usage, database work/decompression, other fields, absent/future rows, account races or all concurrent mutations. It does not establish authenticity, provenance, identity, rights, price accuracy or clinical validity. No production readiness is implied.

## Evidence

Synthetic PostgreSQL tests exercise GET, invalid form, actual conflict and conflict refresh, both writers, lock SELECT shape, oversized validator bypass, unchanged self-review denial and existing review-history comparison. A selected lock-timeout interleaving for each domain confirms a blocked writer observes committed oversized data and creates no review; other races remain possible. Existing review concurrency and normal/optimized regressions and opt-in Chromium checks are also run. Automated contrast results require manual review.
