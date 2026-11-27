# 0233 — the database migration plan, and what a rollback in this repository costs

Date: 2026-11-27
Status: accepted
Suite: `daroobank/test_database_migration_plan.py` (26 tests, ~1.1 s, of which 4 are database-backed
and take ~12 s more)

## Context

Seven documents ask for a migration procedure and the repository answers with two drills that roll a
throwaway database back. [DEPLOYMENT.md](../DEPLOYMENT.md) asks a release to *"run tests/migrations on
staging and validate rollback compatibility"*, to *"Use expand/contract migrations and versioned API;
snapshot/backup before destructive change"* and to *"Define rollback including content/cache and
migration compatibility before release"*, and then reports the one thing
[ADR 0225](0225-populated-rollback-drill.md) measured: *"A measured rollback of this schema is not one
command"*, the plan for `migrate catalog zero` *"is 11 migrations, is not ordered by app (`ingestion
0002` runs first) and commits each migration alone, so a block on any table it touches leaves the
database half undone with rows already destroyed"*, followed by the instruction *"Set `lock_timeout`,
stop the writers, copy the tables the cascade will drop before starting"*.
[OPERATIONS_RUNBOOK.md](../OPERATIONS_RUNBOOK.md) tells an operator to *"rerun in staging, then
explicitly resume from a safe checkpoint"* and documents a readiness command that *"reads this
process's settings and its migration table"*. [DEVELOPMENT_GUIDE.md](../DEVELOPMENT_GUIDE.md) warns
that catalog migration `0008` *"fails on existing violations and may wait for table locks"* and that
nobody should *"run multiple migration-starting web replicas"*.
[TESTING_STRATEGY.md](../TESTING_STRATEGY.md) counts migrations as integration coverage and *"All
relevant tests pass in CI and staging"* as a release condition, [ROADMAP.md](../ROADMAP.md) puts *"DB
migrations"* in Phase 1, and [PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) carries the
subject as an open gate: *"a staging upgrade and rollback **plan** — environment, order, backup and
restore step, owner and authorization for a destructive operation"*, adding that the drill *"measured
no duration, no WAL volume and no long-running `ALTER TABLE` under load"* and that *"Rollback of
Django's own apps, other shapes of concurrency (an open writing transaction, `CREATE INDEX
CONCURRENTLY`, a running command, a standby) and tested recovery from a real staging schema are
unmeasured."*

So the rollback direction had been measured once, on 31 fixture rows, with one shape of concurrency and
no clock. Every number the gate says is missing — duration, WAL volume, a long `ALTER TABLE` under
load, Django's own apps, the other shapes of concurrency — is obtainable from the same throwaway
databases the drills already build, so the document meant to close the gap measures them rather than
arguing about them. [DATABASE_MIGRATION_PLAN.md](../DATABASE_MIGRATION_PLAN.md) followed the form
[ADR 0227](0227-read-audit-plan.md), [ADR 0229](0229-attribution-gap-plan.md),
[ADR 0230](0230-mfa-implementation-plan.md), [ADR 0231](0231-secret-rotation-plan.md) and
[ADR 0232](0232-backup-recovery-plan.md) established: an unowned proposal, priced options, numbered
decisions, no implementation.

## Decision

Measure both directions of the migration path at three volumes, measure what a schema statement locks
and what stops it, roll back Django's own apps, find out what notices a half-undone schema, price a
copy at a volume, and implement no migration control.

1. **The plan states measurements instead of adjectives.** A `## What is true today, measured` section
   in nine subsections — what the tree migrates, the cost of each direction, what a rollback destroys,
   locks and a long `ALTER TABLE` under load, the one migration that reads data, Django's own apps,
   what notices a half-undone schema, the copy step at a volume, and what the repository already says
   — a `## Candidate approach and decisions required` section of eight numbered decisions, an
   `## Options and what each costs` table of seven options, a
   `## Required behavior before any staging migration` list of seven items and a
   `## Verification before any enablement` list of six.
2. **The seven options are A leave the migration path as it is, B write the staging sequence down as an
   ordered procedure, C bound the migration session with a timeout, D move index builds out of atomic
   migrations, E take a copy before every destructive migration and drill restoring it, F make a
   half-undone schema detectable, and G declare staging migration and rollback out of Phase 1
   scope.** Each carries a price counted from this tree and a sentence saying what it still does not
   answer.
