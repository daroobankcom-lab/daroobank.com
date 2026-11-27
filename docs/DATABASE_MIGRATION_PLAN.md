# The database migration plan, and what rolling a schema back in this repository actually costs

`docs/DEPLOYMENT.md` asks a release to *"run tests/migrations on staging and validate rollback
compatibility"*, to *"Test proxy host/origin and cookies, health endpoints, database migrations,
worker isolation"*, to *"Use expand/contract migrations and versioned API; snapshot/backup before
destructive change"* and to *"Define rollback including content/cache and migration compatibility
before release"* — and then reports what
[ADR 0225](ARCHITECTURE_DECISIONS/0225-populated-rollback-drill.md) measured: *"A measured rollback
of this schema is not one command"*, the plan for `migrate catalog zero` *"is 11 migrations, is not
ordered by app (`ingestion 0002` runs first) and commits each migration alone, so a block on any
table it touches leaves the database half undone with rows already destroyed"*, and the instruction
that follows is *"Set `lock_timeout`, stop the writers, copy the tables the cascade will drop before
starting"*. `docs/OPERATIONS_RUNBOOK.md` tells an operator to *"rerun in staging, then explicitly
resume from a safe checkpoint"* and documents a readiness command that *"reads this process's
settings and its migration table"*. `docs/DEVELOPMENT_GUIDE.md` warns that catalog migration `0008`
*"fails on existing violations and may wait for table locks"*. `docs/TESTING_STRATEGY.md` counts
*"atomic publication/rollback … migrations and backup restore"* as integration coverage and *"All
relevant tests pass in CI and staging"* as a release condition, `docs/ROADMAP.md` puts *"DB
migrations"* in Phase 1, and `docs/PHASE1_RELEASE_EVIDENCE.md` carries the subject as an open gate:
*"a staging upgrade and rollback **plan** — environment, order, backup and restore step, owner and
authorization for a destructive operation."*

So the repository has 17 migration modules across six apps, two drills that measure the rollback
direction on synthetic databases, and one deployment paragraph about lock timeouts — and no answer to
the four questions a staging migration actually raises: **which environment, in which order, with
what copied beforehand, and who says go?**
[ADR 0233](ARCHITECTURE_DECISIONS/0233-database-migration-plan.md) records what this document says
and what it measures. It is not a staging environment, not a migration order, not a copy procedure
and not an authorization.

This document is a **proposal**. It has no owner and no approval, so it must not be read as a
decision, and it must not treat two synthetic drills that roll a throwaway database back as a staging
procedure. Its prices are counted from the pins and files below, not prototyped: no migration control
was implemented and reverted, so no cascade of pin failures was run — but the measurements **were**
performed, on synthetic data in throwaway databases, and every number below is the result of those
runs.

**Nothing is implemented.** No staging environment, no `lock_timeout` on any migration connection, no
migration-order control, no copy step, no new command, no new migration and no new dependency exists
in this tree because of this file. The measurements were performed with the `manage.py migrate`
command the drills already call, the `pg_dump` and `pg_restore` clients the restore drill uses, and
writer threads that no longer exist, against databases that no longer exist.

## What is true today, measured

Counted on this tree by reading the migration modules, the settings, the workflow and the two drill
suites, and by running every experiment below against the synthetic PostgreSQL 16.2 server on
throwaway databases that each experiment created and dropped. Durations and byte counts belong to
**one measured run** on one machine and are quoted as such, never as a budget. They are pinned by
`daroobank/test_database_migration_plan.py`.

### What the tree migrates

* **17 project migration modules in six linear chains, and 15 more from Django.** `catalog` 8,
  `clinical` 2, `ingestion` 2, `pricing` 2, `sources` 1, `staff_security` 2 — the counts
  `daroobank/test_migration_reversibility.py` pins as `MIGRATION_COUNTS` — plus `auth` 12,
  `contenttypes` 2 and `sessions` 1, which is the 32 rows a freshly migrated `django_migrations`
  holds. The schema they produce is 33 tables, 279 columns, 111 indexes, 138 constraints and 50
  foreign keys.
