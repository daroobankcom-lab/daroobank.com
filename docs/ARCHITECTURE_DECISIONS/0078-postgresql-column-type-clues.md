# ADR 0078: PostgreSQL managed-column type clues

Status: development-only implementation, 24 November 2026; extends [ADR 0075](0075-postgresql-column-clues.md). [ADR 0089](0089-postgresql-migration-recorder-columns.md) adds selected migration-recorder columns, superseding that limitation below.

## Decision

For managed model fields whose Django PostgreSQL types are in a small explicit allowlist, compare a normalized expected type spelling to PostgreSQL `format_type` for the observed column, including varchar length and numeric precision/scale. Mismatches and unrecognized model types produce aggregate findings and `attention`; unsupported types are not silently treated as healthy. This is a comparison to current code metadata, not an independently trusted migration definition. An absent column is counted separately rather than as a type mismatch.

Auto-created many-to-many primary-key types are deliberately skipped and counted separately: in the current project, their runtime field metadata says integer while the historical auth migrations produce bigint. Model metadata alone cannot safely infer their intended physical type. The skip count does not itself make the report `attention`; it means those types were not checked. `django_migrations` columns are likewise outside the managed-model field check. The same query still checks selected column presence and nullability.

## Evidence and limits

Rolled-back PostgreSQL DDL tests change text/varchar length, numeric precision and timestamp time-zone type, and verify mismatches. Tests verify an unsupported model type fails closed and that an altered auto-created many-to-many primary-key type goes undetected but remains explicitly counted as skipped. This is not full schema comparison: defaults, collations, generation/identity/sequence settings, check expressions, all non-model columns, unsupported types, partitions, permissions and application data are not comprehensively verified. Later ADRs add selected generation, sequence and constant-check clues, but do not close those broader gaps. PostgreSQL type-format spellings and the allowlist may need review when versions or fields change. A report without selected issues is not a health certificate, production readiness, or a reason to auto-repair. Use only authorized synthetic development databases.
