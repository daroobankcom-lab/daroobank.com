# ADR 0114: one-shot recorded-name guard for isolated test teardown

Status: development-only safeguard, 24 November 2026. Extends [ADR 0109](0109-isolated-test-database-collision.md) for the three isolated test settings, without changing Django's default backend.

## Decision

After a successful initial CREATE, the isolated creation instance records the exact test database name in memory. Its teardown rejects an invalid or different name, or any name for which that instance has no successful CREATE record, before issuing DROP. The record is consumed **before** the one DROP attempt; failure or ambiguous connection loss is not retried automatically. A second CREATE on the same instance while a record is active is rejected. The runner still forbids reuse and parallel mode; normal successful teardown continues to use Django's PostgreSQL implementation.

## Evidence

On a disposable PostgreSQL cluster, a synthetic canary database with a random valid test-shaped name was not created by the running test-database creation instance. The old backend's direct teardown deleted the canary in a controlled negative test. The guarded backend rejects teardown through the active and a fresh creation instance and through Django's teardown wrapper; the canary's database OID and marker row survive. Mocked tests verify name mismatch, missing record, one-shot behavior and a simulated ambiguous DROP failure without further database access. Normal test lifecycle, collision, synthetic restore and browser exercises are run separately. These are selected test paths, not proof of safety under all conditions.

## Limits

An in-memory name record is **not identity or ownership proof**. Another privileged process can drop or replace the database under the recorded name before or during teardown; checking OID before DROP would still have a check/use race. CREATE success followed by connection loss, DROP failure, crashes or process termination can leave databases behind. The guard is not a distributed protocol, isn't designed for concurrent use of the same creation object, and can be bypassed by direct SQL, different settings/backends, or code changes. The separate synthetic restore target has its own cleanup logic and is not covered by this guard. No cluster-wide cleanup is added. Use only a separately authorized disposable cluster and synthetic data, verify any cleanup target independently, and never regard a name or this test backend as production protection.
