# ADR 0071: isolated names for general synthetic PostgreSQL tests

Status: development-only implementation, 23 November 2026.

## Decision

Provide opt-in `daroobank.synthetic_test_settings` for ordinary Django tests. Each settings import generates a random `test_daroobank_synthetic_<32 hex>` test database name, deep-copies the base database settings and uses the existing isolated test runner, which rejects `--keepdb` and Django's `--parallel` including parsed abbreviations. This does not change default development settings, browser or restore test settings. CI runs the ordinary suite with the new settings. Tests within the suite can still use separate connections and threads.

This addresses a real development-runner mistake: overlapping ordinary test invocations on the default shared test database caused one runner to destroy the other's database, invalidating that run. Random names make collisions extremely unlikely, not impossible; they are not a substitute for an independently disposable database server, permissions or authorization. The configured role can still create and drop databases and the test runner may delete an existing database on a name collision with `--noinput`. Settings are for tests only, never for serving or migrations. Abrupt termination can leave orphaned synthetic databases requiring explicitly authorized cleanup; there is no automatic cluster-wide cleanup.

## Evidence and limits

Tests verify random names, unchanged base settings and refusal of reuse/parallel flags. A local probe ran two independent PostgreSQL schema test suites concurrently with distinct generated database names; both completed successfully. This selected run does not establish complete isolation from global server resources, shared filesystem paths, races in application code, failures on exhaustion or safety for production data. Continue to use a disposable PostgreSQL cluster with synthetic non-sensitive data.