* **Every migration is atomic, so none of them can hold a concurrent index build.** The string
  `atomic = False` appears in **zero** of the 17 modules, and `CREATE INDEX CONCURRENTLY` inside a
  transaction is refused by PostgreSQL itself — measured as
  `ActiveSqlTransaction: CREATE INDEX CONCURRENTLY cannot run inside a transaction block`. Run
  outside a transaction on the same 2-row table it took 0.003 s and blocked no writer.
* **Two data operations exist and both reverse to nothing.** `catalog 0002` and `catalog 0004` are
  the only `RunPython` modules in the tree, and both pass `migrations.RunPython.noop` as their
  reverse, which the reversibility suite names explicitly: rolling them back keeps the column and
  loses the normalization it wrote.
* **One migration reads data, and it is the one the guide warns about.** `catalog 0008` is a single
  `AddConstraint` for `catalog_published_requires_verified`; PostgreSQL validates a check constraint
  against every existing row while holding `AccessExclusiveLock`.
* **No migration connection has a timeout.** `daroobank/settings.py` sets `db_options =
  {'connect_timeout': 5}` and nothing else, so `manage.py migrate` runs with no `lock_timeout`, no
  `statement_timeout` and no `idle_in_transaction_session_timeout`. The request path bounds its waits
  — `SET LOCAL lock_timeout = '1s'` appears in three project modules and `SET LOCAL statement_timeout`
  in four places — and the migration path bounds nothing. The 2 s `lock_timeout` every rollback
  number below quotes is set by the drill, per session, as an experiment.
* **CI migrates a database that has nothing in it.** `.github/workflows/checks.yml` runs
  `python manage.py migrate --noinput`, then `check`, `makemigrations --check --dry-run` and
  `inspect_postgresql_schema`, against a temporary PostgreSQL service it just started, and runs
  `migrate --check` twice more inside compose. The workflow holds no `environment:` key at all, which
  is the *"defines no staging environment"*
  [ADR 0226](ARCHITECTURE_DECISIONS/0226-ci-artifact-gate.md) measured.

### The cost of each direction, measured

One throwaway database, migrated from nothing, then rolled back and reapplied.

| Direction | What ran | Seconds | WAL bytes | Resulting state |
| --- | --- | --- | --- | --- |
| forward | `migrate` (all 32) | 0.927 | 1,172,320 | 33 tables, 32 applied rows |
| one app back | `migrate catalog zero` (an 11-migration cascade) | 0.711 | 149,408 | 17 tables, 21 applied rows |
| the rest back | `clinical zero`, `ingestion zero`, `pricing zero`, `sources zero`, `staff_security zero` | 0.378 together | 61,536 | 9 tables, 15 applied rows |
| forward again | `migrate` (all 17 project migrations) | 0.724 | 885,624 | 33 tables, 32 applied rows, inventory identical, 0 rows |

* **The nine tables that survive a full project rollback are Django's.** Six `auth_*` tables,
  `django_content_type`, `django_migrations` and `django_session`.
* **The inventory that comes back is the inventory that left.** 279 columns, 111 indexes and 138
  constraints compared row by row, exactly as `daroobank/test_migration_reversibility.py` requires.
* **Sub-second in both directions is the whole cost, and it is not the risk.** The two existing
  suites — 14 tests covering reversibility and the populated drill — took 32.3 s wall in one run,
  most of it fixture work rather than migration work.

### Rows, not seconds: what a rollback destroys

