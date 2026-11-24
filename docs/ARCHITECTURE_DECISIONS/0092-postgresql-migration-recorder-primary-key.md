# ADR 0092: PostgreSQL migration-recorder primary-key clue

Status: development-only implementation, 24 November 2026; extends [ADR 0089](0089-postgresql-migration-recorder-columns.md).

## Decision

The inspector adds Django's runtime migration-recorder primary key to its existing selected unique-key expectations, requiring a matching immediate, valid, ready, live primary B-tree index with the selected key, operator and collation properties. A standalone unique index is not sufficient for a primary-key expectation. Missing findings are aggregate-only and cause `attention`; no repair is performed.

The recorder primary-key field's physical type remains intentionally skipped and counted, since its historical creation can differ from current metadata. The inspection still does not validate the sequence, default expression, recorder rows or migration history, and is not complete schema equivalence or production readiness.

## Evidence

On synthetic PostgreSQL 16, rolled-back DDL removes the recorder primary-key constraint and substitutes a same-column standalone unique index; the inspector flags it without emitting object names. The normal migrated database remains clean. This does not validate all corruption cases or authorize production repair.