3. **`daroobank/test_database_migration_plan.py` pins both halves.** Twenty-two tests are
   database-free and pin the plan's structure, the quotations it is written against, the migration and
   schema inventory, the absent timeout, the absent `atomic = False`, the command inventory and the
   schema pins a change would move; four are database-backed and re-perform four of the measurements —
   the cascade a rollback derives from the migration graph, what every existing command and both
   migration readiness checks say about a database a blocked rollback left half undone, the atomic
   refusal of the validated constraint migration, and the absence of any replica — so the claim that
   only `migrate --check` and one readiness line notice a half-undone schema has to stay true.
4. **Nothing was implemented.** No staging environment, no `lock_timeout` on any migration connection,
   no migration-order control, no copy step, no new command, no new migration and no new dependency.
   The suite's `NothingImplementedTests` pins each absence, including the 17 project migration modules,
   the 24 project models and `db_options = {'connect_timeout': 5}`.

## Measured behavior

All of it from throwaway PostgreSQL databases against the synthetic PostgreSQL 16.2 server the drills
use, with the `pg_dump` and `pg_restore` clients the `pgserver` wheel bundles, and one writer thread
committing an insert every 5 ms — about 195 writes a second — where a load is named. Durations and
byte counts are one measured run each, not budgets.

- **Both directions are sub-second and cheap in WAL, which is why neither is the risk.** On an empty
  throwaway database, `migrate` applied all 32 migrations in **0.927 s** writing **1,172,320 bytes**;
  `migrate catalog zero` unapplied its 11-migration cascade in **0.711 s** writing 149,408 bytes and
  left 17 tables and 21 applied rows; the other five apps followed in **0.378 s** and 61,536 bytes,
  leaving 9 tables and 15 applied rows; reapplying took **0.724 s** and 885,624 bytes and returned an
  inventory identical row for row — 279 columns, 111 indexes, 138 constraints — with **zero** rows.
  The nine survivors are six `auth_*` tables, `django_content_type`, `django_migrations` and
  `django_session`.
- **A rollback's cost does not grow with the data it destroys.** Inserting 50,000 rows into
  `staff_security_staffloginwindow` took 0.345 s and wrote 29,621,944 bytes of WAL into an
  18,653,184-byte table; `migrate staff_security zero` then removed both of that app's tables in
  **0.096 s** writing **6,680 bytes** — 0.02 % of what the insert wrote — and took the row count from
  50,031 to 29. Reapplying took 0.068 s and returned a table with zero rows. A procedure that gates on
  duration therefore cannot see the loss.
- **What each statement locks.** `ALTER TABLE … ADD COLUMN` takes `AccessExclusiveLock` on the table
  alone; `CREATE INDEX` takes `ShareLock` on the table; `ALTER TABLE … ALTER COLUMN … TYPE
  varchar(64)` — the same width — takes `AccessExclusiveLock` on the table, its primary key, its
  indexes and its TOAST table, because it rewrites; `DROP TABLE` of an unreferenced table succeeded
  under `AccessExclusiveLock`, while `DROP TABLE catalog_productpresentation` was refused with
  `cannot drop table … because other objects depend on it` and `TRUNCATE` of the same table with
  `cannot truncate a table referenced in a foreign key constraint`.
- **A rewrite is priced by the table, a metadata change is not, and the WAL is the table.**
  `ADD COLUMN … integer NOT NULL DEFAULT 0` took 0.001 s and 1,344 bytes on an empty table and 0.001 s
  and 1,408 bytes on the same table with 50,000 rows. `ADD COLUMN … text NOT NULL DEFAULT
  md5(random()::text)` took 0.007 s and 27,016 bytes at zero rows, 0.143 s and 17,895,928 bytes at
  50,000, and **3.631 s and 178,759,168 bytes at 500,000 rows**, rewriting a 186,662,912-byte table
  into 174,104,576 bytes.
- **That rewrite is the long-running `ALTER TABLE` under load.** With the writer running, it waited
  **2.726 s** and blocked exactly **one** insert, for **2.703 s**, with four writes landing while it
  held the lock. A blocking `CREATE INDEX` over the same rows took 0.102 s and blocked one writer for
  0.094 s; the metadata-only `ADD COLUMN` took 0.001 s and blocked nobody; `CREATE INDEX CONCURRENTLY`
  run outside a transaction took 0.003 s and blocked nobody.