* **A rollback of 50,000 rows costs 0.096 s and 6,680 bytes of WAL.** Inserting 50,000 rows into
  `staff_security_staffloginwindow` took 0.345 s and wrote 29,621,944 bytes of WAL into an
  18,653,184-byte table; `migrate staff_security zero` then removed both of that app's tables in
  0.096 s, writing 6,680 bytes — 0.02 % of the WAL the insert wrote — and the row count went from
  50,031 to 29. Reapplying took 0.068 s and returned a table with **zero** rows.
* **Duration therefore cannot be the gate.** Nothing about a rollback gets slower as the data it
  destroys grows, so a procedure that waits for a duration, or prices a rollback in seconds, will
  approve the most destructive one. The fixture's 31 rows and this 50,031-row table roll back in the
  same fraction of a second.
* **What the drill already measured stands at volume.** Rolling `catalog` back destroys 23 of the
  fixture's 31 rows and orphans an import receipt whose item table is gone, and rolling all six apps
  back destroys every project row while `auth_user` keeps the account that wrote them
  ([ADR 0225](ARCHITECTURE_DECISIONS/0225-populated-rollback-drill.md)).

### Locks, and a long `ALTER TABLE` under load

Lock modes were read from `pg_locks` inside the session that held them, then rolled back; the load
numbers come from one writer thread committing an insert every 5 ms — about 195 writes a second —
while the statement ran.

* **What each statement locks.** `ALTER TABLE … ADD COLUMN` takes `AccessExclusiveLock` on the table
  alone. `CREATE INDEX` takes `ShareLock` on the table and `AccessExclusiveLock` on the new index.
  `ALTER TABLE … ALTER COLUMN … TYPE varchar(64)` — a change of type to the *same* width — takes
  `AccessExclusiveLock` on the table, its primary key, its indexes and its TOAST table, because it
  rewrites. `DROP TABLE` of a table nothing references succeeded under `AccessExclusiveLock`;
  `DROP TABLE catalog_productpresentation` was refused with
  `cannot drop table catalog_productpresentation because other objects depend on it`, naming two
  foreign keys in `pricing`, and `TRUNCATE` of the same table was refused with
  `cannot truncate a table referenced in a foreign key constraint`.
* **A rewrite is priced by the table, a metadata change is not.** `ADD COLUMN … integer NOT NULL
  DEFAULT 0` took 0.001 s and 1,344 bytes of WAL on an empty table and 0.001 s and 1,408 bytes on
  the same table with 50,000 rows. `ADD COLUMN … text NOT NULL DEFAULT md5(random()::text)`, which
  rewrites, took 0.007 s and 27,016 bytes at 0 rows, 0.143 s and 17,895,928 bytes at 50,000 rows,
  and **3.631 s and 178,759,168 bytes at 500,000 rows** — a 186,662,912-byte table rewritten into
  174,104,576 bytes. The WAL a rewrite writes is about the size of the table it rewrites.
* **Under load, the rewrite is the long-running statement.** With the writer running, the 500,000-row
  rewrite waited **2.726 s** and blocked exactly **one** writer insert, for **2.703 s**; four writes
  landed while it held the lock. A blocking `CREATE INDEX` over the same rows took 0.102 s and blocked
  one writer for 0.094 s, where the same index over 50,000 rows took 0.013 s and 317,088 bytes. The
  metadata-only `ADD COLUMN` took 0.001 s and blocked nobody. The stall a migration causes is as
  long as the statement that causes it, and the queue behind it is what other sessions see.
* **One open transaction is enough to stop it, and 2 s is enough to cancel it.** With an uncommitted
  `UPDATE` in a second session, the metadata `ALTER TABLE` was cancelled after **2.001 s** with
  `canceling statement due to lock timeout`; a session that was only *reading* — a `SELECT count(*)`
  followed by `pg_sleep(4)` — produced the same cancellation after 2.001 s. A reader blocks a schema
  change exactly as a writer does.
* **The same block, applied to a rollback, leaves the database half undone.** `migrate catalog zero`
  run while a second session was reading was cancelled after **2.551 s**, with 32 tables, 31 applied
  migrations and 29 rows left: the first migration of the cascade — `ingestion 0002`, not a `catalog`
  one — had already committed. This is the `FOR UPDATE` shape ADR 0225 measured, reached instead by an
  ordinary read.
