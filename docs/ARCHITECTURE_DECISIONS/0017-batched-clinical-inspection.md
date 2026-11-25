# ADR 0017: batched supplementary-reference inspection

Status: development-only implementation, 22 November 2026; changes the query strategy in [ADR 0016](0016-clinical-technical-inspection.md). Later [ADR 0056](0056-clinical-inspection-author-presence.md) adds author-presence semantics and one SELECT.

## Decision

Avoid one or two reference queries per valid draft in the synthetic clinical technical scan. After retrieving up to 50 drafts plus one lookahead, validate the draft and immediate parent exactly as before. For valid drafts only, Django's sliced prefetch uses PostgreSQL `ROW_NUMBER()` partitioned by draft ID to return the first 11 supplementary assertions per draft, ordered by assertion ID. This yields at most 550 assertion rows to Python per request; the 51st draft's assertions are not fetched. Gather distinct valid recorder IDs and check them in one bulk user query, without joining away assertions whose recorder is missing. Drafts with more than ten assertions still report over-limit before other assertion checks; invalid drafts still skip assertion checks.

Use the same per-assertion and cap checks as the existing individual `evidence_state`. That existing function still obtains its own data and produces the same fingerprints, snapshots, and statuses for the write/review workflow. Batch inspection only emits statuses and never authorizes writes. It rejects duplicate, unsaved or more than 50 draft objects. A fresh prefetch is forced even if instances are reused. Tests compare batch outcomes to individual checks, including missing recorders and invalid and over-limit data, and exercise all 50 drafts at the ten-item boundary and beyond.

## Consequences and limits

For the configured PostgreSQL backend a scan executes at most three SELECT queries (drafts/parents, assertions, users), with fewer when no valid drafts or recorders exist. This bounds rows delivered to Python, not PostgreSQL's scanned or sorted rows, memory, duration, bytes, or query planner choices. The window query may process many matching assertions even though only 11 per draft are returned. It has not been benchmarked on production data and is not a production monitoring system.

No transaction snapshot is established: concurrent changes between the draft, assertion and recorder reads or between pages can produce stale, incomplete or inconsistent observations. These are observations of technical checks, not authenticity, clinical verification, rights, full ancestry, review validity or approval. See ADR 0016 for access, privacy, pagination and the remaining limitations. Django and PostgreSQL version compatibility is covered by the project's pinned Django and PostgreSQL CI, not other database engines.