- **One session that is only reading is enough to stop a migration, and 2 s is enough to cancel it.**
  With an uncommitted `UPDATE` elsewhere, a metadata `ALTER TABLE` was cancelled after **2.001 s** with
  `canceling statement due to lock timeout`; a session running `SELECT count(*)` and `pg_sleep(4)`
  produced the same cancellation. `migrate catalog zero` run against such a reader was cancelled after
  **2.551 s** leaving 32 tables, **31 of 32** applied migrations and 29 rows, with the cascade's first
  migration — `ingestion 0002`, not a `catalog` one — already committed.
- **No migration connection carries a timeout.** `daroobank/settings.py` sets
  `db_options = {'connect_timeout': 5}` and nothing else, while the request path bounds itself with
  `SET LOCAL lock_timeout = '1s'` in three project modules and `SET LOCAL statement_timeout` in four
  places. The 2 s in every number above is the drill's own experiment, not a configuration.
- **No project migration can hold a concurrent index build.** `atomic = False` appears in **zero** of
  the 17 modules, and PostgreSQL refuses the statement inside a transaction with
  `ActiveSqlTransaction: CREATE INDEX CONCURRENTLY cannot run inside a transaction block`.
- **The one migration that reads data is cheap, and its failure is atomic.** `catalog 0008`, the
  validated `catalog_published_requires_verified` check constraint, took **0.100 s** and wrote
  **2,464 bytes** of WAL against 200,000 synthetic presentations — 0.068 s and 2,440 bytes on an empty
  table — and under the write load 0.096 s, 6,200 bytes, **zero** blocked writes and a slowest write of
  0.028 s. Against a single violating row it failed after **0.052 s** with
  `IntegrityError: check constraint "catalog_published_requires_verified" … is violated by some row`,
  wrote **0 bytes**, left the constraint absent and left `django_migrations` at 31 rows. A forward
  migration that fails leaves the schema as it was; a rollback that is blocked does not.
