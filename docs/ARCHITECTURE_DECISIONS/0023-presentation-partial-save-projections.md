# ADR 0023: serialize partial presentation projection writes

Status: development implementation, 22 November 2026. Extends catalog quality inspection and price matching; no new production-readiness or data-verification claim.

## Problem and decision

`ProductPresentation.search_text` and `irc_normalized` are derived from identity fields. Previously, `save(update_fields=...)` loaded omitted fields without a lock and then wrote its projections. A concurrent partial save could change another identity field between those operations, leaving a projection inconsistent with the final stored fields. The deprecated Django 5.2 positional `update_fields` form also bypassed the override's detection, so source fields could be saved without their updated projections.

For nonempty partial saves of existing presentations, resolve the write database using Django's router, enter an atomic block on that database, acquire `SELECT FOR UPDATE` on the presentation, combine its locked stored fields with the fields explicitly updated, and recompute both projections before validating and writing. The lock is held until the enclosing transaction commits or rolls back, including when this runs within a larger transaction. The save override parses Django 5.2's deprecated positional parameters before making this decision; callers should use keyword arguments. Empty `update_fields`, including an empty iterable, remains a no-op. Full saves still compute projections from the full instance and follow ordinary model-save semantics. The quality inspector uses the same declared source-field tuple.

Synthetic PostgreSQL tests coordinate separate connections to demonstrate waiting partial saves, lock-timeout rollback, fresh reads after the first commit, stale instances, positional parameters, validation/write failures, no-op saves, and consistency with the pricing matcher. The concurrent test was first observed failing on the old implementation. No migration or automatic data rewrite is performed.

## Consequences and limits

Row locks introduce additional transaction/SELECT work and may block, time out, deadlock, or surface serialization errors; the application does not introduce a retry policy. This change is not a benchmark, cross-version/database guarantee or proof of every interleaving. PostgreSQL row locks cannot stop a subsequent `QuerySet.update`, `bulk_create`, `bulk_update`, raw SQL, migration historical models or other bypasses from writing inconsistent projections. Such writes and existing stale data remain possible; quality inspection offers bounded diagnostics, not complete detection or automatic repair. In-memory instances can remain stale and must be refreshed explicitly. A full save of an old instance can overwrite newer values under normal Django semantics.

The change does not protect absent catalog rows, prevent a concurrent matching duplicate, establish uniqueness, source rights, authenticity or clinical correctness, or alter price review's phantom-insert limitation in [ADR 0022](0022-price-review-concurrency.md). No publication, source access or production workflow is added. Test data are synthetic only.
