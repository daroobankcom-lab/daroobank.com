# ADR 0055: selected staging concurrency failures after rollback

Status: development-only, 23 November 2026. This improves reporting for synthetic CSV staging and receipt creation; it is not source authorization, immutable audit or publication.

## Decision

Use the existing atomic conflict boundary for the product and price CSV staging services and for their outer receipt/manifest writers. PostgreSQL `55P03` (lock unavailable/timeout), `40P01` (deadlock) and `40001` (serialization failure) raised inside these boundaries become `StagingConflict` only after the affected transaction or savepoint rolls back. The outer receipt boundary also covers receipt/manifest writes and its own commit. Other database and non-database errors propagate unchanged. Direct price dry runs use the same boundary, although they acquire no cooperative source lock.

The two development upload forms return a generic private HTTP 409 with a prompt to reselect the file, and their non-field errors are in an alert region. The price management command turns the selected conflict into a `CommandError`; it does not print a success result. Original database exceptions remain chained for controlled diagnostics and must not be shown to users.

## Evidence and limits

Before this change, separate-connection PostgreSQL tests reproduced uncaught advisory-lock timeout errors in both upload paths. Tests now exercise actual `55P03` for both HTTP uploads and direct staging, private error headers, and absence of candidate, receipt and manifest rows. Simulated selected SQLSTATE failures on the second candidate and after manifest creation test rollback for both domains; another test verifies an earlier committed receipt and its candidates remain intact. Unknown errors are not translated, a price preview's simulated conflict is distinct from file validation, and CLI error handling is exercised. Deadlock and serialization are simulated for these staging paths; these tests do not cover all schedules or deployment setups.

No lock timeout, automatic retry, deduplication policy change or production availability guarantee is added. Browser file inputs must be selected again; callbacks must not have external side effects because rollback cannot undo those. If the caller surrounds a successful wrapper with another transaction, errors at the enclosing commit are outside this boundary. Connection loss or unknown commit outcome and failures outside the boundary are not classified or guaranteed safe to retry. Same-source advisory locks remain cooperative, do not lock other domains or uncooperative writers, and can wait or deadlock; file receipt data is not proof of the original file, source rights, real-world correctness, or approval. Use synthetic data only.
