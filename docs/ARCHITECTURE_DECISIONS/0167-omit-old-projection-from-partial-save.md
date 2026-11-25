# ADR 0167: omit discarded search projection from partial-save lock

Status: development-only defensive transfer change, no schema or validation-rule change.

## Decision

A partial `ProductPresentation.save(update_fields=...)` serializes on the stored row, constructs and validates the prospective row, and recalculates `search_text` and `irc_normalized` from current identity fields. It previously fetched the entire stored `search_text` only to overwrite it during that recalculation. The locked SELECT now defers that field, and the prospective-row copy explicitly skips it before assigning the new projection. The rest of the actual persisted row is still used for validation, and the same row lock, signal-bearing instance, transaction and update fields remain in place.

The change covers this particular locked read, not the initial read by a caller, a later deferred-field access, full saves, bulk/direct writes, other fields or database work/decompression. It neither verifies the product nor makes the public catalog production-ready.

## Evidence

Synthetic PostgreSQL tests use a bypass-written oversized old projection and assert that the locked SELECT excludes it and does not lazily retrieve it. They check recalculation from current fields, rejected invalid prospective rows with no signal/write, an explicit projection-only update, and a waiting writer that observes a concurrently committed identity change. Existing partial validation, signal and concurrency tests continue to run in normal and optimized Python modes. These are selected cases, not a proof of all concurrent schedules.
