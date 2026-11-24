# ADR 0112: historical presentation projection migration test

Status: development-only test, 24 November 2026.

## Decision and evidence

Use a Django historical-model migration-executor test on a disposable PostgreSQL test database for catalog `0001` to `0002`. Four synthetic pre-existing rows cover Persian digits, Arabic letter folding and joiner spacing, an NFKC expansion beyond the new field's 80-character limit, and an empty identifier. The test checks the backfilled values and compares every other historical field before and after migration. A separate injected exception after confirming the backfill writes checks that PostgreSQL rolls back the added column, old row changes and migration recorder entry, and that a subsequent clean upgrade succeeds. It registers migration-graph restoration before rollback, including on setup failure. This extends, rather than replaces, the existing candidate projection migration test.

## Limits

The migration intentionally stores an empty projection instead of truncating an overlong normalized identifier. An empty value can hide a search match; it is not a repair. The test uses a handful of synthetic examples and one injected failure point, not all Unicode, historical data or failure modes, and doesn't establish application validity, completeness, production upgrade safety, general rollback safety, performance, backups or concurrent-writer behavior. Migration tests alter schema and must run only against an authorized disposable database. Production migrations require an independent plan, representative data assessment, backup and tested recovery.
