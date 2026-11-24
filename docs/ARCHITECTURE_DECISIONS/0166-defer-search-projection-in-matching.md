# ADR 0166: omit unused search text from selected matching reads

Status: development-only transfer optimization and defensive read, no schema, authorization or matching-rule change.

## Context and decision

The product comparison clues and price IRC matching queries selected all `ProductPresentation` fields, including `search_text`. That stored search projection is not used in their current-field validation, identity matching, displayed comparison or price-review fingerprint. A bypass-written unusually large projection could thus be transferred for each candidate, including the lookahead; matching and locked review can inspect up to 101 rows.

Both selected queries now defer `search_text`. Price matching still filters by `irc_normalized`, reads and validates the current identity fields, returns the same unique/ambiguous/unmatched statuses, and locks the same existing rows in the review writer. Product comparison still filters public candidates and keeps its 10-plus-one cap. Returned model instances have the field deferred: a future caller that accesses it will issue a separate query and may transfer the whole value, so this is not a global guarantee.

This change does not bound database filtering, decompression, other fields or other read/write paths; it does not repair a stale projection or prove identity, rights, source authorization, price correctness or clinical validity. Existing phantom and non-snapshot limitations remain.

## Evidence

Synthetic PostgreSQL tests place a large projection on matching rows and sentinels, check SQL selection and absence of deferred-field fetches across service, stage, detail, locked review and product comparison; they preserve match results, cap and row locks. Existing matching, cache and concurrency tests and opt-in Chromium complement these selected checks.
