# 0235 — the database connection plan, and what a connection in this repository actually costs

Date: 2026-11-27
Status: accepted
Suite: `daroobank/test_database_connection_plan.py` (15 tests, ~1.1 s, 2 of them on the synthetic PostgreSQL database)

## Context

[PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) carries two connection-shaped gaps in
the open cell of its data-model row: *"no representative volume, connection pool, vacuum or
checkpoint pressure and no real workload was measured"* and *"a standby cannot be measured here
because this environment has no replica (`pg_is_in_recovery()` is false and both replication views
are empty)"*. [DEPLOYMENT.md](../DEPLOYMENT.md) documents one connection variable and one connection
option — *"integer seconds. Persistent connections need pooling, failover and idle-timeout review
before they are used in production"* and *"`verify-full` for any connection that leaves the host, so
the server certificate is checked and the link is encrypted in transit; unset means the driver
decides"* — and [OPERATIONS_RUNBOOK.md](../OPERATIONS_RUNBOOK.md) says of the readiness report that
it *"serves no request, checks nothing about collected static files, logging, clocks, connection
pooling, replicas or external dependencies"*, which is the same limit [ADR
0217](0217-deployment-readiness-report.md) records as *"Nothing verifies static files were
collected, logging is routed, clocks are synchronized, connection pooling is sized, replicas are
healthy, the process can actually serve a request, or that any external dependency is reachable."*
[ADR 0222](0222-documented-environment.md) notes that *"whether connections are persistent
(`POSTGRES_CONN_MAX_AGE`) were documented only in a development template and a development guide,
both of which say they are not production configuration."* [SECURITY.md](../SECURITY.md) requires
*"least-privilege DB/worker credentials"*, [DEVELOPMENT_GUIDE.md](../DEVELOPMENT_GUIDE.md) tells a
developer to *"provision a PostgreSQL database/role or start only the Compose `db` service"*, and
[ADR 0233](0233-database-migration-plan.md) limits its own load measurement to one writer thread
*"with no readers, no connection pool, no vacuum, no replication and no checkpoint pressure"* while
recording that *"no migration connection carries a timeout (`db_options` is `{'connect_timeout': 5}`)"*.

What no document contained was a measurement: how many connections a request opens and what they
cost, how far a process gets before the server refuses it and which role is refused first, what
bounds a statement, a lock wait or an idle transaction when the module that runs it did not bound
one, which privileges the role on the other end of every connection actually has, what a deletion
leaves behind for autovacuum, what an index is worth against a sequential scan, what a write costs
in WAL, and whether a base backup of this cluster works at all.

## Decision

Record [DATABASE_CONNECTION_PLAN.md](../DATABASE_CONNECTION_PLAN.md) as the measurement and the
proposal for this gate, in the form [ADR 0227](0227-read-audit-plan.md), [ADR
0229](0229-attribution-gap-plan.md), [ADR 0230](0230-mfa-implementation-plan.md), [ADR
0231](0231-secret-rotation-plan.md), [ADR 0232](0232-backup-recovery-plan.md), [ADR
0233](0233-database-migration-plan.md) and [ADR 0234](0234-network-tls-plan.md) established: an
unowned proposal, priced options, numbered decisions, no implementation. This record changes no
behavior. The plan states **Nothing is implemented.** — no connection pool, no `CONN_MAX_AGE`
change, no `statement_timeout`, no `lock_timeout`, no `idle_in_transaction_session_timeout`, no
`keepalives`, no `tcp_user_timeout`, no new role, no new grant, no new index, no new command, no new
environment variable and no new dependency — and this suite holds it to that claim, to its
twenty-four quotes (each must exist both in the plan and in the document it comes from), to its
measured numbers, and to the tree still having the shape those numbers were taken from. The eight
decisions — which role connects and who owns the schema, what the connection lifetime is, where the
pool is and which ceiling it protects, what bounds a statement, a lock wait and an idle transaction
and at which layer, what bounds a connection that stops answering, who may maintain the database,
what the recovery objective is, and which query plans may be sequential — stay open; answering them
is not this record's business.

## Measured behavior

One measurement run, nine fresh processes plus the test process, all on this tree, against the
synthetic PostgreSQL 16.2 server on throwaway databases and throwaway roles that each experiment
created and dropped:

