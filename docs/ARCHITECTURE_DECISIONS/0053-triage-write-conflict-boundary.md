# ADR 0053: translate selected triage write conflicts after rollback

Status: development-only, 23 November 2026. This changes error reporting, not the locking or review guarantees in ADRs 0049–0052.

## Decision

Wrap the product-candidate, price, source and clinical preliminary review writers in a shared atomic boundary. After rollback of the writer's transaction or nested savepoint, translate PostgreSQL SQLSTATE `55P03` (lock not available/timeout), `40P01` (deadlock) and `40001` (serialization failure) into each domain's existing review conflict with a generic retry message. Existing web handlers render a private 409 without the database message. The original exception remains chained for diagnostic code, which must not be exposed to users. Unselected database errors and non-database exceptions are re-raised.

This boundary does not set a lock timeout, retry a write, guarantee eventual success or change permissions. It covers only these four review writers and only errors raised inside their own atomic boundary. If a caller encloses a successful writer in an outer transaction, a failure at its later commit is outside the boundary. Other services, connection acquisition, rendering, middleware and database/proxy failures are also outside it. Do not treat a conflict as approval or evidence of a valid history.

## Evidence and limits

Synthetic tests simulate each selected SQLSTATE in all four writers after a temporary database change and verify savepoint rollback, domain-specific conflict types, cause preservation and no review creation. Simulated HTTP tests check private 409 responses without driver details; unknown database errors and other exceptions remain unmasked, and the legacy `pgcode` attribute is covered. Existing PostgreSQL separate-connection tests exercise actual lock timeout `55P03` at a product candidate, price product, source claim and clinical reference row. Only that SQLSTATE is exercised as a real database race in these four writers; the others are simulated here. These tests are not exhaustive and do not prove availability or a production retry strategy.
