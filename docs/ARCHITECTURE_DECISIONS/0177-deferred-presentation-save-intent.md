# ADR 0177: preserve deferred presentation save intent before projection reads

Status: development data-integrity fix; no schema, publication, provenance or approval change.

## Context

Django normally treats `save()` on a deferred model loaded from the same database as a partial update of fields already loaded or assigned. `ProductPresentation.save()` previously accessed deferred attributes to build and validate projections before delegating to Django. That made those attributes appear loaded, so an implicit partial save could instead update the whole row. In a synthetic PostgreSQL race, an unrelated `strength` update committed while this save waited, and the deferred save overwrote it with the previous value.

## Decision

Before accessing deferred attributes, the model now determines Django's same-database implicit partial-update field set using the initially loaded/assigned concrete fields. It sends that set through the existing locked prospective-row validation and projection rebuild, including both derived projections in the update. Explicit `update_fields` remains authoritative. A missing row raises the existing partial-save `DoesNotExist` rather than recreating it; signals receive the selected update fields and projections. The original signal-bearing object may still have other fields deferred or stale.

As in Django's inference, a force insert, a save to a different database alias, or a deferred instance with no loaded non-primary-key fields does not acquire this implicit partial intent. Ordinary fully loaded saves and `QuerySet.update`, bulk operations, direct SQL, later writes and stale fields already loaded/assigned remain outside this guarantee. Other writers must cooperate with the row lock; this is not full concurrency, audit, authorization or publication safety. This change does not establish clinical correctness or data authenticity.

## Evidence

Synthetic PostgreSQL tests reproduce the lost update on the old implementation, coordinate a real blocked writer with `pg_blocking_pids`, and verify the committed unrelated field and regenerated projection survive. Tests also cover implicit field selection and signals, assigned deferred fields, invalid current data, no-op empty updates, force update, missing row and selected cross-database/primary-key-only fallback behavior. Normal/optimized regressions and repeated selected locking schedules supplement them; they do not prove all interleavings.