* **No standby exists here to measure against.** `pg_is_in_recovery()` is `false`, `pg_stat_replication`
  has 0 rows and `pg_replication_slots` has 0 rows in this environment, so the standby shape the open
  gate names is unmeasured rather than measured safe.

### The one migration that reads data, and the shape of its failure

`catalog 0008`, applied and rolled back on a throwaway database, with 200,000 synthetic presentations
(1.125 s and 101,036,096 bytes of WAL to insert, a 69,238,784-byte table).

* **Validating 200,000 rows costs almost nothing and writes almost no WAL.** The migration took
  **0.100 s** and wrote **2,464 bytes** of WAL; on an empty table the same migration took 0.068 s and
  wrote 2,440 bytes. Validation is a scan, not a rewrite, so the guide's *"may wait for table locks"*
  is about the `AccessExclusiveLock` it holds for that scan, not about its duration.
* **Under the same write load it blocked nobody.** With the writer committing every 5 ms, the
  migration took 0.096 s, wrote 6,200 bytes, blocked **zero** writes and the slowest write waited
  0.028 s; eight writes landed while it ran.
* **One violating row refuses the whole migration, and the forward direction stays atomic.** With a
  single row carrying `published = true` and `verified_at IS NULL` among 200,081, the migration failed
  after **0.052 s** with
  `IntegrityError: check constraint "catalog_published_requires_verified" of relation
  "catalog_productpresentation" is violated by some row`, wrote **0 bytes** of WAL, left the
  constraint absent and left `django_migrations` at 31 rows — the migration is not recorded. A
  forward migration that fails leaves the schema as it was; a **rollback** that is blocked leaves it
  half undone. The asymmetry is measured, not argued.

### Rolling back Django's own apps

The open gate asks about this explicitly, and the cascade is not what the app names suggest.

* **`migrate sessions zero` is one migration and costs a session table.** 0.156 s, 4,544 bytes of WAL,
  33 tables down to 32 and 32 applied rows down to 31 — `django_session` gone, every project row and
  the staff account intact. The model-derived inspection then reports 1 unresolved table, 0 missing
  foreign keys and 3 missing columns.
* **`migrate contenttypes zero` is the most destructive single command in the tree.** Its cascade is
  **26 migrations, 24 of them project migrations** — `auth` 12, `contenttypes` 2, `catalog` 6,
  `clinical` 2, `ingestion` 2, `pricing` 1, `sources` 1. It took 1.241 s, wrote 346,936 bytes of WAL,
  took the database from 32 tables to **5** and from 31 rows to **6**. The survivors are
  `catalog_productpresentation`, `pricing_pricecandidate`, `staff_security_publicreadwindow`,
  `staff_security_staffloginwindow` and `django_migrations`. Rolling back one of Django's own apps
  destroys more of this schema than rolling back `catalog` does — 26 migrations against 11, five
  surviving tables against 17.
* **`migrate auth zero` afterwards has nothing left to take.** Its cascade is 24 migrations, but the
  run took 0.016 s, wrote 752 bytes and removed nothing: `auth_user` had already gone with
  `contenttypes`.
* **The application keeps answering while the schema is gone.** After all three rollbacks an ORM read
  of `ProductPresentation` still returned 2 rows, and the model-derived inspection reported 28
  unresolved tables, 49 missing foreign keys, 45 missing unique keys, 23 missing check constraints,
  239 missing columns and 51 missing field indexes — a database that is mostly absent is still a
  database some reads succeed on.

### What notices a half-undone schema

Measured on the database the blocked rollback left behind: 32 tables, 31 applied migrations, 29 rows,
`ingestion 0002` unapplied.

