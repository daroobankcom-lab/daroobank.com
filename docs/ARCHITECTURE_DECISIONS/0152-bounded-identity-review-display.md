# ADR 0152: bound identity-package review display content

Status: development-only staff display with synthetic data, not production hardening. Extends ADRs 0032 and 0148; review writers, permissions, locks and schema are unchanged.

## Decision

The private identity-package history and package-revision page previously selected complete JSON `graph_snapshot` and text `reason` for up to 25 reviews plus one lookahead, or the single latest review for revision. They now use the existing bounded review helper with an allowlisted snapshot field: at most 65,536 characters of PostgreSQL textual JSON per graph and at most 1,001 reason characters. Each rendered row is materialized from the same SELECT; original deferred fields are replaced to prevent accidental lazy reads. A graph or reason over its bound yields `content_oversized`; both attributes are suppressed, no partial graph is structurally classified, and a fixed message says the content was not examined and comparison is unknown. The lookahead row is bounded but not classified. The latest row's ID remains the optimistic review token; missing accounts and oversized rows do not hide it.

An oversized latest review makes the correction page conservatively unavailable, without declaring the uninspected review inconsistent. The existing writer independently re-reads and validates; the visible page's separate read is not a snapshot or a lock. Review submission and writer semantics are not changed. Current graph, links, other fields, other endpoints and write-time reads remained outside these bounds at this decision; ADR 0153 subsequently bounds the selected latest-review fields in the identity writer lock read.

## Evidence and limits

Synthetic PostgreSQL tests exercise million-character graph/reason, reason alone, thresholds, malformed smaller JSON, missing reviewer, valid neighbor, cursor/lookahead, no partial classification, SQL selection, privacy, invalid POST, no write and conflict behavior. Chromium checks the fixed label, non-reflection and disabled revision form at four selected widths. Automated accessibility checks are incomplete and some contrast items require manual review.

The limits count PostgreSQL textual JSON characters, not exact wire bytes, full process memory, DB work or time. Casting, reading and decompressing the original value may be expensive, and multiple near-limit values may still be significant. Oversized is not a judgment about consistency, authority, provenance, historical identity, approval or authenticity; no content was inspected. Other routes and direct SQL bypass this display policy, and concurrent changes remain possible.
