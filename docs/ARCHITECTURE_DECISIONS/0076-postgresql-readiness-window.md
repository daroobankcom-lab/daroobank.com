# ADR 0076: PostgreSQL readiness retry window

Status: development-only implementation, 23 November 2026.

## Decision

The development startup helper makes at least one read-only `SELECT 1` attempt, even for a zero retry window. After an `OperationalError`, it closes the failed connection and waits at most the remaining monotonic retry window. It now checks the deadline before starting every subsequent attempt, rather than starting one more connection after sleeping to the deadline. Unexpected non-operational errors are not swallowed. The CLI failure message refers to a retry window, not a guaranteed wall-clock timeout.

This is not a hard 60-second deadline: an already-started connection, DNS lookup, query, close, scheduler delay or underlying driver may take longer than the remaining window. The configured libpq `connect_timeout` applies to connection establishment, not necessarily DNS or the query. The helper does not cancel operations, validate migrations, verify data or guarantee readiness after it returns. The development entrypoint remains unsuitable for production deployment.

## Evidence

Deterministic monotonic-clock tests reproduce and prevent a second attempt exactly at the deadline, verify one zero-window attempt and propagation of unexpected exceptions. Existing synthetic PostgreSQL subprocess tests exercise success and an absent database. These cases do not reproduce all network or server hangs or prove a hard startup bound.
