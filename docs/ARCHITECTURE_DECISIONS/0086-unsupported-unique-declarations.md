# ADR 0086: unsupported model unique declarations

Status: development-only implementation, 24 November 2026; extends [ADR 0073](0073-postgresql-unique-key-clues.md) and [ADR 0085](0085-postgresql-unique-null-semantics.md). [ADR 0087](0087-postgresql-unique-enforcement.md) adds a selected immediate-enforcement clue, superseding that limitation below.

## Decision

The development catalog command now counts current managed-model `UniqueConstraint` declarations it cannot compare and reports `attention` instead of silently excluding them from a clean result. The unsupported count includes expression, conditional, included-column, custom operator-class, explicit null-distinctness and explicitly deferrable declarations, as well as subclasses whose semantics may differ. These definitions are excluded from the selected simple-key check; names are not included in the report. This is a count of model metadata, not a database catalog finding. The catalog read is still a single statement, and no repair is performed.

The supported comparison still checks index presence, ordered key columns and selected validity/null semantics, not whether a matching unique index is backed by an immediate constraint, its precise operator classes or collation, nor complete migration equivalence. Current runtime metadata can diverge from migration history. Declared indexes, field-generated uniqueness and other constraint subclasses have their own coverage limitations. A clean report is neither a database integrity certificate nor production readiness.

## Evidence

Tests temporarily add several unsupported declarations to synthetic model metadata and verify that the command returns aggregate `attention` without names. A subclass and multiple simultaneous unsupported declarations are counted; a read-only transaction confirms the database inspection remains one statement. The ordinary migrated baseline continues to pass. The tests do not prove every possible Django or PostgreSQL constraint form is detected.
