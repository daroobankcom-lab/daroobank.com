# ADR 0063: projection-repair write conflict boundary

Status: development-only local tooling, 23 November 2026. Extends [ADR 0024](0024-synthetic-projection-repair.md).

## Decision

The default-database projection repair now uses the shared writer transaction boundary. If PostgreSQL reports lock timeout/not available (`55P03`), deadlock (`40P01`) or serialization failure (`40001`) inside that boundary, it rolls back and raises `ProjectionRepairError` with the database exception retained as its cause. The existing command turns that error into its generic `CommandError`, without intentionally displaying the token or driver details. Other database errors and programming errors still propagate. No retry or automatic new preview is added.

The boundary uses Django's default alias, as does the repair's fixed `DB_ALIAS`; an alias change would require revisiting this invariant. A surrounding outer transaction remains responsible for its own eventual commit; commit failures outside the boundary are not translated. Connection establishment, token validation and preview are also outside it. The local command and database are not protected by web authorization; debug mode and synthetic confirmation are not proof that data is synthetic.

## Evidence and limits

Synthetic tests exercise simulated selected SQLSTATEs after an update, checking savepoint rollback, preserved cause, reusable token and healthy outer transaction; an unselected SQLSTATE is not masked. A real PostgreSQL row lock and short lock timeout exercise both the service and command, and another selected interleaving checks the repair holds its row lock against a writer. The tests do not reproduce a real deadlock or serialization failure in this path and cannot establish all interleavings, database versions, successful outer commit, auditability or production safety. Commands may expose tokens in shell history or process listings. Use only isolated synthetic development data.
