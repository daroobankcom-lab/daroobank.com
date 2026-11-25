# ADR 0160: bound selected source claim evidence-note reads

Status: development-only defensive reads for synthetic records; no schema, permissions or source-rights policy change.

## Decision

Private claim list/detail, date scan and same-URL related-claim summaries previously selected full `evidence_note` TextFields. These now select at most 1,001 characters, including each lookahead row, in their original SELECT. The supported field limit is 1,000 characters, so an extra character **proves** the stored note invalid regardless of its suffix. No prefix is sent to the complete claim validator or displayed: the deferred attribute is replaced with `None`, an oversize flag causes the existing invalid claim/date status, and the detail page hides the note explicitly. The source review scan uses the same helper. For notes at or below the limit, existing canonical validation and fingerprint comparisons remain in force. Detail-form errors and conflict refreshes also use the bounded query. Existing pagination, filters, current-account checks and read-only behavior remain unchanged.

This character-transfer bound does not bound database/decompression work, other fields, all entry points or writers. The invalid field does not establish anything about the authenticity, rights, integrity or completeness of the whole claim. Existing list metadata remains unverified. Counts and records are read separately, not as a snapshot.

## Evidence

Synthetic PostgreSQL tests cover the exact 1,000/1,001 boundaries, long whitespace, no partial validation, detail and form conflict refresh, date filtering and lookahead, related summaries, SQL selection and non-reflection. Existing source and review-scan tests and selected Chromium widths supplement these cases. Automated contrast results need manual review.
