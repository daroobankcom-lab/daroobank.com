# ADR 0077: cross-domain synthetic PostgreSQL restore drill

Status: development-only implementation, 23 November 2026; extends [ADR 0043](0043-synthetic-postgresql-restore-drill.md).

## Decision

Expand the opt-in disposable PostgreSQL restore drill beyond its existing identity package/review graph. Before dumping, exercise synthetic source claim/review, product and price staging/review, duplicate receipt items, and a clinical draft with supplementary reference and review. After restoring the archive into a newly created independent database, run Django checks, migration-state check and the read-only selected catalog inspection, then verify selected cross-domain records, actor/reviewer links, candidate hashes, receipt/item links and evidence fingerprints from a fresh ORM process.

The fixture helper checks development DEBUG, PostgreSQL and strict random restore-test database name patterns before touching data; creation also requires dedicated restore settings. These are extra guardrails, not proof the server is disposable. Continue to use only a separately authorized disposable cluster with synthetic data. Existing collision and cleanup checks remain; archives are private but unencrypted, and failures or abrupt termination can leave resources requiring careful manual inspection.

## Evidence and limits

The opt-in drill runs an actual `pg_dump`/single-transaction `pg_restore`, rejects one truncated archive and verifies the selected restored relationships. A separate test deliberately corrupts a synthetic receipt item and clinical evidence snapshot and confirms the verifier fails. Guard tests reject non-PostgreSQL, non-DEBUG, wrong names and missing isolated-settings marker before fixture writes. The drill is still only a selected sample: it does not prove all fields, all models, migration history correctness, source rights, durability, backup security, off-host recovery, recovery time or production readiness. Hash equality and consistency do not prove authenticity. No real source data or patient data is used.
