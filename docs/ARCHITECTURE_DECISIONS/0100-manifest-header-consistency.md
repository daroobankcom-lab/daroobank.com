# ADR 0100: manifest header consistency

Status: development-only implementation, 24 November 2026; extends [ADR 0099](0099-manifest-ordinal-distinctness.md).

## Decision

Before querying manifest items, the version-1 structural check validates the current receipt header: known domain, integer nonnegative totals, domain row limit, created-plus-duplicates total, and either null product suggestion counts or nonnegative price suggestion counts summing to rows. The row limits reuse the CSV import limits, matching the current database constraints. Bad headers return `invalid` without an item aggregate. Legacy receipts retain the `legacy` result and are not reconstructed. The database constraints are unchanged and remain the primary enforcement; this is a selected defensive read check if a constraint is missing or bypassed.

Validation cannot detect an internally consistent fabrication and does not validate actor, source rights, provenance, chronology, or database schema. It adds no lock or snapshot; receipt and item observations can become stale. It does not guarantee bounded database execution time or detect every malformed database value, and it does not repair records. Header metadata remains visible to the authorized receipt-detail viewer even when manifest rows are hidden.

## Evidence

Synthetic tests exercise invalid headers and ensure the aggregate is not queried, including product/price row bounds, invalid counts, and legacy behavior. A PostgreSQL test transaction temporarily drops the relevant check constraint and sets a product suggestion count, which previously passed the manifest check; product scan and detail then show the generic structure warning without displaying row details. Rollback restores the constraint and original data. Existing domain permission, bounded scan, ordinary manifest and query-count tests pass. This does not cover every corruption or concurrent writer.