* **A request at the default lifetime opens a connection, and the connection is most of the
  request.** Twenty `/health/ready/` requests through `daroobank.wsgi.application` opened **20**
  connections at `POSTGRES_CONN_MAX_AGE=0` in 82 ms (**4.10 ms** each) and **1** connection at
  `CONN_MAX_AGE=60` in 34 ms (**1.68 ms** each), all twenty responses `200 OK` in both: the
  connection cycle is **2.42 ms** of a 4.10 ms request. Directly, over 20 samples each: connect and
  close **1.88 ms** mean (1.82 median, 1.56–2.55) and **1.84 ms** in a second run, connect plus
  `select 1` plus close **2.22 ms** mean (2.39 median, 1.72–2.67) and **2.12 ms** in the earlier
  run, and `select 1` on an open connection **0.11 ms** mean (0.08 median, 0.06–0.51). Two
  instruments were rejected first: 300 requests through `django.test.Client` opened **1** connection
  and moved `pg_stat_database.sessions` by **1** at every lifetime, because `ClientHandler.__call__`
  disconnects `close_old_connections` from `request_started`, and the same 300 inside
  `manage.py shell` opened **0** because the shell already holds one.
* **`connect_timeout` bounds the handshake and nothing after it.** Against a local listener that
  accepted the socket and never answered the startup packet, `connect_timeout=5` failed after
  **5,001.98 ms**, `1` after **2,001.65 ms**, `30` after **30,001.09 ms** and `0` after
  **130,001.02 ms** — the kernel's `tcp_syn_retries = 6`, not libpq. Refusals that do not wait are
  immediate: a closed port **0.32 ms**, an unknown role **1.52 ms**, an unknown database
  **1.55 ms**, an unresolvable name **5.68 ms**. The parameters Django builds are exactly
  `client_encoding`, `connect_timeout`, `context`, `dbname`, `host`, `port`, `prepare_threshold` and
  `user` — no `application_name`, no `keepalives`, no `tcp_user_timeout`, no `target_session_attrs` —
  and libpq accepted all four of the missing ones through the same path. `SO_KEEPALIVE` read **0** in
  every configuration because `POSTGRES_HOST` is a socket directory, `listen_addresses` is empty and
  TCP to `127.0.0.1:5432` is refused, so keepalive behavior is unmeasurable here.
* **The server bounds no wait; four modules bound their own.** `statement_timeout`, `lock_timeout`,
  `idle_in_transaction_session_timeout` and `idle_session_timeout` are all **0** and
  `deadlock_timeout` is **1000** ms. `pg_sleep(2)` ran to completion in **2,003 ms**; inside
  `SET LOCAL statement_timeout = '500ms'` it raised `QueryCanceled` after **501 ms**. A waiter on a
  row another session held `FOR UPDATE` was still waiting at **3.003 s** —
  `('active', 'Lock', 'transactionid', 3.003)` — and was freed only by `pg_cancel_backend`, raising
  `QueryCanceled` after **3,007 ms**; with `SET LOCAL lock_timeout = '300ms'` it raised
  `LockNotAvailable` after **301 ms** and stayed retryable. A transaction idle after one statement
  was still open at **6.009 s** holding **4** granted locks, and nothing closed it. The bounds that
  exist are **7** `SET LOCAL` statements in **4** non-test modules — `daroobank/health.py` (1),
  `staff_security/management/commands/cleanup_staff_login_windows.py` (2),
  `staff_security/read_limit.py` (2) and `staff_security/throttle.py` (2) — carrying `lock_timeout`
  `'1s'` three times and `statement_timeout` `'2s'` three times and `'1s'` once;
  `idle_in_transaction_session_timeout` appears **0** times in project code and **0** times in the
  four modules, while the test suites carry 130 mentions of `lock_timeout` and 76 of
  `statement_timeout`.
