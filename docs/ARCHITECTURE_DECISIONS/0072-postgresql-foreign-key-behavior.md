# ADR 0072: PostgreSQL foreign-key behavior clues

Status: development-only implementation, 23 November 2026; extends [ADR 0070](0070-postgresql-catalog-clues.md).

## Decision

In the same read-only PostgreSQL catalog statement, also count actual foreign-key constraints matching the managed, model-declared single-column source and target pairs that are not `DEFERRABLE INITIALLY DEFERRED` or have database-level update/delete actions other than `NO ACTION`. These reflect the current Django-generated PostgreSQL schema conventions, not an independently verified migration specification. A nonzero count changes the command status to `attention`. Matching constraints are counted individually: an extra immediate or cascading constraint remains a finding even if another expected deferred constraint exists. Missing keys are reported separately, so absence is not double-counted as a behavior mismatch.

Django's ORM `on_delete` behavior is not the same as a PostgreSQL `ON DELETE` action; this diagnostic does not infer or validate the ORM policy. The output remains aggregate-only and the command performs no repair. Code metadata determines the expected pair, while the database determines the observed attributes; this cannot establish which side is correct if a migration or a deliberate database customization differs.

## Evidence and limits

On a disposable PostgreSQL database, tests replace a real expected FK with a non-deferrable FK and add duplicate immediate and cascading FKs inside rolled-back transactions. These defects are reported even if a valid duplicate exists. The normal migrated synthetic database has zero selected findings. These are selected structural clues, not full DDL equivalence: FK match type, supporting indexes, constraint names, authorization, other non-model/composite constraints, current transaction `SET CONSTRAINTS` state, data validity and production safety are not assessed. Schema changes in progress can produce transient observations. Restrict this tool to authorized synthetic development databases.
