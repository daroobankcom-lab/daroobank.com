# ADR 0046: recheck current fields for public search matches

Status: development implementation, 23 November 2026.

## Context and decision

The public search selects SQL candidates using the stored normalized `search_text` projection. Direct ORM updates, bulk operations or SQL can bypass model `save()` and leave that projection stale. A candidate could therefore be returned for a search term that no longer appears in the candidate's current displayed identity fields.

After the existing public eligibility checks and within the existing 150-candidate page limit, recompute normalized text from the fetched presentation's current search fields and include it only if the normalized query is a substring. The order, page and candidate limits, signed cursor scheme, SQL prefilter and detail endpoint remain unchanged. This is a query-specific check, not a requirement that the entire stored projection equal the current projection: a stale projection may still produce a valid current match. Existing model save and quality inspection behavior are unchanged.

## Evidence and limitations

Synthetic PostgreSQL tests bypass `save()` to make a stale positive, show both HTML and JSON omit it, and check that normal save refreshes the projection. They also show a stale negative remains missing, an unchanged current match remains available, Persian normalization is preserved, direct detail still works, and a full page of 150 stale matches advances to a subsequent valid result without revealing skipped names. The SQL prefilter can still omit valid matches when the projection is stale; this cannot find or fix those rows. There is no completeness guarantee, automatic repair or database-wide scan. PostgreSQL may scan more than the application candidate cap. The application performs additional normalization for at most 150 eligible candidates per request; no production performance guarantee is made.

The checks use each fetched row, not a transactionally stable catalog snapshot. Later updates, inter-page changes, bulk bypasses, different database collations and missing projections can still cause omissions, duplicates or stale results. Cursor anchors may be skipped candidates; the existing anchor validation and forward-only semantics remain. A match does not prove identity, availability, source rights, correctness, clinical approval or production readiness. Operators should use the bounded quality tools for synthetic diagnostics rather than infer that a result means a projection is correct.
