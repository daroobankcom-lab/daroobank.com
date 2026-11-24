# ADR 0149: bound source and clinical review-scan content

Status: development-only defensive inspection with synthetic tests. Extends ADRs 0147–0148 without changing writes, permissions or retention.

## Decision

The per-claim source and per-draft clinical review scans now select at most 65,536 characters of PostgreSQL textual JSON per snapshot and 1,001 reason characters, in the same SELECT, using the shared bounded-query and materialization helpers also used by candidate scans and recent-history pages. The original columns remain deferred until replaced from bounded annotations, so classifiers cannot trigger a lazy fetch. Exceeding either threshold yields `oversized`, `unknown` comparison, a fixed label and a filter; no partial content is classified. Existing smaller valid, legacy and malformed cases keep their normal classification. The lookahead row is bounded as well. The scan still reads at most 50 IDs plus one sentinel in ascending ID order; filtering is local to that batch and can result in an empty page with a continuation. The scans do not return reasons or snapshots to the page.

## Evidence and limits

Synthetic PostgreSQL tests cover both domains, huge snapshots and reasons, exact character boundaries, small malformed JSON including JSON null, non-disclosure, absence of classification of oversized data, SQL shape, no writes, filtered empty pages, a large lookahead row and continuation. Chromium covers the fixed filter and labels plus recent-history warnings with synthetic large rows at four selected widths. All existing source and clinical scan regressions remain relevant. See also ADR 0148.

The parent claim, clinical draft and its parent, other fields and endpoints are outside these limits. The bounds are on characters, not wire bytes, memory, database work or time; PostgreSQL may decompress or process the full large value. Separate reads are not a consistent snapshot; changing data or deletion can affect pages. Oversized means not inspected, not inconsistent, valid, authentic, authorized or clinically approved. Account existence, provenance, legal rights, clinical validation and complete history are not verified. The thresholds are not production sizing or schema constraints. Tests and automated accessibility checks cannot certify a production system or all browser/device behavior; some axe contrast results require manual review.