- **Rolling back Django's own apps is the most destructive command in the tree.** `migrate sessions
  zero` is one migration, 0.156 s and 4,544 bytes, and costs `django_session` while every project row
  survives. `migrate contenttypes zero` derives a cascade of **26 migrations, 24 of them project
  migrations** — `auth` 12, `contenttypes` 2, `catalog` 6, `clinical` 2, `ingestion` 2, `pricing` 1,
  `sources` 1 — took 1.241 s, wrote 346,936 bytes, and took the database from 32 tables to **5** and
  from 31 rows to **6**: `catalog_productpresentation`, `pricing_pricecandidate`,
  `staff_security_publicreadwindow`, `staff_security_staffloginwindow` and `django_migrations`.
  `migrate auth zero` afterwards found nothing left to take, at 0.016 s and 752 bytes. An ORM read of
  `ProductPresentation` still returned 2 rows after all three, while the model-derived inspection
  reported 28 unresolved tables, 49 missing foreign keys, 45 missing unique keys, 23 missing check
  constraints, 239 missing columns and 51 missing field indexes.
- **Almost nothing notices a half-undone schema.** On the database the blocked rollback left,
  `manage.py check --database <alias>`, `makemigrations --check --dry-run` and `showmigrations` all
  exit **0**; `migrate --check` exits **1**; readiness reports `migrations_applied` false with
  `1 migrations are not applied: ingestion.0002_importreceiptitem_importreceipt_manifest_version_and_more`
  and `migration_history_consistent` true with `every applied migration has a file in this release` —
  the same pair an unmigrated database produces. The
  model-derived inspection does count the damage (1 unresolved table, 3 missing foreign keys, 10
  missing columns) but `catalog/management/commands/inspect_postgresql_schema.py` takes no `--database`
  and reads `django.db.connection`, so it cannot be pointed at another database. Repairing forward took
  **0.198 s**, returned an identical inventory and 32 applied migrations, left the row count at 29 of
  31, and made readiness report `32 migrations applied, none pending`.
- **A copy at that volume is small, fast, and carries its sequences.** `pg_dump --format=custom
  --no-owner --no-acl` of the 50,031-row database exited 0 in **0.154 s** producing **1,186,535
  bytes**, against the 136,001-byte fixture archive [ADR 0232](0232-backup-recovery-plan.md) measured —
  ~1,614 times the rows for 8.7 times the bytes. `pg_restore --exit-on-error --single-transaction
  --no-owner --no-acl` into a database that did not exist exited 0 in **0.327 s** printing 0 bytes on
  stderr, and the target held 50,001 rows, 32 applied migrations and a
  `catalog_productpresentation` identity sequence reading `(2, True)`; the next `INSERT` **succeeded
  with no `setval`**. The archive's `SEQUENCE SET` entries are why, and it is why ADR 0225's *"Identity
  sequences are part of any restore"* is a statement about a replayed copy rather than a restored one.
- **There is no standby to measure.** `pg_is_in_recovery()` is `false`, `pg_stat_replication` has 0
  rows and `pg_replication_slots` has 0 rows here, so the standby shape the gate names stays
  unmeasured rather than measured safe.

## Red checks

Twenty-eight mutations were applied to a byte-identical backup of the tree, one at a time, and the
suite was run after each with the bundled PostgreSQL clients on `PATH`, so the four database-backed
tests ran as well as the twenty-two that read files. Every file was restored from its backup and
re-hashed afterwards, the two mutations that create a file left nothing behind, and the final run was
green.

| Mutation | Result |
| --- | --- |
| the plan drops its proposal disclaimer | exit 1, 1 of 26 tests fail |
| the plan drops its `Nothing is implemented` sentence | exit 1, 1 of 26 tests fail |
| the plan drops a measured WAL volume | exit 1, 1 of 26 tests fail |
| the plan drops a numbered decision | exit 1, 1 of 26 tests fail |
| the plan drops an option row | exit 1, 1 of 26 tests fail |
| the plan drops a required-behavior item | exit 1, 1 of 26 tests fail |
| the plan drops a verification item | exit 1, 1 of 26 tests fail |
| the plan drops a schema count it quotes | exit 1, 1 of 26 tests fail |
| the plan starts presenting an option as chosen | exit 1, 1 of 26 tests fail |
| `docs/DEVELOPMENT_GUIDE.md` stops saying what the plan quotes it for | exit 1, 1 of 26 tests fail |
| `docs/DATABASE_SCHEMA.md` stops naming the plan | exit 1, 1 of 26 tests fail |
| the release-evidence row closes | exit 1, 1 of 26 tests fail |
| this record loses a limitation | exit 1, 1 of 26 tests fail |
| this record's Suite line stops counting its tests | exit 1, 1 of 26 tests fail |
| the decision index stops summarizing this record | exit 1, 1 of 26 tests fail |
| `daroobank/settings.py` gives the migration connection a lock timeout | exit 1, 1 of 26 tests fail |
| a migration module marks itself non-atomic | exit 1, 1 of 26 tests fail |
| `.github/workflows/checks.yml` defines an environment | exit 1, 1 of 26 tests fail |
| the readiness command loses one of its two migration checks | exit 1, 1 of 26 tests fail |
| the readiness command renames the loader its second check reads | exit 1, 1 of 26 tests fail |
| `inspect_postgresql_schema` grows a `--database` option | exit 1, 1 of 26 tests fail |
| `compose.yaml` stops binding the database port to localhost | exit 1, 1 of 26 tests fail |
| a management command appears | exit 1, 1 of 26 tests fail |
| `requirements.txt` grows a dependency | exit 1, 1 of 26 tests fail |
| a settings module appears | exit 1, 1 of 26 tests fail |
| a pinned schema count moves on its own | exit 1, 1 of 26 tests fail |
| the document-count pin moves back | exit 1, 1 of 26 tests fail |
| the drill fixture stops filling 31 rows | exit 1, 2 of 26 tests fail |

All twenty-eight were caught, and twenty-seven of them by exactly one test, because each mutation was
made to move one pin. The widest catch was the drill fixture growing a row, which broke both the pin
on the row counts the plan quotes and the half-undone measurement that fills the same tables: that is
the one place where a document pin and a database-backed measurement overlap.

One mutation was missed on the first pass and is recorded here because of what it says about the pin.
Renaming the local `loader` inside `migration_history_consistent()` left `MigrationLoader(connection`
appearing twice, so the count the suite pinned did not move and the run stayed green — a check that no
longer compares what is on disk with what is applied looked unchanged to it. The pin now also counts
`loader.disk_migrations` (twice) and `loader.applied_migrations` (three times), which a rename moves,
and the row above is that mutation re-run against the strengthened pin. The weaker variant of the same
mutation, deleting the comparison altogether, was caught before and after.

After every file was restored and re-hashed no file differed by a byte, neither created file existed,
the suite ran green again (26 tests, exit 0) and no database was left behind.

## Consequences

- `docs/DATABASE_MIGRATION_PLAN.md` is the answer to the *Data model and migrations* row of
  `docs/PHASE1_RELEASE_EVIDENCE.md`, and the row now says so. The row stays **Open**: a plan is not a
  staging environment, an order, a copy procedure, an owner or an authorization.
- `docs/DEPLOYMENT.md`, `docs/OPERATIONS_RUNBOOK.md`, `docs/DEVELOPMENT_GUIDE.md`,
  `docs/TESTING_STRATEGY.md`, `docs/DATABASE_SCHEMA.md` and `docs/CHANGELOG.md` each gained a sentence
  that names what the drills do not measure and links this record. The deployment guide's four
  instructions — set `lock_timeout`, stop the writers, copy first, `setval` on restore — are unchanged,
  because turning them into a sequence is option B and no option was chosen.
- The two existing drills still pass unchanged: `daroobank.test_migration_reversibility` and
  `daroobank.test_populated_rollback_drill` run 14 tests in about 32 s against the synthetic server and
  leave no database behind, and this record's measurements do not alter a pin in either.
- The new suite adds four database-backed tests to an ordinary run — a graph-derived cascade count, a
  deliberately half-undone throwaway database read by every command that could notice it, a refused
  constraint migration, and the absence of a replica — so a run is about 12 s longer and no new opt-in
  switch exists. Its database work is confined to the throwaway databases
  `daroobank/test_migration_reversibility.py` already creates and drops.
- The pins that count the tree moved with it: `daroobank/test_document_links.py` now counts 265
  documents, 233 records, 1075 links, 31 external links, 29 anchors and 23 `Suite:` lines, and the two
  suites that count test modules now count 239.
- One pin outside this plan moved because of it. `daroobank/test_mfa_implementation_plan.py` counts the
  test modules that name the login route, and this suite names the `staff_security_staffloginwindow`
  table and the command that cleans up staff login windows, so that count is 43 rather than 42. The
  sentence in `docs/MFA_IMPLEMENTATION_PLAN.md` that quotes it still read *42 of the 237 test modules*
  — stale since the tree grew past it — and now reads 43 of the 239.
- A reader can now see, without running anything, that a rollback here is fast in both directions, that
  its cost is rows rather than seconds, that one Django app name removes 24 project migrations, that a
  500,000-row rewrite stalls a writer for 2.703 s, that nothing but `migrate --check` and one readiness
  line reports a half-undone schema, and that the copy which makes a rollback survivable is 1.2 MB and
  0.327 s at 50,031 rows.

## Limitations

- **Every number is one run on one machine, on synthetic data.** 500,000 rows in a window table and
  200,000 synthetic presentations are larger than the fixture and smaller than a pharmacy catalog, and
  none of it has the row width, the index count or the fragmentation of real data. The durations say
  what this schema did once, not what a staging database will do.
- **The load is one writer thread, not a workload.** About 195 commits a second from one connection
  — 1,566 writes counted over an 8.021 s window against the same 500,000 rows, a mean commit of
  0.558 ms and no writer error — with no readers, no connection pool, no vacuum, no replication and
  no checkpoint pressure. A real migration competes with all of those, and a stall measured against
  one writer understates a queue.
- **No option was evaluated for safety or lawfulness.** Whether a pharmacy catalog may be rolled back
  at all, who authorizes it, what a copy of it may be kept and for how long, and whether a staging
  environment may hold real data are questions for an owner and a reviewer, not for this record.
- **The prices are counted, not run.** No migration control was prototyped, so no cascade of pin
  failures was measured the way [ADR 0227](0227-read-audit-plan.md) measured 20 failures across 7
  suites. The counts in options B to G are an inventory of what moves, and the real total is unknown
  until an implementation exists.
- **The standby, the running command and the real staging schema stay unmeasured.** This environment
  has no replica and no standby, no long-running management command was held open against a migration,
  and no staging schema exists to recover from — three of the shapes the open gate names.
- **The suite pins documents, counts and two re-performed measurements.** It cannot tell whether the
  eight decisions will ever be answered, whether the answers will be adequate, or whether a rollback
  performed under them would leave the business recoverable; forcing the questions is all this record
  does.
