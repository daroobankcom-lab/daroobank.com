# ADR 0099: manifest ordinal distinctness

Status: development-only implementation, 24 November 2026; extends [ADR 0004](0004-intake-row-manifest.md) and [ADR 0025](0025-manifest-consistency-inspection.md).

## Decision

A receipt manifest's structural check now compares the count of distinct ordinals with the recorded row count in its existing aggregate query. Together with total count, minimum 1 and maximum `rows`, this detects gaps hidden by duplicate ordinals even if the database's per-receipt uniqueness constraint is missing or bypassed. The normal database unique constraint remains essential and unchanged; the check does not replace schema inspection or repair damaged records. Both detail and bounded inspection stop showing rows on structural inconsistency.

The additional `COUNT(DISTINCT ...)` adds database work even though the application still runs one aggregate query; neither row output caps nor this check bound database scan time or memory. Receipt, aggregate and page reads are separate and not a stable snapshot. This is not proof of provenance, authenticity, source rights, valid chronology, current account existence, or intact schema. Other coherent modifications may pass. No automatic repair or production guarantee is implied.

## Evidence

On a synthetic PostgreSQL test database, tests temporarily drop the uniqueness constraint within a rolled-back transaction and replace ordinals `1,2,3` with `1,1,3`, preserving count, min, max and outcome totals. Product and price service reports and private staff pages now reject the structure; rollback restores the constraint and valid data. A seeded independent sorted-list oracle additionally checks 200 synthetic product/price layouts (100 contiguous and 100 with a duplicated position), using randomized item order, creation flags and price status totals. Existing tests exercise page limits, aggregate query count and ordinary staging. The tests do not cover every corruption or concurrent change.
