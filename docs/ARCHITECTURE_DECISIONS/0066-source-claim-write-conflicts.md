# ADR 0066: source claim creation conflict boundary

Status: development-only, 23 November 2026. Extends the unverified source-claim ledger and complements the review writer boundary in [ADR 0053](0053-triage-write-conflict-boundary.md).

## Decision

Wrap the source claim `get_or_create` write in the shared atomic conflict boundary. A PostgreSQL lock-not-available/timeout (`55P03`), deadlock (`40P01`) or serialization failure (`40001`) raised within that boundary is translated after rollback into `ClaimConflict`, a subtype of `ClaimError`, with the underlying database error retained as its cause. The staff create view catches it separately and shows a generic conflict message with HTTP 409 and existing private headers. Other validation failures retain the existing form behavior. The view does not retry. A successful duplicate retains the original recorder and does not replace the claim.

Permission checks and data validation run before the transaction. Unselected database errors and programming errors are not masked; a surrounding outer transaction's eventual commit remains outside this boundary. The response re-renders the operator's submitted form, so it is not a general confidentiality filter. Access to local data and logs must still be restricted. This does not verify the claimed rights, qualify the actor, prevent later database changes, or enable collection or publication. Only synthetic data is suitable.

## Evidence and limits

Synthetic tests simulate each selected SQLSTATE after insertion to check rollback, exception chaining and a usable surrounding transaction; an unselected error still propagates. Separate PostgreSQL connections create a real unique-constraint wait with a short lock timeout, exercised at both service and HTTP boundaries; the latter returns a private 409. Once the first transaction commits, a subsequent explicit replay finds the original claim and recorder. Tests do not reproduce actual deadlocks or serialization failures in this path, cover every interleaving or establish production safety. There is no automatic retry or guarantee of success at an outer commit.