* **The ceiling is 100, a non-superuser reaches 97, and a superuser locks the operator out.** With
  `max_connections` **100** and `superuser_reserved_connections` **3**, a `LOGIN NOSUPERUSER` role
  held **97** connections and then received `FATAL: remaining connection slots are reserved for
  roles with the SUPERUSER attribute` after **1.92 ms**; the superuser role held **100** and then
  received `FATAL: sorry, too many clients already` after **1.01 ms** — as an operator and as a
  non-superuser alike, because the reserved slots are reserved for the role already holding them.
  While the non-superuser held all 97, a superuser operator connected successfully. Opening one more
  connection at 97 cost **16.90 ms**. Those 97 idle backends reported **1,003,684 kB** of resident
  set between them (mean 10,347 kB) and **107,105 kB** of proportional set (mean **1,104 kB**,
  1,087–1,107): summing RSS overstates an idle backend by **9.4 times**.
* **One superuser role owns everything, and a runtime role's maintenance commands succeed without
  doing anything.** The cluster has exactly **one** non-system role, `postgres`, superuser with
  `createrole`, `createdb`, `replication` and `bypassrls` and `rolconnlimit` −1; it owns all 33
  tables, **0** grants exist to `PUBLIC`, and from it a session read a `SCRAM-SHA-256` hash out of
  `pg_authid`, dropped and recreated a project table, created a database, read all **360** rows of
  `pg_settings` and installed the `vector` extension — one of only **2** available, with `plpgsql`
  1.0 the only one installed. A throwaway `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE` role with
  `SELECT, INSERT, UPDATE, DELETE` read, inserted, updated, deleted and advanced a sequence, read
  **340** settings, and was refused `pg_authid`, `pg_shadow`, `CREATE TABLE`, `CREATE DATABASE`,
  `CREATE SCHEMA`, `ALTER TABLE`, `CREATE INDEX` and `CREATE INDEX CONCURRENTLY`, `TRUNCATE`,
  `REINDEX`, `ALTER SYSTEM`, `SET ROLE` and `SET SESSION AUTHORIZATION`. Its `VACUUM` printed
  `WARNING: permission denied to vacuum "django_migrations", skipping it`, still exited **0**, and
  left `vacuum_count` at **0** with `last_vacuum` `NULL`; a `VACUUM (FULL)` after 20,000 inserted
  and deleted rows left the table at exactly **1,048,576** bytes. Its `GRANT TRUNCATE` to itself
  printed `WARNING: no privileges were granted`, still exited **0**, and left
  `has_table_privilege(…, 'TRUNCATE')` **false** and the access control list unchanged; granting to
  `PUBLIC`, granting with the grant option and revoking from itself were equally inert.
  `manage.py migrate` as that role into an empty superuser-owned database with `USAGE` but not
  `CREATE` on the schema failed with `MigrationSchemaMissing: Unable to create the django_migrations
  table (permission denied for schema public)`, and with `CREATE` granted — inside the target
  database, since `pg_namespace` is per-database — it applied all **32** migrations and **owned
  everything it created**, all **33** tables and all **111** indexes. `manage.py test` on a database-touching module
  exited **2** with *"Got an error creating the test database: permission denied to create
  database"*, while a module with no database-dependent test passed as either role because Django
  creates no test database for it. `pg_dump -Fc` wrote **145,667 bytes** with the grants and failed
  on the first table without them. A non-superuser reads another role's backend in
  `pg_stat_activity` as `<insufficient privilege>` with `state`, `wait_event` and `backend_start`
  `NULL`, where the superuser reads `active`, `select pg_sleep(4)` and `PgSleep`; it is not a member
  of `pg_signal_backend`, can cancel its own role's backend and is refused for a superuser's.
* **A deletion returns nothing to the filesystem, and autovacuum does not either.** On a throwaway
  50,000-row table: inserting took 400–440 ms and **9,312 kB**; deleting 25,000 rows took 13–14 ms,
  left `count(*)` at 25,000 and the size at **9,312 kB**; `VACUUM (ANALYZE)` took **25 ms** and left
  **9,320 kB**; `VACUUM FULL` took **48 ms** and left **4,664 kB**. `n_dead_tup` read **0**
  immediately after the delete and **0** two seconds later, autovacuum ran after **65 s** and the
  size stayed 9,320 kB, and the threshold that triggers it at that volume is **10,050** dead tuples.
