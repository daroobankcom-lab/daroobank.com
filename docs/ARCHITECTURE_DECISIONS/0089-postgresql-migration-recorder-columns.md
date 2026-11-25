# ADR 0089: PostgreSQL migration-recorder column clues

Status: development-only implementation, 24 November 2026; extends [ADR 0075](0075-postgresql-column-clues.md) and [ADR 0078](0078-postgresql-column-type-clues.md). [ADR 0092](0092-postgresql-migration-recorder-primary-key.md) adds a recorder primary-key presence clue, superseding that limitation below.

## Decision

The existing read-only catalog statement includes Django's runtime `MigrationRecorder.Migration` metadata in the expected-column list even though that model is not in the installed app registry. Its concrete columns are checked for presence and nullability; supported types of non-primary fields are also compared. The recorder primary-key type is deliberately skipped and counted separately as `skipped_migration_pk_types`, since the physical type may depend on settings in effect when the table was first created. This skip is not by itself an attention condition. Existing auto-created many-to-many primary-key type skips remain separately counted.

An unchecked recorder key type can be incorrect without detection; the check does not verify the recorder's primary-key constraint, sequence, row contents, migration history, or full migration equivalence. Metadata from the current runtime is not an authenticated historical schema. Reports remain aggregate-only and no repair is performed. A clean result is not a production readiness certificate.

## Evidence

Tests on synthetic PostgreSQL 16 remove each recorder column, alter selected nullability and non-primary column type, and verify aggregate attention inside rolled-back transactions. A deliberately changed primary-key type still passes and increments the explicit skipped count. The normal migrated database and one-statement read-only inspection continue to pass. This does not validate real migration history or authorize production repair.
