# ADR 0054: translate selected clinical draft and reference write conflicts

Status: development-only, 23 November 2026. This extends the selected atomic conflict boundary in ADR 0053 to synthetic clinical draft creation, revision and supplementary-reference addition. It does not change the draft, reference or review locking guarantees.

## Decision

The shared writer boundary is renamed `write_conflict_boundary` to reflect its broader use. Inside it, draft creation (with or without a parent) and reference addition now convert PostgreSQL SQLSTATE `55P03`, `40P01` and `40001` to `DraftConflict` only after their transaction or nested savepoint rolls back. The clinical create form now handles that conflict with the same generic, private HTTP 409 response as revision and reference forms. Existing authorization, validation, data and lock order remain unchanged; other errors are not translated.

No timeout or automatic retry is introduced. A surrounding transaction's later commit is outside the boundary; a serializable outer transaction may need to be rolled back and restarted in its entirety. The boundary does not cover reads performed before calling these writers, response rendering, unrelated services or upstream failures. It does not make references, drafts or history immutable or clinically approved.

## Evidence and limits

Synthetic tests hold a PostgreSQL draft row lock on a separate connection and demonstrate actual `55P03` translation for revision and reference addition, no partial writes, then successful writes after lock release. HTTP tests simulate all three selected SQLSTATEs for initial creation, revision and reference creation after a temporary database mutation, checking rollback, generic 409, private headers and absence of the synthetic driver detail. An unknown SQLSTATE remains an error rather than being masked. Deadlock and serialization are simulated for these additional writers, not proven by these tests as real interleavings. Different timings, database deployments and other failures remain untested; the portal remains development-only.
