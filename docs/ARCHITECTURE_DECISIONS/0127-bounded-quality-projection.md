# ADR 0127: bound the projection returned to catalog-quality inspection

Status: development-only diagnostic change, 24 November 2026.

## Context and decision

The read-only catalog-quality inspector limits each page to 50 records plus a lookahead, but previously fetched the complete unbounded `search_text` column for every row before examining it. Now its single query selects at most 65,537 characters of each projection. If the extra character is present, the row receives the fixed `oversized_search_projection` warning and its `public_filter` is `unknown`. The inspector does not make search/IRC consistency, source-hygiene, public eligibility or duplicate-IRC claims for that row; this is conservative, not a determination that the product is invalid. The separate IRC inspector remains available as an independent bounded clue. This 65,536-character inspection threshold is not a model constraint or the 8192-character repair threshold.

For a projection at or below the threshold, its full text and the prior checks are retained. The inspector can still report `invalid_text` for a control in the returned prefix or another examined field. It cannot detect controls solely in an omitted suffix and must not interpret the absence of that warning as safety. No data are changed. The CLI exposes the new fixed issue code and the private page shows its Persian label.

## Evidence and limitations

Synthetic tests exercise a million-character projection, the character boundary, controls at the edge, selected SQL and no-echo/read-only behavior, plus the permission-scoped page and command. Existing quality, IRC and repair tests remain relevant. The output meaning changes for oversized rows and callers consuming issue codes must handle the new warning and `unknown` status.

The limit applies to the projection returned to Python, not PostgreSQL's storage, substring work, decompression, query time, all other fields, all callers or every configuration. It does not make the report a complete scan, snapshot, security audit, verification or production monitoring system. Unknown rows need separately authorized investigation, not automatic repair.
