# ADR 0130: label unknown candidate statuses explicitly

Status: development-only defensive display change, 24 November 2026.

## Decision

The product and price queue templates previously treated an unrecognized latest-review decision as no review, and the price queue treated an unrecognized stored match status as unmatched. Their detail history templates also labeled an unknown review decision as `defer`. Although current database checks reject these values, a missing or bypassed constraint could make these labels misleading.

The selected queues and detail histories now render a fixed invalid-status label for unknown non-null values. Normal recognized labels remain unchanged; a `None` latest decision still means no review in the queue and does not distinguish a missing row from a corrupted null decision. Existing status filters and aggregate counts are unchanged; invalid values may appear only under the unfiltered list. Unknown status text itself is not echoed in these selected places.

This change does not validate or suppress other review history content, prevent new reviews, authenticate the data, repair rows, inspect every status in other domains, or make the reads a snapshot. Database constraints remain primary. A privileged writer or a missing schema object can still create corruption; source rights, medical validity and price approval are separate concerns.

## Evidence and limitations

A synthetic PostgreSQL test temporarily drops only the three named relevant checks inside a guarded isolated test transaction, writes selected invalid values, and verifies fixed queue/detail labels, selected privacy headers and no echo of status canaries. A separate savepoint test confirms the selected checks return after rollback. This is not proof of production-safe schema mutation; never run such mutations on real data. Other constraints, nulls, review history values, races, crashes and operator interpretation are not fully covered.
