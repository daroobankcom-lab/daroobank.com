# ADR 0090: optimization-safe synthetic restore verification

Status: development-only implementation, 24 November 2026; extends [ADR 0077](0077-cross-domain-restore-drill.md) and [ADR 0079](0079-restored-sequence-probes.md).

## Context and decision

Python removes `assert` statements under optimization. The synthetic cross-domain fixture and inline identity-graph checks previously used such statements; invoking the fixture under `python -O` could therefore accept selected corrupted data. The ordinary drill's child environment is intentionally allowlisted and does not propagate `PYTHONOPTIMIZE`, but a parent or direct verifier invocation can still be optimized.

Replace fixture `assert` statements with explicit checks that raise a generic `AssertionError`, and move inline identity verification into a guarded fixture function using the same explicit checks. The opt-in drill invokes the guarded function, continues to suppress subprocess output in user-facing errors, and uses only disposable named databases. These checks now run under Python optimization; no production database, backup or repair behavior is introduced.

## Evidence and limits

A synthetic PostgreSQL test invokes both cross-domain and identity verifiers in a separate `python -O` process, verifies a valid fixture, and rejects a corrupted receipt and a wrong graph hash. The restore suite also passes with its parent interpreter optimized. This only exercises selected checks and corruptions; it does not establish complete restoration, backup authenticity, transaction consistency under all workloads, recovery time or production suitability. Exception messages remain generic, although local test diagnostics and exception chains can still expose information.
