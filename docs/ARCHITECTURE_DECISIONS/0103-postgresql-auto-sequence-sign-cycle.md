# ADR 0103: selected PostgreSQL auto-sequence settings

Status: development-only implementation, 24 November 2026; extends [ADR 0093](0093-postgresql-auto-field-generation.md) and [ADR 0094](0094-postgresql-serial-default-clue.md).

## Decision

For supported managed Django auto fields, implicit many-to-many keys and the migration recorder, the existing single read-only catalog statement now counts owned sequences with a nonpositive increment, a minimum below one, or cycling enabled. Any count yields `attention` without returning names or values. This is a conservative clue: an intentionally configured sequence can be flagged even if it has not generated an invalid or repeated value. Missing ownership or generation continues to be reported by the existing separate check.

The check deliberately does not enforce an exact increment, start, maximum or cache size, compare migration intent, read the current sequence value, check privileges or compare values with existing rows. It cannot establish that IDs represent commit order or guarantee future inserts succeed; a valid-looking sequence can be rewound, exhausted or altered after inspection. The result observes one statement on one connection, is not a database health certificate and performs no repair. Use only authorized synthetic development databases.

## Evidence

Rolled-back PostgreSQL 16 tests flag cycling, negative increment and zero minimum on a selected model sequence, as well as cycling on an implicit many-to-many and migration-recorder sequence. A legacy owned sequence with an unusual quoted name is accepted when ordinary and flagged when cycling. A positive nonunit increment remains unflagged, illustrating the selected scope. A separate synthetic sequence with maximum two and cycling returns 1, 2, 1; another has ordinary selected settings but is rewound so an insert collides while the inspector still reports no selected issues. Command privacy, one-statement/read-only execution and clean-schema checks remain tested. These examples do not prove all sequence behavior, isolation schedules or PostgreSQL versions.
