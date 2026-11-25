# ADR 0022: price-review concurrency boundaries

Status: development-only tests and input hardening, 22 November 2026. Extends [ADR 0021](0021-price-irc-candidate-cache.md); no production concurrency guarantee is added.

## Decision

Make the limits of preliminary price matching visible on the candidate page. Keep the existing fresh, locked match for acceptance and the candidate-row lock and expected-review check; do not claim they enforce unique matches. Validate direct-service candidate IDs and expected review/product IDs as actual integers in the PostgreSQL bigint range (zero allowed only for expectations), and cap the two hidden form fields to that range. Boolean values are not service IDs. Invalid data is rejected before attempting a database lock. Authorization remains separate and is checked first.

Synthetic PostgreSQL `TransactionTestCase` tests use separate database connections, bounded timeouts and coordinated interleavings. They check that two reviewers submitting the same expected version produce one review and one conflict; an existing product row lock blocks acceptance, and a committed change is rejected on a subsequent attempt; a second transaction can insert a matching duplicate after the locked matching query but before acceptance commits; and an actual concurrent product change can be missed by a staging IRC cache while a later fresh lookup and acceptance see the changed state.

## Consequences and limits

The duplicate-insert test intentionally demonstrates **an allowed limitation**, not safety: PostgreSQL `SELECT FOR UPDATE` locks selected existing rows, not an IRC predicate or nonexistent rows. Even a successful preliminary acceptance can already be ambiguous by commit; later catalog writes can also invalidate it. Index projections may be stale. No automatic invalidation, follow-up review, shared writer protocol, table/predicate lock, serializable isolation, database uniqueness rule or publication is introduced. These mechanisms need a wider identity and concurrency design: normalized IRC is not itself a unique product identity, and a table-wide lock would block unrelated work. Direct or privileged writers can bypass application checks.

The tests demonstrate selected interleavings on the test PostgreSQL configuration, not all schedules, failure modes, database versions, deployments or production loads. Locks may wait or time out; test timeouts are not application timeout policy. A review, timestamp, fingerprint, source attestation and snapshot do not establish product identity, rights, authenticity or medical correctness. Only synthetic local data should be used; production requires legal, clinical, security and database review.
