# ADR 0095: source-claim replay integrity and locking

Status: development-only implementation, 24 November 2026; extends [ADR 0066](0066-source-claim-write-conflicts.md).

## Decision

When the source-claim service finds an existing source URL and fingerprint, it re-reads and locks the claim row in the same atomic boundary as creation. Replay succeeds only if the locked row passes current field/hash validation, its fields exactly equal the submitted validated values, and its recorded-by account currently exists. A missing, changed or invalid row or missing recorder returns a generic `ClaimConflict`; the existing private create view reports HTTP 409. A successful replay retains the original recorder. Selected PostgreSQL lock/deadlock/serialization errors remain translated after rollback, with no automatic retry.

The lock can block other writers until the outermost transaction ends. The recorder-existence lookup is not an account lock or proof of the historical recorder's identity or authority. A later change, direct SQL bypass, coherent rewriting of both data and hash, or surrounding-transaction commit failure is not prevented or fully detected. No source, evidence, rights or legal authorization is verified; only synthetic data is appropriate.

## Evidence

Synthetic PostgreSQL tests check corrupted payload, missing recorder lookup, disappearance after the initial lookup, exact field comparison, private HTTP conflict and unchanged normal replay. Real two-connection tests verify lock timeout, lock lifetime through an outer transaction, and a replay that reads before an uncommitted mutation but re-reads after its commit. These schedules do not prove all isolation behavior or absence of deadlocks.
