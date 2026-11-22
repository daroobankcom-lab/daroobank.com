# ADR 0002: offline ingestion-window inspection

Status: implemented for development inspection only, 22 November 2026.

## Context and decision

The target architecture requires an independent authorized worker, with a default 23:00–01:00 Asia/Tehran window across midnight. No authorized source, scheduler, worker, distributed lock or publication workflow exists. Implement a pure, offline window calculation with optional per-invocation local start/end and IANA timezone, a read-only development-only staff view, and a local JSON management command. The command has no DB, queue or network operation; the web view uses authentication/session/permission data but makes no scheduling or ingestion writes. Inputs are not saved as settings or audit records. This is not an actual scheduling configuration.

Use timezone-aware instants and Python `zoneinfo`; local boundary times must round-trip to exactly one UTC instant. Reject gaps and folds instead of guessing. Windows are half-open `[start, end)`; start equals end is invalid rather than a 24-hour window. Same-day and overnight windows are both supported. Return the current or next window only; no promise is made about later dates. A bad local boundary stops that calculation. The platform's installed timezone data and system clock must be correct and kept current.

## Alternatives and consequences

A fixed Tehran offset would mishandle historical and future rule changes; guessing an ambiguous boundary risks running at the wrong instant. Cron/Celery/Redis, a persistent UI configuration, leases and source execution are intentionally deferred until source rights, worker design and operational safety can be validated; a window is never authorization. This preview cannot enforce cutoff, prevent duplicate runs, resume work, detect clock errors or establish source rights, even when it reports a window is open. Before using this calculation in a scheduler: design persistence and audited policy changes, rights verification and revocation, clock monitoring, durable deduplication and database locking, shutdown/checkpoint behavior and concurrency tests against the actual production stack.
