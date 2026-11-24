# ADR 0079: post-restore synthetic sequence probes

Status: development-only implementation, 24 November 2026; extends [ADR 0077](0077-cross-domain-restore-drill.md).

## Decision

After restoring and verifying the selected synthetic graph in a fresh target database, exercise ordinary service writes across source claims/reviews, product and price candidates/reviews, receipts/items, clinical drafts/references/reviews, and identity package/review. Assert that these selected generated primary keys advance beyond the fixture's prior maxima. These writes are deliberately made only on the new target, never on the source database; strict target-name and DEBUG guards run before helper writes. Target destruction remains restricted to one successfully created random synthetic database.

For a negative control, the drill deliberately rewinds the target's synthetic source-claim ID sequence to an existing ID, confirms a new service insert fails with an integrity error, then sets that target sequence to the current maximum and confirms the probe can insert. This is a test of one selected sequence error, not a general sequence-repair procedure. PostgreSQL sequence state is nontransactional; the test's deliberately modified target is disposable. Never copy these mutations to a production or valuable database.

## Evidence and limits

The opt-in drill uses an actual `pg_dump`/`pg_restore`, fresh ORM subprocesses and PostgreSQL sequences, with tests rejecting non-target fixture writes before database access. This samples a subset of tables and service paths, not every sequence, alternate increment/cache configuration, concurrent allocation, data field, version, recovery scenario or production deployment. Advancing selected IDs after one restore does not establish full backup completeness, operational readiness, authenticity or source authorization. Continue to use only a separately authorized disposable cluster and synthetic data.
