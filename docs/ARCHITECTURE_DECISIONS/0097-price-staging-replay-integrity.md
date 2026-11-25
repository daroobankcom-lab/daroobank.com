# ADR 0097: price staging replay integrity

Status: development-only implementation, 24 November 2026; extends [ADR 0096](0096-product-staging-replay-integrity.md) to the price stage.

## Decision

Committed price staging locks and re-reads each existing duplicate before counting it or emitting a receipt item. It requires matching source identity, exact CSV fields and fingerprint, original amount/currency, converted amount, category, unit, dates and rights-attestation flag. If a recorder ID is present its current account must exist. A missing or inconsistent candidate raises generic `StagingConflict`, rolling back the whole stage and receipt. Legacy/CLI candidates with no recorder remain replayable and are not assigned one; they remain ineligible for review under existing rules. The existing first candidate's suggestion is not overwritten or validated against current product data; the receipt reflects the current request's bounded suggestion observation. Previews do not perform this write-path check.

Each duplicate adds a row lock and, when a recorder exists, an account lookup. Repeated rows are rechecked after internal callbacks. Locks persist through the outermost transaction and can block or deadlock; selected database conflicts are translated without automatic retry. A null recorder cannot prove whether a recorder was historically present; existing-account lookup is not an identity proof or account lock. Hash and attestation do not establish authenticity, source rights or price approval. Later changes and direct SQL bypasses remain possible. Only synthetic data is appropriate.

## Evidence

Synthetic PostgreSQL tests cover valid and actorless replays, modified payload and derived values, attestation and missing recorder, disappearance, rollback after a later bad duplicate, callback mutation, private HTTP conflict, lock timeout, outer lock lifetime and a concurrent mutation after the initial lookup. A one-off local synthetic probe with other tests running staged 1,000 repeated product rows in 3.76 seconds and 5,000 repeated price rows in 23.30 seconds, with one new candidate per batch and the remaining rows marked duplicate. These selected schedules and single-machine timings do not establish full isolation, production-scale throughput or absence of deadlocks.
