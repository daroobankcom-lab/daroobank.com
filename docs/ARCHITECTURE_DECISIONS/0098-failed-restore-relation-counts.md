# ADR 0098: selected failed-restore relation counts

Status: development-only implementation, 24 November 2026; extends [ADR 0043](0043-synthetic-postgresql-restore-drill.md).

## Decision

The opt-in synthetic restore drill compares aggregate counts of selected `public` relation kinds in the newly created target before and after its one truncated-archive, single-transaction restore attempt. In addition to the existing package-table absence check, any changed selected count fails the drill. A successful full restore must change the selected aggregate. Counts are read from PostgreSQL catalogs and do not emit object names. All writes and eventual removal concern only the separately created, disposable target.

This is not a complete schema comparison. Equal counts can hide object replacement; non-`public` schemas, functions, types, extensions, permissions, table data and many other changes are not covered. The result is specific to one synthetic archive and corruption. It does not certify production rollback, backup quality or recovery readiness.

## Evidence

A real PostgreSQL 16 drill creates and drops synthetic target-only canary tables. Adding one changes the aggregate, while replacing it with a differently named table intentionally leaves the aggregate unchanged; cleanup restores the baseline. The truncated restore returns an error and preserves those selected counts, and the valid restore changes them and passes the existing ORM and sequence checks. No production repair procedure is implied.
