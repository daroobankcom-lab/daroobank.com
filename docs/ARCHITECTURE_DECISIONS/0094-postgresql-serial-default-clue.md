# ADR 0094: PostgreSQL legacy serial default clue

Status: development-only implementation, 24 November 2026; extends [ADR 0093](0093-postgresql-auto-field-generation.md).

## Decision

For supported auto fields using a non-identity legacy serial-style definition, the read-only inspector now requires an owned sequence and a canonical deparsed `nextval` default referencing that sequence. It also rejects default expressions with recorded function dependencies, preventing a selected search-path-shadowed custom `nextval` from satisfying the text check. The existing `BY DEFAULT` identity check is unchanged. Missing clues cause aggregate `attention`; no default, sequence or data is modified.

This is a conservative textual/catalog clue, not proof of semantic equivalence, function safety, permissions, sequence state or insert success. Equivalent noncanonical expressions can be flagged; expression rendering, search paths and catalog behavior may differ in other environments. Current sequence values, increments, bounds and ownership outside the selected fields remain unchecked. A clean report does not prove recovery or production readiness.

## Evidence

Rolled-back PostgreSQL 16 DDL tests accept a standard owned serial sequence, including a sequence name with quotes and a search-path variation; they reject a constant default, a different sequence, absent ownership/default and a shadowed user function. A semantically equivalent `nextval(...) + 0` default is intentionally flagged. These are selected synthetic cases, not exhaustive PostgreSQL expression or security analysis.