| Command or check | Result on the half-undone database |
| --- | --- |
| `manage.py check --database <alias>` | exit 0 |
| `manage.py makemigrations --check --dry-run` | exit 0 |
| `manage.py showmigrations` | exit 0 |
| `manage.py migrate --check` | **exit 1** |
| readiness `migrations_applied` | **false** — `1 migrations are not applied: ingestion.0002_importreceiptitem_importreceipt_manifest_version_and_more` |
| readiness `migration_history_consistent` | true — `every applied migration has a file in this release` |
| model-derived inspection of that alias | 1 unresolved table, 3 missing foreign keys, 2 missing unique keys, 3 missing check constraints, 10 missing columns, 3 missing field indexes |
| `manage.py inspect_postgresql_schema` | cannot be pointed at it: the command takes no `--database` and reads `django.db.connection` |

* **The one signal is indistinguishable from an unmigrated database.** `migrate --check` exits 1 and
  readiness reports one unapplied migration, which is exactly what a database that simply has not been
  migrated forward yet also reports. Nothing in the tree distinguishes "not yet upgraded" from "half
  rolled back", and the four other required checks that fail in this debug environment are settings
  checks, not schema checks.
* **Repair forward restores the schema and not the rows.** `migrate` on the half-undone database took
  **0.198 s**, returned it to 33 tables and 32 applied migrations with an inventory identical to the
  pre-incident one, left the row count at **29 of 31**, and readiness then reported
  `32 migrations applied, none pending`. The two destroyed rows are not part of any repair.

### The copy step, measured at a volume

The gate says no copy of the tables a cascade will drop exists. What one costs, measured on the
50,031-row database with the clients the restore drill uses.

* **A dump of that database is 1,186,535 bytes and takes 0.154 s.** `pg_dump --format=custom
  --no-owner --no-acl` exited 0. The fixture-only database
  [ADR 0232](ARCHITECTURE_DECISIONS/0232-backup-recovery-plan.md) measured is 136,001 bytes, so
  ~1,614 times the rows cost 8.7 times the bytes: the custom format compresses, and an archive size
  does not scale like a table.
* **Restoring it takes 0.327 s and prints nothing.** `pg_restore --exit-on-error --single-transaction
  --no-owner --no-acl` into a database that did not exist exited 0 with 0 bytes on stderr, and the
  target came back with 50,001 rows in the window table and 32 applied migrations.
* **A restore returns the sequences; a replay does not.** The restored `catalog_productpresentation`
  identity sequence read `(2, True)` against 2 restored rows, and the next `INSERT` into the restored
  database **succeeded with no `setval`** — the archive carries `SEQUENCE SET` entries, which is why
  the restore path does not need the manual step
  [ADR 0225](ARCHITECTURE_DECISIONS/0225-populated-rollback-drill.md) required of a replayed copy when
  it concluded *"Identity sequences are part of any restore."* The two copy shapes are not
  interchangeable, and only one of them is written down.
* **The clients are still not part of the repository.** The only `pg_dump` and `pg_restore` on this
  machine are the `pgserver` wheel's bundled 16.2 binaries under
  `.venv/lib/python3.11/site-packages/pgserver/pginstall/bin/`, which is what ADR 0232 measured for
  the fixture and what CI replaces with a wrapper around the mutable `postgres:16` tag.

### What the repository already says about it

* `docs/DEPLOYMENT.md`: *"Set `lock_timeout`, stop the writers, copy the tables the cascade will drop
  before starting, and treat `setval` on the identity sequences as part of any restore"* — four
  instructions, none of them a sequence with an environment, an order and an authorization, and the
  `setval` half of it applies to a replay rather than to a restore.
* `docs/DEVELOPMENT_GUIDE.md`: *"Do not run multiple migration-starting web replicas or use this
  development stack as a production deployment."*
* `docs/OPERATIONS_RUNBOOK.md`: *"Verify migrations, records and application behavior; never restore
  into the running database."*
