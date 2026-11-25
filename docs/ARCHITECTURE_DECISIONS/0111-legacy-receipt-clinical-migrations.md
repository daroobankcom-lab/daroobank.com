# ADR 0111: selected pre-feature PostgreSQL migration fixtures

Status: development-only tests, 24 November 2026.

## Decision

Expand existing synthetic PostgreSQL migration coverage for two additive transitions: ingestion `0001` to `0002` and clinical `0001` to `0002`. Earlier receipt and clinical evidence tests already exercised small pre-feature fixtures; these additional tests check more fields, both receipt domains, and a linked draft chain. Before upgrading, create sample receipt summaries or a clinical draft chain and preliminary review using historical models. Check the existing field values, timestamps, actor links and selected JSON snapshots survive; the new manifest/reference tables remain empty, and pre-manifest receipts are classified as legacy. Separately check that the added version/reference constraints are present and reject selected invalid writes. A cleanup registered before the migration attempts to restore the test database's full migration graph even when setup fails. This adds no migration, application behavior, backfill or real data.

## Evidence and limits

The tests migrate backwards and forwards within a disposable PostgreSQL test database and use only synthetic fixtures. They exercise two sample receipts and a small draft chain/review, not every old dataset, later migration, partial deployment, concurrent application version, database privilege or external asset. The check for a named constraint and one rejected input does not prove its complete expression or all existing data. A cleanup can itself fail, and process termination can leave the database altered or orphaned; no production database may be used for these tests. This is not a rollback plan, proof of deployability, medical or legal validation, or a substitute for an authorized backup, restore rehearsal and version-compatible rollout.
