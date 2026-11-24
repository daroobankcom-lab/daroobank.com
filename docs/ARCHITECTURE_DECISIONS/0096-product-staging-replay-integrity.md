# ADR 0096: product staging replay integrity

Status: development-only implementation, 24 November 2026; extends the product staging and receipt paths in [ADR 0055](0055-staging-conflict-boundary.md). [ADR 0097](0097-price-staging-replay-integrity.md) adds selected price-replay checks.

## Decision

When committed product CSV staging encounters an existing candidate, it locks and re-reads that row before counting it as a duplicate or writing a receipt item. Its source identity, exact submitted fields, fingerprint, IRC projection, rights-attestation flag and current recorder existence must match the selected expectations. A missing or inconsistent candidate raises generic `StagingConflict`, rolling back the entire stage and receipt transaction. Existing valid duplicates preserve the first recorder and still produce request-specific duplicate receipt items. Previews do not perform this write-path check.

Each duplicate can incur a row lock and account lookup; repeated rows are rechecked rather than cached, including after an internal callback. Locks last through the outermost transaction and can wait, deadlock or increase resource use; selected database conflicts are translated, with no automatic retry. The recorder lookup is not a lock or proof of historical identity. Matching fields/hash and asserted rights are not authenticity, permission to use the source or approval; later changes and direct SQL bypasses remain possible. This does not change price staging. Only synthetic data is appropriate.

## Evidence

Synthetic PostgreSQL tests cover valid duplicate receipts, modified payload, projection and attestation, missing recorder and disappeared row, full rollback when a later duplicate is corrupt, an internal callback mutation and private HTTP 409. Separate connections exercise a lock timeout, outer lock lifetime and a mutation committed after the initial lookup but before the locked re-read. These schedules do not establish full isolation, throughput at scale or absence of deadlocks.