* `docs/PHASE1_RELEASE_EVIDENCE.md`: *"No backup, restore tool, recovery objective or copy of the
  tables a cascade will drop exists; a failed rollback has to be repaired by hand"*, and the row's
  own list of what is missing — *"it measured no duration, no WAL volume and no long-running
  `ALTER TABLE` under load"*, *"Rollback of Django's own apps, other shapes of concurrency (an open
  writing transaction, `CREATE INDEX CONCURRENTLY`, a running command, a standby) and tested recovery
  from a real staging schema are unmeasured."*
* `docs/CHANGELOG.md`, recording the populated drill: *"Django's own apps are never rolled back, and
  no backup, restore tool, recovery objective, staging environment or rollback **plan** with an owner
  exists."*

## Candidate approach and decisions required

The measured starting point is a forward direction that is atomic and cheap, a backward direction
that is equally cheap and destroys rows without slowing down, one command that can remove 24 project
migrations by name of a Django app, a half-undone state that only `migrate --check` and one readiness
line notice, no timeout on any migration connection, no copy step and no staging environment. Every
option below is contingent on the decisions it names, and none of them is answered here.

1. **Which environment is "staging", and what data is in it?** The tree defines none: the workflow has
   no `environment:` key, `compose.yaml` is a local development stack bound to `127.0.0.1`, and the
   only databases this repository creates are the test database and throwaways. A plan that names an
   environment names something that does not exist yet.
2. **In which order, and may a rollback touch Django's own apps at all?** `migrate contenttypes zero`
   is a 26-migration cascade that takes 24 project migrations with it; `migrate sessions zero` is one
   migration that costs every live session. The order the six project apps are rolled back in is
   derived from the graph, not chosen by anyone.
3. **Where is the copy step, and what shape does it take?** A whole-database custom-format dump of
   50,031 rows is 1,186,535 bytes and 0.154 s, and restores in 0.327 s with its sequences intact; a
   copy of only the tables a cascade will drop is what `docs/DEPLOYMENT.md` asks for and is what ADR
   0225 showed needs `setval` to replay.
4. **Who authorizes a destructive migration, and how is that recorded?** `LOGGING` is `{}`, no model
   among the 24 can hold a migration record, and ADR 0232 measured that nothing records a dump or a
   restore either. The gate asks for an owner and an authorization; this document names neither.
5. **What is the acceptable lock wait, and what happens to requests during it?** A metadata change
   under 195 writes a second waited 0.001 s, a 500,000-row rewrite waited 2.726 s and stalled one
   writer for 2.703 s, and with the drill's 2 s `lock_timeout` a single open read cancelled the
   statement. The request path already bounds itself to a 1 s `lock_timeout`; the migration path does
   not.
6. **What detects a half-undone schema, and who reads it?** `check`, `makemigrations --check` and
   `showmigrations` all exit 0 on one; `migrate --check` exits 1 and readiness names the one unapplied
   migration, which is the same signal an unmigrated database gives. The inspection that would count
   the missing tables cannot be pointed at another database.
7. **What is the recovery objective for a failed migration — repair forward, or restore back?** Repair
   forward took 0.198 s and returned an identical schema with 29 of 31 rows; restoring back is the
   0.327 s restore above, into a database whose target shape no document names.
8. **Which migrations may never be rolled back in place?** All 17 modules are atomic, so none can host
   a `CREATE INDEX CONCURRENTLY`; two data operations reverse to no-ops, so their rollback is a silent
   loss of normalized data; and one validated constraint migration refuses to apply while a single
   violating row exists, which is a forward failure an operator has to fix in data, not in schema.

## Options and what each costs

Prices are counted from the pins and files above, not prototyped.

