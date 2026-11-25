# ADR 0120: synthetic search-index experiment, not an index migration

Status: development experiment, 24 November 2026. No production database or actual medicine records were used.

## Decision

Do not add a `pg_trgm` extension or index to application migrations solely on this evidence. Keep an opt-in experiment in `catalog/test_synthetic_search_benchmark.py` to compare the current search with temporary GIN trigram and partial B-tree ordering indexes in a disposable test database. Adding an index would require a reviewed migration and privilege/extension policy, realistic workload and storage measurements, write-cost and deployment/rollback planning, and accessibility and relevance evaluation. This experiment neither changes app search semantics nor makes the current search scalable.

## Method

The test requires the isolated synthetic settings/backend, a fresh empty random-named test database, opt-in environment flag, and a server with `pg_trgm` available and the test role authorized to create it. These checks do not authenticate the PostgreSQL host or prove isolation: an operator must verify the cluster is disposable and authorized. It bulk-creates 100,000 fictional published-flagged test records, half with a Persian half-space in their names, and measures five selected queries through Django's in-process JSON endpoint. It warms each query and samples 30 sequential requests per phase, reporting median and nearest-rank p95, not network or browser latency. It compares first and selected second-page IDs between phases, then reports one `EXPLAIN (ANALYZE, BUFFERS)` per query. In each phase, four thread-local in-process Django clients additionally issue eight requests each for the same common query, with a coordinated start and separate DB connections; all returned IDs are checked. It creates randomly named indexes only in the disposable test DB, reports their sizes and build times, and removes its own trigram index before the ordering-index-only phase. Five sampled 1,000-row updates in each phase are rolled back; these are not durable commit or realistic write-throughput measurements. The benchmark has no latency pass/fail thresholds. Django attempts to destroy the test database on completion; a crash can leave it behind, and a name prefix is not ownership proof.

## One local observation

On a disposable local PostgreSQL 16.2 cluster, Linux x86-64, 2 visible CPUs and approximately 3.85 GiB reported memory, Python 3.11.2 and Django 5.2.19, database collation `C`, 24 November 2026, the test completed successfully. The locally bundled PostgreSQL initially lacked `pg_trgm`; for this synthetic cluster only, the PostgreSQL upstream `REL_16_2` contrib source was compiled into the ignored local virtual environment. The tarball SHA-256 was `bea6ebced0b04923dc32bfff1950d5d23b2407843af71593100e09fd2bf4aa53`. This is not a production installation procedure.

| Synthetic query | Baseline p50 / p95 ms | With index p50 / p95 ms | Observed query plan with index |
|---|---:|---:|---|
| Common Persian text | 46.425 / 52.847 | 46.317 / 58.575 | Sequential scan |
| Rare localized digits | 26.693 / 41.921 | 2.182 / 3.082 | Bitmap index and heap scans |
| Absent Persian text | 29.704 / 38.433 | 1.451 / 1.907 | Bitmap index and heap scans |
| Single Persian letter | 47.025 / 65.059 | 41.554 / 45.819 | Sequential scan |
| Literal percent, no match | 26.015 / 31.666 | 23.233 / 29.833 | Sequential scan |

The index occupied 5,677,056 bytes and took 1.240 seconds to build on this dataset. Median rollback-only update time was 19.523 ms before and 41.936 ms after index creation (five samples each; p95 is the maximum). These numbers are illustrative, not evidence of a general speedup or write penalty.

A later run added a partial B-tree on `(name_fa, id)` for published, verified rows. In that run, baseline p50 for common/rare/absent/short/percent queries was 37.342/24.013/27.881/41.521/23.234 ms. With both indexes, p50 was 4.493/1.946/1.939/4.563/20.457 ms; the planner selected the B-tree for common/short, GIN for rare/absent, and a sequential scan for percent. With only the B-tree, those medians were 4.913/25.089/33.039/6.382/23.823 ms. The B-tree was 5,922,816 bytes and built in 0.083 seconds in that particular run. Index order, preceding rolled-back updates and data distribution confound comparison, and the B-tree is not in application migrations.

## Limitations

A subsequent four-client run on the same host produced common-query p50/p95 of 151.976/272.769 ms with no index, 167.527/250.047 ms with GIN alone, 16.141/36.835 ms with both, and 23.271/67.928 ms with the B-tree alone. These are 32 requests per phase, in one Python process, while an unrelated synthetic migration stress job also ran on the host; they are not capacity or service-level measurements.

The artificial data have highly repetitive fields and only one query ordering; each index phase follows baseline, the both-index phase precedes removal of the GIN index, earlier rolled-back updates change the database's physical state, caches are warm, 30–32 samples are too few for reliable tail estimates, and representative concurrent users, network, cold caches, ingestion, durable commits, bloat, VACUUM, persistent storage, deployment locks and failures were not studied. Worker-level plan rows/times may be per-loop averages, not totals. The experiment does not address stale projections, forward-only non-snapshot pagination, source/clinical correctness or search relevance. Even though these few timings happen to fall under a provisional budget, this is not the documented 100,000-record representative concurrent performance acceptance test and must not be treated as one.
