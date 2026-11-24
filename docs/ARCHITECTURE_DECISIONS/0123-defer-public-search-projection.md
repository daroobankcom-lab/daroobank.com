# ADR 0123: avoid fetching internal projections on public reads

Status: development change, 24 November 2026.

## Context and decision

Public search uses `search_text` to find candidates in PostgreSQL, then validates current display fields and recomputes the normalized search text from those fields before returning each result. Public detail uses the same eligibility predicate but does not search on the projection. Neither existing HTML template nor JSON serializer needs the stored `search_text` or `irc_normalized` values. In particular, `search_text` is a PostgreSQL text column and a bypassed write can make it much larger than a normal model-generated value.

Defer these two columns when selecting search batches and individual public details. The SQL search condition still uses `search_text`, the current-field recheck still occurs, and pagination, eligibility and public response fields remain unchanged. The database may still read, decompress and scan the large search projection to evaluate the condition; this change only avoids transferring those two columns in the selected result rows. It is not a bound on database work, request time, query memory, all row sizes or capacity.

## Consequences and evidence

The services still return Django model instances, now with two deferred fields. A direct caller accessing either field incurs a separate query and can see a later database state or an error if the row disappears; saving such instances also follows Django's deferred-field behavior and the model's own save logic. Do not treat those model instances as immutable snapshots. Callers that require the projections should fetch them explicitly and consider their own consistency and authorization. Public response paths must not access deferred fields implicitly.

Synthetic PostgreSQL tests use a bypass-written million-character projection and check selected SQL `SELECT` lists, query counts, returned values, GET/HEAD HTML and JSON, and absence of the two projections from those selects. Search still matches via the stored projection, then validates current fields. Existing pagination and concurrency tests remain relevant. Tests do not measure memory or network bytes and are not proof of behavior under all middleware, callers, corrupt data, database plans or workloads. No migration, index, data repair, source verification or clinical approval is included.