| Option | What changes | Price, counted | What it still does not answer |
| --- | --- | --- | --- |
| **A. Leave the migration path as it is** | nothing | 0 code files, 0 commands, 0 settings, 0 migration modules and 0 schema pins move; `db_options` stays `{'connect_timeout': 5}` and the two drills stay the only measurements | whether a release told to *"run tests/migrations on staging"* has a staging to run them on, and who authorizes a rollback that costs 0.096 s and 50,000 rows |
| **B. Write the staging sequence down as an ordered procedure** | a numbered sequence — environment, order, copy step, verification, rollback, authorization gate — added to `docs/DEPLOYMENT.md` or `docs/OPERATIONS_RUNBOOK.md` and linked from the evidence row | 2 documents reworded, `daroobank/test_document_links.py` re-pins its 265 documents and its link and anchor counts, `daroobank/test_environment_documentation.py` re-pins any variable the procedure names, the runbook's *"never restore into the running database"* has to be squared with a rollback step, and this plan's own quotation pins move | decisions 1, 3, 4 and 7: a written sequence with no environment, no owner and no objective is the same gap in prose |
| **C. Bound the migration session with a timeout** | `lock_timeout` and `statement_timeout` set for the connection `manage.py migrate` uses, in `db_options` or in a wrapper the procedure names | `daroobank/settings.py`'s `db_options = {'connect_timeout': 5}` moves against the pins that read it, a new variable name lands in `docs/DEPLOYMENT.md`'s table and in `daroobank/test_environment_documentation.py`'s switch inventory, `compose.yaml`'s 12 environment names and `LOCK_FACTS` in `daroobank/test_secret_rotation_plan.py` move if it is delivered by environment, and the drills' explicit `SET lock_timeout = '2s'` stops being the only timeout in the tree | decision 5's second half: a cancelled migration is the half-undone state measured above, so a timeout converts a stall into a repair unless the order is also decided |
| **D. Move index builds out of atomic migrations** | a migration marked `atomic = False`, or a separate non-migration step, so an index can be built `CONCURRENTLY` | the reversibility suite's requirement that each app is one linear chain and that every data operation declares an explicit reverse has to cover a new kind of step, `MIGRATION_COUNTS` and the 17-module count move, the 111-index inventory gains an index whose creation is not recorded in `django_migrations`, and `daroobank/test_populated_rollback_drill.py`'s reapply-equality assertion has to tolerate an index that no migration owns | decision 8: a concurrent build is not atomic, so a failure leaves an `INVALID` index that nothing in the tree counts or removes |
| **E. Take a copy before every destructive migration and drill restoring it** | the copy step the deployment guide already asks for, plus a drill of the restore into a database in use | the whole of [the backup and recovery plan](BACKUP_RECOVERY_PLAN.md) option E, whose price is counted there: the runbook's prohibition, the drill's *"never an existing database"* policy and `test_target_name_collision_is_not_dropped` are contradicted, `daroobank/test_backup_guide.py`'s six-step trace is re-pinned, and 1,186,535 bytes per 50,031 rows becomes a recurring artifact with the custody question ADR 0232 leaves open | decisions 3, 4 and 7: a copy nobody is authorized to restore, into a target shape no document names |
| **F. Make a half-undone schema detectable** | `inspect_postgresql_schema` takes `--database`, or a pre- and post-migration schema assertion is added to the procedure, so the state measured above is reported rather than inferred from one unapplied migration | `catalog/management/commands/inspect_postgresql_schema.py` (28 lines, no `add_arguments`, bound to `django.db.connection`) and its test module move, the readiness command's ten required checks gain or reuse one, `daroobank/test_populated_rollback_drill.py`'s `inspect()` helper is affected, and the 12-command count in `daroobank/test_secret_rotation_plan.py` moves if a command is added rather than extended | decision 6's second half: a detector says a schema is half undone, and the answer to that is a decision about repair forward versus restore back |
| **G. Declare staging migration and rollback out of Phase 1 scope** | `docs/DEPLOYMENT.md`, `docs/OPERATIONS_RUNBOOK.md`, `docs/TESTING_STRATEGY.md` and `docs/PHASE1_RELEASE_EVIDENCE.md` stop asking for a staging migration and say what is accepted instead | 4 documents reworded, this plan's quotation pins and `daroobank/test_document_links.py` re-pin the wording they quote, ADR 0225's consequences stay as the only measured statement, and the evidence row's *"run tests/migrations on staging and validate rollback compatibility"* becomes a sentence about a local development stack | whether an operator told to *"rerun in staging, then explicitly resume from a safe checkpoint"* may do it at all, which is a decision for an owner and not for this file |