* **No foreign key is unindexed, and the next one would cost 480 kB to fix.** All **50** foreign keys
  in the schema have an index or a covering prefix. On a synthetic 50,000-row child whose only index
  was its primary key, the children of one parent ran as a `Seq Scan` with **Execution Time
  2.666 ms**, `shared hit=319` and `Rows Removed by Filter: 49990` (wall 3.14 ms), and as a `Bitmap
  Heap Scan` with **Execution Time 0.068 ms** and `shared hit=13 read=2` (wall 0.48 ms) once
  `CREATE INDEX` had run for **17–18 ms** and **480 kB**; one cascading parent delete cost **3.51 ms**
  without the index and **0.77 ms** with it.
* **WAL per write is not a constant, and there is no archive to recover from.** 10,000 inserts in one
  statement wrote **2,619,752 bytes**; 1,000 single-row updates in one transaction wrote **176,896
  bytes** and the same 1,000 with a transaction each wrote **94,520 bytes**, **46.6 % less**; four
  consecutive passes of the same updates read **296,928 → 200,328 → 182,776 bytes** from
  `pg_stat_wal`, the first pass after a checkpoint costing **247,672 bytes** with **14,393** records
  and **19** full-page images. The cluster ended at 721,277 WAL records, 15,665 full-page images,
  140,870,044 bytes and 2,280 `wal_buffers_full`, with **8** timed checkpoints against **14**
  requested ones and 7,173 buffers written at checkpoints against 16,952 by backends. `pg_wal` held
  **67,113,020 bytes**, and dropping the probe database moved the data directory from **126,007,951**
  to **104,884,778** bytes — a drop does not return the WAL it wrote. `pg_is_in_recovery()` is
  **false**, `pg_stat_replication` is empty, there are **0** replication slots, `archive_mode` is
  **off**, `archive_command` reads `(disabled)` and `restore_command` is empty. `pg_basebackup -Ft
  -z` of the whole cluster nevertheless exited **0** in **1,214 ms** and wrote **8,058,024 bytes** in
  three files — `backup_manifest`, `base.tar.gz` and `pg_wal.tar.gz` — which with no archive recovers
  to the instant it was taken and to no point after it.

## Red checks

After the plan, the suite and the neighbour patches existed, twenty-six mutations were applied one
at a time to a byte-identical backup of the tree (`sha256sum` recorded before, re-verified after
every restore, final check rc=0), each followed by a run of
`daroobank/test_database_connection_plan.py`, each run required to fail. Every mutation went red and
the suite ended green:

1. Plan: `## What is true today, measured` renamed — `test_the_plan_states_its_own_shape`.
2. Plan: `### The ceiling, and who is locked out at it` renamed —
   `test_the_plan_states_its_own_shape`.
3. Plan: decision 5 unnumbered — `test_the_plan_states_its_own_shape`.
4. Plan: option `**E. Put a pooler in front**` unbolded and relabelled —
   `test_the_plan_states_its_own_shape`.
5. Plan: "The selected approach is to raise `POSTGRES_CONN_MAX_AGE`." inserted —
   `test_the_plan_is_an_unowned_proposal_that_implements_nothing` (forbidden-selection list).
6. Plan: `**Nothing is implemented.**` deleted —
   `test_the_plan_is_an_unowned_proposal_that_implements_nothing`.
7. Plan: the DEPLOYMENT `POSTGRES_CONN_MAX_AGE` quote deleted —
   `test_the_plan_quotes_the_requirements_it_is_priced_against`.
8. DEPLOYMENT.md: the quoted `POSTGRES_CONN_MAX_AGE` sentence reworded in its source —
   `test_the_plan_quotes_the_requirements_it_is_priced_against`.
9. Plan: the ADR 0217 pooling quote deleted —
   `test_the_plan_quotes_the_requirements_it_is_priced_against`.
10. Plan: `**20 for 20 requests**` became `21 for 20 requests` —
    `test_the_plan_states_the_measured_numbers`.
11. Plan: `2.42 ms per request` became `2.24 ms per request` —
    `test_the_plan_states_the_measured_numbers`.
12. Plan: `5,001.98 ms` became `5,100 ms` — `test_the_plan_states_the_measured_numbers`.
13. Plan: every `130,001.02` became `130,000` — `test_the_plan_states_the_measured_numbers`.
14. Plan: the ceiling table's `97` became `98` — `test_the_plan_states_the_measured_numbers`.
15. Plan: `1,003,684 kB` became `1,003,648 kB` — `test_the_plan_states_the_measured_numbers`.
16. Plan: `1,104 kB` became `1,014 kB` — `test_the_plan_states_the_measured_numbers`.
17. Plan: every `9,320` became `9,230` — `test_the_plan_states_the_measured_numbers`.
18. Plan: `8,058,024 bytes` became `8,058,420 bytes` —
    `test_the_plan_states_the_measured_numbers`.
