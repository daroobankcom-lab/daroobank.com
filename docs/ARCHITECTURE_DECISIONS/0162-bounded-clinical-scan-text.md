# ADR 0162: bound clinical draft and parent text in selected scans

Status: development-only read defense for synthetic drafts; no schema, authorization or validation-rule change.

## Decision

The private draft queue and technical scan previously selected unrestricted `statement` and `change_reason` fields for each draft and its immediate parent, including the scan lookahead. The queries now transfer at most 4,001 and 1,001 characters respectively for each joined row. The helper replaces deferred fields before validation and marks any field over the transfer limit as uninspected; no partial text is sent to the full payload validator or rendered. The scan has a separate `oversized` category, applied after the bounded batch, and the queue shows a corresponding notice. Both suppress the detail link for these rows; this is not access control. The lookahead remains unclassified. Author and evidence checks are not performed for an oversized scan row. The review-history scan uses the same helper and keeps current comparison unknown.

Crucially, `valid_review_reason` currently accepts some strings longer than 1,000 raw characters if they consist of a valid short reason plus surrounding whitespace. Thus an oversized `change_reason` is **not** automatically inconsistent; even a fully valid stored reason must be shown as uninspected. This change does not tighten write validation or rewrite existing records. Statement length over 4,000 is itself invalid under current validation, but this combined defensive state remains conservative.

These are selected transfer limits, not limits on database work/decompression, exact bytes, direct detail requests, other fields, writers, or absent/future rows. Results are not a snapshot and do not establish clinical validity, rights, provenance or authenticity.

## Evidence

Synthetic PostgreSQL cases cover both current and joined parent, exact thresholds, a genuinely valid long-whitespace reason, no partial validation, SQL shape, filtering and sentinel continuation. Existing inspection/review tests and Chromium at four widths supplement these checks; automated contrast remains subject to manual review.
