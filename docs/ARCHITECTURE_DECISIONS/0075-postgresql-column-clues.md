# ADR 0075: PostgreSQL managed-column clues

Status: development-only implementation, 23 November 2026; extends [ADR 0070](0070-postgresql-catalog-clues.md). [ADR 0078](0078-postgresql-column-type-clues.md) later adds selected column-type comparisons and supersedes that specific limitation below.

## Decision

The same read-only catalog statement now counts expected local concrete columns from managed model metadata, including automatic many-to-many tables, that are missing, dropped, or on a missing/non-table relation. It separately counts existing columns whose PostgreSQL `attnotnull` differs from the current model field's `null` setting. A mismatch produces `attention`; the command still reports only aggregate counts and performs no repair. A missing table can produce both a table and multiple column findings. `django_migrations` is not represented as a managed model here, so its columns are not checked.

The comparison follows the connection search path and compares current code metadata to a single observed catalog snapshot, not the applied migration graph. Schema transitions can legitimately cause transient warnings, and deliberate database-only constraints may differ from model metadata; investigate rather than automatically altering a database.

## Evidence and limits

Synthetic, rolled-back PostgreSQL DDL tests drop a real column and change nullability in both directions. A separate regression changes an existing column's type while preserving its name and nullability and demonstrates that the inspection does not detect the type mismatch. It does not compare column types, defaults, generated expressions, collations, data, complete constraints, indexes, partitions, privileges, backups or production safety. Only authorized synthetic development databases are appropriate.