19. Plan: `**50** foreign keys` became `49` — `test_the_plan_states_the_measured_numbers`.
20. settings.py: `db_options = {'connect_timeout': 5}` became `{'connect_timeout': 10}` —
    `test_the_plan_quotes_the_requirements_it_is_priced_against` and
    `test_the_settings_shape_is_the_measured_one`.
21. settings.py: the `POSTGRES_CONN_MAX_AGE` default `'0'` became `'60'` — the same two tests.
22. settings.py: a new `os.environ.get('POSTGRES_POOL_SIZE')` read appended —
    `test_the_settings_shape_is_the_measured_one`, which counts the environment names the settings
    read.
23. requirements.txt: a `psycopg_pool` line appended —
    `test_no_new_command_model_or_dependency_exists` and `test_the_tree_still_contains_no_pooler`.
24. staff_security/throttle.py: one of its two `SET LOCAL` statements deleted —
    `test_the_timeout_inventory_is_the_measured_one`.
25. Plan: the `**33** tables and **111** indexes` the migrating role owns became `32` and `110` —
    `test_the_plan_states_the_measured_numbers`.
26. Plan: *"`pg_namespace` is per-database"* became *"`pg_namespace` is shared"* —
    `test_the_plan_states_the_measured_numbers`.

Two mutations initially slipped, and both slips were the mutation's fault rather than the suite's:
the plan states `130,001.02 ms` in three places and `9,320 kB` in three, and replacing the one
occurrence in the table left the other two, so the number the suite pins was still there. Both were
rewritten to change every occurrence and both then went red. The suite itself failed on its first run
against the documents written that morning — 25 assertions over 15 tests — and four of those failures
were its own: the verification list has seven items, not six; the tree holds 741 files, not the 740
copied from a count taken before this delivery's three files existed; the count of timeout tokens in
the test modules counted this suite's own file, which names the tokens it forbids, until the suite
excluded its own three files; and the forbidden-selection list was applied to the whole record, which
names those phrases in this section. Each was fixed in the suite or in the documents before the red
check above was run, and the record's own `Suite:` line and quotation count were recounted at the
same time. Mutations 25 and 26 were added after that run, when a second privilege probe re-measured
what the migrating role owns — all 33 tables and all 111 indexes carry it as `relowner` — and
established that the `CREATE` grant has to be made inside the target database, because
`pg_namespace` is per-database and a grant made while connected to another database leaves the same
`MigrationSchemaMissing` behind. Both numbers are pinned and both mutations were run red.

## Consequences

* The data-model row in [PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) now carries the
  connection, ceiling, privilege, vacuum, index, WAL and base-backup measurements in its evidence
  cell while every sentence [ADR 0233](0233-database-migration-plan.md) put there stays verbatim,
  because that record's suite pins them; the open half names the two gaps this record closes as
  measured and states that the eight decisions remain unassigned work.
* `docs/DEPLOYMENT.md`, `docs/OPERATIONS_RUNBOOK.md`, `docs/SECURITY.md`,
  `docs/TESTING_STRATEGY.md`, `docs/DEVELOPMENT_GUIDE.md` and `docs/DATABASE_SCHEMA.md` each gained a
  sentence that names what was measured and links the plan and this record; `docs/CHANGELOG.md`
  carries the entry and `docs/PHASE1_RELEASE_EVIDENCE.md` carries both cells of its data-model row.
* The connection path now has a measured inventory — a per-request cost, a ceiling, a role boundary
  and a timeout inventory — and a suite that re-reads the settings shape, the `SET LOCAL` count, the
  absence of any pooler and four catalog facts on every run, which is the connection counterpart of
  the schema inventory [DATABASE_SCHEMA.md](../DATABASE_SCHEMA.md) and the migration measurements
  [ADR 0233](0233-database-migration-plan.md) already carry: documentation of what exists, not a
  policy for what should.