## Required behavior before any staging migration

1. **Name the environment before naming the order.** Nothing in this tree is a staging environment:
   no `environment:` key in the workflow, one compose file bound to `127.0.0.1`, and every database
   the repository creates is a test database or a throwaway.
2. **Assume the rollback direction is fast and destructive, and gate it on rows rather than
   seconds.** 0.096 s and 6,680 bytes of WAL removed 50,000 rows; 0.156 s removed every session;
   1.241 s removed 24 project migrations by way of `contenttypes`.
3. **Treat `migrate contenttypes zero` and `migrate auth zero` as destructive of project schema.** The
   cascade is derived from the graph, is 26 and 24 migrations long, and leaves five tables.
4. **Decide the timeout before the incident, and decide what a cancelled migration means.** With no
   timeout a rewrite over 500,000 rows holds `AccessExclusiveLock` for 2.726 s while writers queue;
   with a 2 s timeout the same class of statement is cancelled and, in the rollback direction, leaves
   31 of 32 migrations applied and a schema that only `migrate --check` reports.
5. **Stop the readers as well as the writers.** A session that only ran `SELECT count(*)` and
   `pg_sleep(4)` cancelled a metadata `ALTER TABLE` after 2.001 s and a rollback after 2.551 s.
6. **Copy in a shape that can be restored.** A custom-format archive returns its sequences and needed
   no `setval` in the measured run; a replayed copy of rows does not, and the guide's instruction to
   *"treat `setval` on the identity sequences as part of any restore"* is true of the second shape
   only.
7. **Verify against the schema, not the migration table.** After a repair forward the schema inventory
   was identical, readiness reported `32 migrations applied, none pending`, and 2 of 31 rows were still
   gone — so every verification that reads `django_migrations` passes on a database that lost data.

## Verification before any enablement

- Repeat the direction experiment on synthetic data in throwaway databases and re-measure every number
  in this document: the forward, per-app and reapply durations and WAL volumes, the 50,000-row
  rollback, the metadata and rewriting `ALTER TABLE` at three volumes, the lock modes of each
  statement, the writer stall under load, the validated constraint migration at 200,000 rows and its
  refusal against one violating row, the three Django-app cascades, the half-undone command table and
  the dump and restore at volume.
- Confirm that a blocked rollback still leaves 31 of 32 migrations applied with the first migration of
  the cascade — `ingestion 0002` — already committed, that `check`, `makemigrations --check` and
  `showmigrations` still exit 0 on it, and that repairing forward still restores the schema without
  restoring a row.
- Confirm that no migration module has gained `atomic = False`, that the two `RunPython` reverses are
  still no-ops, that `db_options` is still `{'connect_timeout': 5}`, and that no staging environment,
  migration-order control or copy step has appeared.
- Confirm that the two existing drills still pass unchanged — 14 tests, about 32 s against the
  synthetic server, no database left behind — and that this plan's suite reports the same counts they
  pin.
- Verify that no model, command, setting, document or workflow step this plan names as absent has
  appeared, and that the counts in `daroobank/test_database_migration_plan.py` are recomputed rather
  than deleted if a chosen option lands.
- Record named owners and evidence for operational, security and release approval. No staging
  environment, no migration order, no copy procedure, no claim of Phase 1 completion and no rollback
  authorization follows from implementing these tests.