* Two global pins move with this record and must be recounted from the tree rather than from this
  text: the test-module count in `daroobank/test_database_migration_plan.py`,
  `daroobank/test_mfa_implementation_plan.py` and `daroobank/test_secret_rotation_plan.py`, the
  `docs/` markdown count in `daroobank/test_database_migration_plan.py` and
  `daroobank/test_backup_recovery_plan.py`, and the document, record, link and `Suite:` line counts
  in `daroobank/test_document_links.py`. After this record the tree holds 269 documents, 235
  records, 25 `Suite:` lines, and the two test-module counts and the two markdown counts now count
  242 and 241, and 268.
* One pin in the MFA suite moves for a reason of its own: `LOGIN_ROUTE_TESTS` is 45, not 44, because
  `daroobank/test_database_connection_plan.py` names
  `staff_security/management/commands/cleanup_staff_login_windows.py` — one of the four modules whose
  `SET LOCAL` statements it counts — and that module matches the `staff_login` pattern the MFA suite
  uses to count the test modules downstream of the login route. The connection suite does not test
  the login route; the count is of modules that name it.
* No option was chosen: no connection lifetime, no pool, no timeout, no role, no grant and no index
  follows from this record, and the eight options in the plan are priced inventories rather than
  recommendations.
* Nothing here configures a connection, a pool, a timeout, a role or a dependency. Any of those
  remains a change for whoever answers the decisions, with its price already counted in the plan's
  option table — including the price that option E puts on the four modules whose `SET LOCAL`
  statements a transaction-mode pooler would have to carry, and the price option G puts on
  migrations, indexes, `TRUNCATE`, `pg_dump` and the test runner.

## Limitations

- **Everything is synthetic and local.** One run on one machine, throwaway databases and throwaway
  roles, a synthetic PostgreSQL 16.2 server started by a tool that is not in the runtime lock, and
  no browser, no proxy, no replica and no archive. The durations say what this cluster did once, not
  what a deployment will do.
- **The socket is not a network.** `POSTGRES_HOST` is a Unix socket directory and `listen_addresses`
  is empty, so every connection cost here excludes a TCP handshake, an authentication exchange over a
  network and any TLS negotiation, and `SO_KEEPALIVE` could not be observed at all. A deployment that
  connects over TCP pays more per connection than the 1.88 ms measured here, by an amount this run
  could not produce.
- **The request loop is one process, one thread, one worker.** Twenty sequential requests through the
  WSGI application measure the lifecycle Django implements, not concurrency: no fork, no thread pool,
  no queue and no contention, so the 2.42 ms saving at a lifetime above zero is per request in one
  worker and says nothing about how many slots a deployment of N workers holds.
- **The ceiling was reached by holding connections, not by serving requests.** One process opened 97
  and then 100 connections and kept them idle; no worker, no pooler and no request queue was
  involved, and the 1,104 kB proportional set is an idle backend of this cluster with 128 MB of
  `shared_buffers`, not a busy one.
- **The role boundary was measured against one throwaway role in one throwaway database.** The grants
  were the ones this probe issued; a deployment that grants differently, that makes the runtime role
  a member of `pg_signal_backend` or `pg_read_all_stats`, or that lets the runtime role own the
  schema, gets a different boundary. The `WARNING`-and-exit-0 behavior of `VACUUM` and `GRANT` is
  PostgreSQL's, not this tree's, and would follow any such role.
- **Bloat, WAL and the plan measurements used synthetic tables.** 50,000 rows of one narrow table and
  a 50,000-row child are larger than the fixture and smaller than a pharmacy catalog, and none of it
  has the row width, the index count or the fragmentation of real data. The rewriting `ALTER TABLE`
  numbers are quoted from [ADR 0233](0233-database-migration-plan.md) rather than re-run.
- **No option was evaluated for correctness or lawfulness.** Whether connections should persist, what
  a statement may cost, who may hold superuser, whether an archive must exist and which indexes are
  worth their write cost are questions for named owners; the eight options are priced inventories,
  not recommendations, and the eight decisions stay open.
- **The suite pins documents, counts, the settings shape and four catalog facts.** It cannot tell
  whether a pooler would help, whether a lifetime above zero would survive a deployment's restarts,
  or whether the plan is the right plan; forcing the questions and the counts is all it does.
