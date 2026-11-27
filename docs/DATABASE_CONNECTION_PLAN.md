# The database connection plan, and what a connection in this repository actually costs

`docs/DEPLOYMENT.md` documents one connection variable and one connection option: the
`POSTGRES_CONN_MAX_AGE` row says *"integer seconds. Persistent connections need pooling, failover and
idle-timeout review before they are used in production"*, and the `POSTGRES_SSLMODE` row says
*"`verify-full` for any connection that leaves the host, so the server certificate is checked and the
link is encrypted in transit; unset means the driver decides"*. `.env.example` carries the same
variable with the comment *"Integer seconds, 0 through 31536000. Persistent connections need
operational review."* `docs/OPERATIONS_RUNBOOK.md` says of the readiness report that it *"serves no
request, checks nothing about collected static files, logging, clocks, connection pooling, replicas
or external dependencies"*, and [ADR 0217](ARCHITECTURE_DECISIONS/0217-deployment-readiness-report.md)
lists among the report's limits that *"Nothing verifies static files were collected, logging is
routed, clocks are synchronized, connection pooling is sized, replicas are healthy, the process can
actually serve a request, or that any external dependency is reachable."*
[ADR 0222](ARCHITECTURE_DECISIONS/0222-documented-environment.md) records that *"whether connections
are persistent (`POSTGRES_CONN_MAX_AGE`) were documented only in a development template and a
development guide, both of which say they are not production configuration."*
`docs/SECURITY.md` requires *"least-privilege DB/worker credentials"*, `docs/DEVELOPMENT_GUIDE.md`
tells a developer to *"provision a PostgreSQL database/role or start only the Compose `db` service"*,
and [ADR 0233](ARCHITECTURE_DECISIONS/0233-database-migration-plan.md) limits its own load
measurement to one writer thread *"with no readers, no connection pool, no vacuum, no replication and
no checkpoint pressure"*, and `docs/PHASE1_RELEASE_EVIDENCE.md` carries the same fact and the same
two gaps in its data-model row — *"no migration connection carries a timeout (`db_options` is
`{'connect_timeout': 5}`)"*, *"no representative volume, connection pool, vacuum or
checkpoint pressure and no real workload was measured"* and *"a standby cannot be measured here
because this environment has no replica (`pg_is_in_recovery()` is false and both replication views are
empty)"*.

So the repository has one documented connection variable, one connection option, four modules that
bound their own statements, and no answer to the five questions a connection actually raises in
production: **how long does a connection live, what does opening one cost per request, where is the
ceiling and who reaches it first, what bounds a statement or a lock wait when the module did not
bound it, and which role is on the other end?**
[ADR 0235](ARCHITECTURE_DECISIONS/0235-database-connection-plan.md) records what this document says
and what it measures. It is not a capacity plan, not a pooler, not a privilege model and not a
recovery objective.

This document is a **proposal**. It has no owner and no approval, so it must not be read as a
decision, and it must not treat one measurement run on a synthetic server as a capacity budget. Its
prices are counted from the pins and files below, not prototyped: no pooler was installed and
removed, no role was created in a deployment and no timeout was written into a server configuration
— but the measurements **were** performed, on synthetic data in throwaway databases against throwaway
roles that no longer exist, and every number below is the result of those runs.

**Nothing is implemented.** No connection pool, no `CONN_MAX_AGE` change, no `statement_timeout`, no
`lock_timeout`, no `idle_in_transaction_session_timeout`, no `keepalives`, no `tcp_user_timeout`, no
new role, no new grant, no new index, no new command, no new environment variable and no new
dependency exists in this tree because of this file. The measurements were performed with the
`manage.py migrate` and `manage.py test` commands the tree already has, the `pg_dump`, `pg_restore`
and `pg_basebackup` clients the restore drill already uses, and a WSGI request loop that no longer
exists, against databases and roles that no longer exist.

## What is true today, measured

Counted on this tree by reading `daroobank/settings.py`, `compose.yaml`, `.env.example`,
`requirements.txt` and the four modules that bound their own statements, and by running every
experiment below against the synthetic PostgreSQL 16.2 server on throwaway databases and throwaway
roles that each experiment created and dropped. Durations and byte counts belong to **one measured
run** on one machine and are quoted as such, never as a budget. They are pinned by
`daroobank/test_database_connection_plan.py`.

### The connection lifecycle per request

`POSTGRES_CONN_MAX_AGE` exists, is read as `int(os.environ.get('POSTGRES_CONN_MAX_AGE', '0'))` and
so defaults to `'0'`, and is validated to the inclusive range 0..31,536,000 together with the
port, one `try` block whose only refusal message is *"Invalid PostgreSQL port or connection
lifetime"*. The cap has a stated reason — *"A finite cap also prevents
huge integers from overflowing Django's monotonic close deadline when a database connection is
opened."* — and `CONN_HEALTH_CHECKS` is `True`. Twenty requests for
`/health/ready/` — the one route that always runs exactly one `SELECT` inside an atomic block that
sets a one-second server-side timeout — were driven through `daroobank.wsgi.application` in a fresh
process for each configuration:

| `POSTGRES_CONN_MAX_AGE` | connections opened | wall time | per request | `close_at` after the first request |
| --- | --- | --- | --- | --- |
| `0` (the default, what `compose.yaml` and `.env.example` set) | **20 for 20 requests** | 82 ms | **4.10 ms** | already in the past: −0.0044 s |
| `60` | **1 for 20 requests** | 34 ms | **1.68 ms** | 59.9954 s, and 59.9822 s after the twentieth |

Every response was `200 OK` with the body `ok` in both configurations, so the difference is the
connection cycle alone: **2.42 ms per request**. The same cost measured directly over the Unix
socket this environment uses, 20 samples each: opening and closing a connection **mean 1.88 ms,
median 1.82 ms, min 1.56 ms, max 2.55 ms** in one run and **mean 1.84 ms, median 1.95 ms, min
1.39 ms, max 2.08 ms** in a second; opening, running `select 1` and closing **mean 2.22 ms, median
2.39 ms, min 1.72 ms, max 2.67 ms** and in the earlier run **mean 2.12 ms, median 2.03 ms, min
1.84 ms, max 2.72 ms**; and `select 1` on a connection that is already open **mean 0.11 ms, median
0.08 ms, min 0.06 ms, max 0.51 ms**. A request at the default lifetime therefore spends roughly
twenty times as much on the connection as on the query it makes.

Two instruments were rejected before this one was trusted. The Django test client is not a faithful
instrument for connection lifecycle: `ClientHandler.__call__` disconnects `close_old_connections`
from `request_started` for the duration of the call, so 300 requests through `django.test.Client`
opened **1** connection and moved `pg_stat_database.sessions` by **1** at `CONN_MAX_AGE` 0, 60 and
31,536,000 alike. A `manage.py shell` session is not one either: it already holds an open
connection, so the same 300 requests inside it opened 0 new ones and committed 2 transactions. The
mechanism the numbers come from is Django's own: `close_at = None if max_age is None else
time.monotonic() + max_age` when a connection is established, `close_if_unusable_or_obsolete`
comparing `time.monotonic()` against it, and `close_old_connections` wired to both `request_started`
and `request_finished`.

`CONN_HEALTH_CHECKS` is on, which means a reused connection is asked whether it is still usable
before it is handed to a request; on this socket that question is the 0.11 ms round trip above, so
the persistent configuration pays it per request and the default configuration pays a whole
connection instead.

### The only bound on a connection, and what is left unbounded

`db_options` is `{'connect_timeout': 5}` and nothing else, which is what
[ADR 0233](ARCHITECTURE_DECISIONS/0233-database-migration-plan.md) records as *"`db_options =
{'connect_timeout': 5}` and nothing else"*. The parameters the PostgreSQL backend
builds from the settings are exactly `client_encoding` (`UTF8`), `connect_timeout`, `context`,
`dbname`, `host`, `port`, `prepare_threshold` and `user`: no `application_name`, so no backend can
be attributed to this application by name; no `keepalives`; no `tcp_user_timeout`; no
`target_session_attrs`; no `options`.

`connect_timeout` bounds only the wait for a server that accepts a socket and then does not answer
the startup packet, and against exactly that — a local listener that accepted and stayed silent —
its price is its own value:

| `connect_timeout` | outcome against the silent listener |
| --- | --- |
| `5` (the project setting) | failed after **5,001.98 ms**: `connection timeout expired` |
| `1` | failed after **2,001.65 ms** — about twice the setting, not once |
| `30` | failed after **30,001.09 ms** |
| `0` (libpq: wait indefinitely) | failed after **130,001.02 ms**, ended by the kernel's `tcp_syn_retries = 6` rather than by libpq |

The listener accepted 4 connections across those four attempts. Refusals that do not involve waiting
are immediate: a port with nothing listening failed after **0.32 ms**, a role that does not exist
after **1.52 ms**, a database that does not exist after **1.55 ms**, and a host name that does not
resolve after **5.68 ms**.

Nothing bounds a connection after it is open. The server's own TCP settings are all zero, which
means the kernel decides: `tcp_keepalives_idle` 0 s, `tcp_keepalives_interval` 0 s,
`tcp_keepalives_count` 0 and `tcp_user_timeout` 0 ms, against kernel defaults of
`tcp_keepalive_time` 7200 s, `tcp_keepalive_intvl` 75 s and `tcp_keepalive_probes` 9 — so a
connection whose peer has vanished without a FIN is not noticed for two hours.

Those zeros are what a server with no TCP listener reports, not what every PostgreSQL 16 reports.
The same build started from a stock `initdb` with `listen_addresses = '*'` — the shape CI's
`postgres:16` service has — reports `tcp_keepalives_idle` as **7200**, the kernel's own
`net.ipv4.tcp_keepalive_time`, while `boot_val` stays **0** and `source` stays `default`: an
unconfigured keepalive timer is reported as the kernel's value once the server accepts TCP. So
*nobody configured it* and *it is off* are different claims, only the first of which is true of this
cluster, and a deployment that listens on TCP inherits the kernel's two hours rather than a zero.

libpq accepts
`keepalives=1` with `keepalives_idle`, `keepalives_interval` and `keepalives_count`, and it accepts
`tcp_user_timeout=5000` and `target_session_attrs=read-write`, through the same call path Django
uses, so every one of them is one line of `OPTIONS` away. What they would do could not be measured
here: `SO_KEEPALIVE` read **0** on the socket in all five configurations because the connection is a
Unix socket, not TCP.

That is the second fact about this environment. `POSTGRES_HOST` is a directory
(`/home/user/daroobank.com/.cache/pgdata`), `listen_addresses` is empty, `inet_server_addr()` and
`inet_server_port()` both return `NULL` for the connection in use, and a TCP connection to
`127.0.0.1:5432` is refused. Every duration in this document was therefore measured over a Unix
socket with no network between client and server; a deployment that connects over TCP adds a
handshake, an authentication exchange and, if `POSTGRES_SSLMODE` is set, a TLS negotiation to each of
the connection costs above, and none of that was measured.

### Timeouts: four modules bound themselves, the server bounds nothing

Every session timeout in the cluster is zero: `statement_timeout` 0, `lock_timeout` 0,
`idle_in_transaction_session_timeout` 0 and `idle_session_timeout` 0, with `deadlock_timeout` at its
1,000 ms default. `log_lock_waits` is off and `log_min_duration_statement` is −1, so a wait leaves no
line in any log. Measured against that:

* **A statement with no bound runs to its own end.** `pg_sleep(2)` completed in **2,003 ms**. The
  same statement inside `SET LOCAL statement_timeout = '500ms'` raised `QueryCanceled` after
  **501 ms**.
* **A lock waiter with no bound waits forever and has to be killed.** A second session that tried to
  take `FOR UPDATE` on a row another session held was still waiting after three seconds —
  `('active', 'Lock', 'transactionid', 3.003)` in `pg_stat_activity` — and was released only by
  `pg_cancel_backend` from an administrator session, raising `QueryCanceled` after **3,007 ms**. The
  same wait with `SET LOCAL lock_timeout = '300ms'` raised `LockNotAvailable` after **301 ms** and
  left the session alive and able to retry.
* **An idle transaction with no bound stays open, holding its locks.** A transaction that had run one
  statement and then gone idle was still open after six seconds —
  `('idle in transaction', 'Client', 6.009, 4 granted locks)` — and nothing in the server or in this
  tree closed it.

The bound that exists is per statement, set by the module that happens to remember: **7 `SET LOCAL`
statements in 4 non-test modules** — `staff_security/read_limit.py`, `staff_security/throttle.py`,
`staff_security/management/commands/cleanup_staff_login_windows.py` and `daroobank/health.py` —
carrying `lock_timeout` `'1s'` three times, `statement_timeout` `'2s'` three times and `'1s'` once.
`idle_in_transaction_session_timeout` appears **0** times in project code, so the third of the three
waits above is bounded nowhere at all. The test suites are far heavier than the code they test: 130
mentions of `lock_timeout`, 76 of `statement_timeout`, 61 `SET LOCAL`, 12 `set_config` and 6
`connect_timeout` across the test modules. Any path that does not go through one of those four
modules — a management command, an ingestion run, a shell session, a query the ORM builds for a view
that never calls them — runs with no bound whatsoever.

### The ceiling, and who is locked out at it

`max_connections` is **100** and `superuser_reserved_connections` is **3**, each equal to its
compiled default — this server writes the first of them into its own configuration file, so its value
is the default while its source is not. Held open from one process until the server refused:

| role | connections held | the refusal | how long the refusal took |
| --- | --- | --- | --- |
| a `LOGIN NOSUPERUSER` role | **97** | `FATAL: remaining connection slots are reserved for roles with the SUPERUSER attribute` | **1.92 ms** |
| the superuser role the application uses | **100** | `FATAL: sorry, too many clients already` — for a superuser operator and for a non-superuser alike | **1.01 ms** |

While the non-superuser role held all 97 open slots, a superuser operator connected successfully: the
three reserved slots are real. While the **superuser** role held all 100, no operator could connect
at all, because the reserved slots are reserved for the role that is already holding them. Opening
one more connection while 97 were held cost **16.90 ms**.

What an idle connection holds was read two ways from `/proc` for those 97 backends: resident set
**total 1,003,684 kB, mean 10,347 kB, min 9,944 kB, max 10,632 kB**, and proportional set **total
107,105 kB, mean 1,104 kB, min 1,087 kB, max 1,107 kB**. Summing RSS across backends overstates
what they hold by **9.4 times**, because the shared pages are counted once per process; an idle
backend of this cluster holds about **1.1 MB** of private memory.

No pooler exists anywhere in the tree: **0 files** mention `pgbouncer`, `pgpool`, `psycopg_pool`,
`HAProxy` or `pg_stat_statements`. `compose.yaml` is 44 lines with 2 services and 15 environment
assignments, sets `POSTGRES_CONN_MAX_AGE: ${POSTGRES_CONN_MAX_AGE:-0}`, and carries **no** resource
limit of any kind — no `mem_limit`, no `cpus`, no `deploy.resources` — so nothing in the development
stack bounds either side of that ratio. The ceiling a single Django process can reach is therefore
100 connections with no queue in front of it, and the price of one worker holding one connection open
is 1.1 MB of private memory plus a slot that no other worker can use.

### One role, a superuser, and the boundary a runtime role would have

The cluster has exactly **one** non-system role: `postgres`, with `rolsuper`, `rolinherit`,
`rolcreaterole`, `rolcreatedb`, `rolreplication` and `rolbypassrls` all true and `rolconnlimit` −1.
It owns every one of the 33 tables in `public`; **0** grants exist to `PUBLIC`; the `public`
schema is owned by `pg_database_owner`. This is the role the application connects as, in
development, in `compose.yaml`, in the CI workflow (which creates a per-run `POSTGRES_USER` that
the official image makes a superuser) and in the test runner.

Measured from that role: it read a stored credential hash out of `pg_authid` (`'SCRAM-SHA-256$…'`),
dropped a project table and recreated it, created a database, read all **360** rows of `pg_settings`,
installed the `vector` extension, and terminated another backend. Only **2** extensions are
available in this build — `plpgsql` and `vector` — and only `plpgsql` 1.0 is installed, so
`pg_stat_statements`, `pgcrypto`, `pg_trgm`, `btree_gin` and `pg_buffercache` are not options here at
any price.

A throwaway `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE` role was measured against the same schema.
Before any grant it was refused every project table, `pg_authid`, `pg_shadow`, `CREATE TABLE` in
`public` and `CREATE DATABASE`. After `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES` and
`GRANT USAGE, SELECT ON ALL SEQUENCES` it read a project table (32 rows), inserted, updated and
deleted a row, advanced a sequence, bounded its own statement with `set_config('statement_timeout',
'1s', false)`, read the table's access control list and read **340** of the server's settings. It was
still refused `pg_authid`, `pg_shadow`, `CREATE TABLE`, `CREATE DATABASE`, `CREATE SCHEMA`,
`ALTER TABLE … ADD COLUMN`, `CREATE INDEX` and `CREATE INDEX CONCURRENTLY`, `TRUNCATE`, `REINDEX`,
`ALTER SYSTEM`, `SET ROLE postgres` and `SET SESSION AUTHORIZATION`.

Three of its refusals are not refusals, and that is the sharpest edge in this section:

* **`VACUUM` and `GRANT` succeed and do nothing.** `vacuum django_migrations` as the runtime role
  printed `WARNING:  permission denied to vacuum "django_migrations", skipping it`, still reported
  `VACUUM` and still exited 0; `vacuum_count` stayed **0** and `last_vacuum` stayed `NULL`. A
  `VACUUM (FULL)` after 20,000 inserted and deleted rows left the table at exactly **1,048,576**
  bytes. `grant truncate on django_migrations to itself` printed
  `WARNING:  no privileges were granted for "django_migrations"` and still reported `GRANT`;
  `has_table_privilege(…, 'TRUNCATE')` stayed **false** and the access control list stayed
  `{postgres=arwdDxt/postgres,dbops_app=arwd/postgres}`. Granting `SELECT` to `PUBLIC`, granting with
  the grant option, and revoking `SELECT` from itself were equally inert. A maintenance step run by a
  runtime role is a silent no-op, not an error.
* **Migrations need `CREATE` on the schema, and then the migrating role owns what it creates.**
  `manage.py migrate` as the runtime role into an empty database owned by the superuser, with `USAGE`
  but not `CREATE` on `public`, failed with
  `MigrationSchemaMissing: Unable to create the django_migrations table (permission denied for schema
  public)`. With `CREATE` granted it applied all **32** migrations, and everything it created is
  owned by **itself** rather than by `postgres`: all **33** tables and all **111** indexes in `public`
  carry the runtime role as `relowner`. The grant has to be made inside the target database —
  `pg_namespace` is per-database, so `GRANT CREATE ON SCHEMA public` run while connected to another
  database grants nothing the migration can use, and the same `MigrationSchemaMissing` follows.
  Against an already-migrated database it exits 0 with *"No
  migrations to apply."*, and with the table grants revoked it exits 1 with *"permission denied for
  table django_migrations"*.
* **The test runner needs `CREATEDB`.** `manage.py test catalog.test_candidate_migration` as the
  runtime role exits **2** with *"Got an error creating the test database: permission denied to
  create database"*. A module with no database-dependent test is not evidence to the contrary:
  `manage.py test daroobank.test_document_links` passed as either role (7 tests) because Django
  creates no test database for it.

Two further boundaries were measured. `pg_dump -Fc` as the runtime role with the grants in place
succeeded and wrote **145,667** bytes; with the table grants revoked it fails on the first table. And
a non-superuser sees other roles' backends in `pg_stat_activity` but not what they are doing: for the
same backend that reads `active`, `select pg_sleep(4)` and wait event `PgSleep` to the superuser, the
runtime role reads `<insufficient privilege>` for the query and `NULL` for `state`, `wait_event` and
`backend_start`. It is not a member of `pg_signal_backend`; it can cancel a backend of its own role
and is refused `permission denied to cancel query` and `permission denied to terminate process` for a
superuser's.

### Autovacuum, bloat and what a deletion leaves behind

Autovacuum is on with `naptime` 60 s, `vacuum_scale_factor` 0.2, `vacuum_threshold` 50,
`analyze_scale_factor` 0.1, `cost_delay` 2 ms and `max_workers` 3; `checkpoint_timeout` is 300 s and
`max_wal_size` / `min_wal_size` are 1,024 MB / 80 MB. Measured on a throwaway 50,000-row table:

| step | rows | size on disk | time |
| --- | --- | --- | --- |
| insert 50,000 rows | 50,000 | **9,312 kB** | 400–440 ms |
| delete half of them | 25,000 (verified by `count(*)`) | **9,312 kB** — nothing shrank | 13–14 ms |
| `VACUUM (ANALYZE)` | 25,000 | **9,320 kB** — nothing returned to the filesystem | **25 ms** |
| `VACUUM FULL` | 25,000 | **4,664 kB** | **48 ms** |

The statistics collector did not keep up with the deletion: immediately afterwards
`n_dead_tup` was **0** against `n_live_tup` 50,000, and two seconds later it was still 0. Autovacuum
did run — `last_autovacuum` was set after **65 s** — and the table was still 9,320 kB afterwards,
because a vacuum frees pages for reuse inside the relation and returns nothing to the filesystem.
The threshold that triggered it is 10,050 dead tuples for a 50,000-row table
(`vacuum_threshold` 50 + `vacuum_scale_factor` 0.2 × 50,000), so a table has to lose a fifth of
itself before anything looks at it. Only `VACUUM FULL` reclaimed space, and it takes an
`AccessExclusiveLock` while it rewrites — the same lock mode ADR 0233 measured a rewriting
`ALTER TABLE` holding for 3.631 s over 500,000 rows and 178,759,168 bytes of WAL, which this document
quotes rather than re-runs.

### Plans: the index and the sequential scan

The current schema has **0** unindexed foreign keys: all **50** of them have an index or a covering
prefix whose leading column is the referencing column, so the gap this section prices does not exist
in the schema as it stands. It exists in the next table anyone adds.

Priced on a synthetic 50,000-row child table whose only index was its primary key, with `ANALYZE`
run and `EXPLAIN (ANALYZE, BUFFERS)` read:

| query | plan without an index on the referencing column | plan with one |
| --- | --- | --- |
| the children of one parent | `Seq Scan`, **Execution Time 2.666 ms**, `shared hit=319`, `Rows Removed by Filter: 49990`, wall 3.14 ms | `Bitmap Heap Scan`, **Execution Time 0.068 ms**, `shared hit=13 read=2`, wall 0.48 ms |
| one cascading parent delete | **3.51 ms** | **0.77 ms** |

`CREATE INDEX` over those 50,000 rows took **17–18 ms** and the index is **480 kB**. The ratio is
39× on execution time for one lookup and 4.6× for one cascading delete, and the price is 480 kB plus
a write on every insert, update of that column and delete — which this run did not measure, because
measuring it needs a write workload and the only write load in this tree is ADR 0233's single writer
thread.

This is the measurement `docs/DATABASE_SCHEMA.md` asks for and does not have: it says *"Use query
plans and realistic data before adding indexes."* and *"Add FKs, constrained status transitions and
transactional publication"*, and the plans above are the query-plan half of that instruction, taken
on synthetic data because no realistic data exists in this tree. The other index experiment the
repository describes cannot run here at all: `docs/TESTING_STRATEGY.md` says its opt-in benchmark
*"compares existing search with test-only GIN trigram and partial B-tree ordering indexes over
100,000 fictional records"* and that *"It requires `pg_trgm` to be available and creatable in an
authorized disposable PostgreSQL cluster"* — and this cluster offers exactly **2** extensions in
`pg_available_extensions`, `plpgsql` and `vector`, with `plpgsql` 1.0 the only one installed, so
`pg_trgm` is neither available nor creatable and the comparison has no environment to run in.

### WAL, checkpoints and the standby that does not exist

`wal_level` is `replica`, `synchronous_commit` and `full_page_writes` are on, `wal_compression` is
off, `commit_delay` is 0 with `commit_siblings` 5, and `wal_buffers` is 512. Measured volumes:

* **10,000 inserts in one statement**: **2,619,752 bytes**.
* **1,000 single-row updates in one transaction**: **176,896 bytes**. The same 1,000 updates with a
  transaction each: **94,520 bytes** — **46.6 % less**, not more, because each transaction's commit
  record costs less than the extra full-page images the batched pass wrote.
* **The same 1,000 updates four times in a row**, read from `pg_stat_wal`: **296,928 → 200,328 →
  182,776 bytes**, and the first pass after the next checkpoint **247,672 bytes with 14,393 records
  and 19 full-page images**. WAL per write is therefore not a constant: it depends on
  `full_page_writes` and on how far the write is from the last checkpoint.
* **Cluster totals at the end of the run**: `pg_stat_wal` 721,277 records, 15,665 full-page images,
  140,870,044 bytes and `wal_buffers_full` 2,280; `pg_stat_bgwriter` 8 timed checkpoints against 14
  requested ones, 7,173 buffers written during checkpoints, 16,952 by backends and 20,744 allocated.
  More checkpoints were requested by WAL volume than were taken on the 300 s timer.
* **Dropping a database does not return the WAL it wrote**: `pg_wal` held **67,113,020 bytes**, and
  the data directory went from **126,007,951** bytes before the drop to **104,884,778** after it.
* **`pg_stat_database` for one probe database**: 151 commits, 0 rollbacks, 579 blocks read against
  746,888 buffer hits, 4 sessions, 0 abandoned, 0 fatal, 0 killed, 0 deadlocks, 0 temporary files
  and 0 temporary bytes — so nothing in these experiments spilled to a temporary file, which is what
  `work_mem` at its 4,096 kB default would have shown if it had.

There is no standby and no archive: `pg_is_in_recovery()` is **false**, `pg_stat_replication` is
empty, there are **0** replication slots, `archive_mode` is **off**, `archive_command` reads
`(disabled)` and `restore_command` is empty, with `max_wal_senders` 10, `max_replication_slots` 10 and
`hot_standby` on and unused. What **could** be measured here, and what ADR 0233 and ADR 0232 both
left unmeasured, is the base backup itself: `pg_basebackup -Ft -z` of the whole cluster exited **0**
in **1,214 ms** and wrote **8,058,024 bytes** in three files — `backup_manifest`, `base.tar.gz` and
`pg_wal.tar.gz`. With `archive_mode` off there is no WAL archive to replay onto that backup, so it
recovers to the instant it was taken and to no point after it: a working base backup with no archive
is a snapshot, not a recovery objective. That leaves the first of the three questions
[the backup and recovery plan](BACKUP_RECOVERY_PLAN.md) says a restore raises — *"is this the right
archive, whose keys open it, and which database does it go into?"* — with one more answer than it had:
there is no archive, so the only candidate is a base backup whose freshness nothing records.

### What the repository already says about it

Counted over the **257** documents in `docs/` that this delivery neither writes nor edits — the
eleven it touches are excluded, because a document that reports the absence of a word cannot itself
be one of the documents searched for it: `statement_timeout` is named in **5** of them, `replica` in
**9**, `superuser` in **15**, `VACUUM` in **3**, `standby` in **3**, `connect_timeout` in **3**,
`least privilege` in **2**, `CONN_MAX_AGE` in **2** — [ADR
0009](ARCHITECTURE_DECISIONS/0009-postgresql-only.md) and [ADR
0222](ARCHITECTURE_DECISIONS/0222-documented-environment.md) — and `POSTGRES_CONN_MAX_AGE` and
`pooling` in **1** each, the latter only in ADR 0217's list of what the readiness report does not
verify. `max_connections`, `autovacuum`, `pooler` and `read replica` appear in **0** of them: no
document in this repository names the connection ceiling or the process that reclaims space.

Over the **741** files of the tree outside `.git`, `.venv`, `.cache`, `.github`, `node_modules`, this
plan, its record and its suite, `pgbouncer`, `pgpool`, `psycopg_pool`, `HAProxy` and
`pg_stat_statements` appear in **0** files. `requirements.in` is 4 lines, `requirements.txt` 94 and
`requirements-build.txt` 9, and no pooling or monitoring client is in any of them.

## Candidate approach and decisions required

The measured starting point is a connection that is opened and closed for every request at a cost of
about 2 ms against a query cost of about 0.1 ms, one bound on the whole connection path
(`connect_timeout` at 5 s), no bound on any statement, lock wait or idle transaction except the seven
`SET LOCAL` statements four modules remember to issue, a ceiling of 100 connections with no pooler in
front of it, a single superuser role that owns the schema and can read every credential hash in the
cluster, no index gap in the 50 foreign keys that exist, and neither a standby nor an archive. Every
option below is contingent on the decisions it names, and none of them is answered here.

1. **Which role connects, and who owns the schema?** One superuser role owns all 33 tables and can
   read `pg_authid`, drop a table, create a database and install an extension. A runtime role with
   `SELECT, INSERT, UPDATE, DELETE` cannot migrate, cannot create an index, cannot `TRUNCATE`, and its
   `VACUUM` and `GRANT` report success while doing nothing — so whoever answers this also answers who
   runs migrations, who indexes and who vacuums, and with which credentials.
2. **What is the connection lifetime, and what may a request pay for it?** At the default of 0 every
   request paid 2.42 ms of the 4.10 ms it took, and 20 requests opened 20 connections. At 60 they
   opened one. A lifetime above 0 keeps a connection open across requests in a worker that may be
   forked, restarted or idle, and `CONN_HEALTH_CHECKS` is already on, so the price of persistence is
   a slot held per worker plus a 0.11 ms check per reuse.
3. **Where is the pool, if any, and which ceiling does it protect?** 100 slots, 97 of them usable by a
   non-superuser, 1.1 MB of private memory per idle backend, and no pooler, no proxy and no resource
   limit anywhere in the tree. A pool changes who holds a slot; it does not change `max_connections`,
   which nothing in this repository sets.
4. **What bounds a statement, a lock wait and an idle transaction, and at which layer?** The server
   bounds none of them. Four modules bound their own statements to 1 s and 2 s, and nothing bounds an
   idle transaction: one was still open after 6.009 s holding 4 granted locks. The layer question is
   the whole decision — a server setting bounds every session including migrations and backups, a
   role setting bounds one role, `db_options` bounds this application's connections, and `SET LOCAL`
   bounds one transaction in one module.
5. **What bounds a connection that stops answering?** `connect_timeout` bounds only the handshake:
   5,001.98 ms against a silent listener, and 130,001.02 ms with the setting at 0. After the
   handshake nothing is bounded — the server's TCP settings are all zero and the kernel's keepalive
   is two hours — and no `keepalives`, `tcp_user_timeout` or `target_session_attrs` is set, though
   libpq accepts all of them through the same `OPTIONS` dictionary.
6. **Who may maintain the database, and how is a no-op distinguished from a success?** A runtime
   role's `VACUUM` exits 0 with a warning and leaves `vacuum_count` at 0; a superuser's reclaims
   nothing either, because `VACUUM (ANALYZE)` left 9,320 kB where `VACUUM FULL` left 4,664 kB.
   Autovacuum ran after 65 s and also returned nothing to the filesystem. Whatever role is chosen,
   the command that reclaims space takes an `AccessExclusiveLock`.
7. **What is the recovery objective, and does a standby or an archive exist?** A base backup of this
   cluster took 1,214 ms and 8,058,024 bytes and works over the replication protocol even with
   `archive_mode` off, but with no archive there is no point in time to recover to. The custody,
   cadence and objective questions belong to
   [the backup and recovery plan](BACKUP_RECOVERY_PLAN.md); what is missing there and measured here is
   that this environment has no WAL archive and no replica at all.
8. **Which query plans may be sequential, and who decides an index is worth its write cost?** All 50
   foreign keys are indexed today, so no gap exists to close; the synthetic measurement prices the
   next one at 480 kB and 17–18 ms to build against a 39× execution-time difference on one lookup.
   Nothing in the tree asserts that a new referencing column gets an index, and no write-amplification
   measurement exists to price it against.

## Options and what each costs

Prices are counted from the pins and files above, not prototyped.

| Option | What changes | Price, counted | What it still does not answer |
| --- | --- | --- | --- |
| **A. Leave the connection path as it is** | nothing | 0 code files, 0 settings, 0 environment variables, 0 roles, 0 indexes and 0 schema pins move; `db_options` stays `{'connect_timeout': 5}`, `POSTGRES_CONN_MAX_AGE` stays `0`, and every request keeps paying 2.42 ms of a 4.10 ms cycle for a connection that lives for one request | decisions 1 through 8: a request path with no bound on its statements, one superuser role and 100 slots is a measured configuration, not a reviewed one |
| **B. Write the connection and capacity numbers into documents only** | the measured ceiling, per-request cost, timeout inventory and privilege boundary added to `docs/DEPLOYMENT.md` and `docs/OPERATIONS_RUNBOOK.md` and linked from the evidence row | 2 documents reworded, `daroobank/test_document_links.py` re-pins its 267 documents and its link and anchor counts, `daroobank/test_environment_documentation.py` re-pins any variable the prose names, and this plan's own quotation pins move | decisions 2, 3 and 4: a documented ceiling that nothing enforces is the same ceiling |
| **C. Pin the connection shape in a suite of its own** | what this delivery does: a suite that re-reads the settings shape, the timeout inventory, the absence of any pooler and the measured numbers, and holds the plan to being a proposal | 1 test module (the three test-module counts move), 2 documents, 1 record, 1 index bullet, 1 changelog entry, 2 evidence cells, 6 neighbour sentences and the five document-and-link counts in `daroobank/test_document_links.py`; no runtime file changes | whether the pinned shape is the wanted shape: a suite reports drift, it does not choose a lifetime, a ceiling or a role |
| **D. Raise `POSTGRES_CONN_MAX_AGE` above 0** | one integer in the environment, which `settings.py` already accepts up to 31,536,000 | 0 code lines: the variable, its validation and its documentation already exist; the measured saving is 2.42 ms per request and 19 of 20 connections, and the measured cost is one slot held per worker for the lifetime, `CONN_HEALTH_CHECKS`' 0.11 ms per reuse, and a connection that survives a fork, a database restart or a failover only as long as the health check notices | decision 2's second half and decision 3: a lifetime is a per-worker slot reservation, so without a worker count and a ceiling there is no number to choose |
| **E. Put a pooler in front** | PgBouncer, pgpool-II or `psycopg_pool` between the application and the server | a new dependency in `requirements.in` (4 lines) and `requirements.txt` (94 lines with hashes) or a new service in `compose.yaml` (44 lines, 2 services, 15 environment assignments, no resource limit), a new host and port pair in `docs/DEPLOYMENT.md`'s variable table and in `daroobank/test_environment_documentation.py`'s inventory, `POSTGRES_HOST`'s meaning changes for every suite that builds a throwaway database — `daroobank/isolated_test_runner.py`, the restore drill's `docker run --network host` client step in the workflow, and `tools/wait_for_database.py` — and transaction-pooling mode forbids the session-level `SET LOCAL` statements the four modules rely on unless prepared statements and session state are handled | decisions 3 and 4: a pooler moves the ceiling without bounding a statement, and the tree's own per-transaction timeouts are what a transaction-mode pooler has to carry |
| **F. Bound the session at the server, the role or the connection** | `statement_timeout`, `lock_timeout` and `idle_in_transaction_session_timeout` set in a server configuration, in `ALTER ROLE … SET`, or in `db_options` / `OPTIONS` | `db_options = {'connect_timeout': 5}` in `daroobank/settings.py` moves against the pins that read it verbatim, including ADR 0233's and this plan's; a server or role setting is outside this repository entirely and no document records it; a migration connection inherits whatever is set, so the 3.631 s rewriting `ALTER TABLE` and the 0.100 s constraint scan ADR 0233 measured become cancellable at any bound below their duration; and the four modules' `SET LOCAL` values stop being the only bounds in the tree | decision 4's layer question and decision 6: a bound that cancels a migration leaves the half-undone schema ADR 0233 measured, so the bound and the migration order have to be decided together |
| **G. Move the application onto a least-privilege role** | a second role with `SELECT, INSERT, UPDATE, DELETE` and `USAGE`, an owner role for migrations, and a grant step that has to run on every new table | the privilege boundary measured above becomes the operating model: migrations move to the owner role (a runtime role fails with `MigrationSchemaMissing` without `CREATE` on the schema, and owns what it creates with it), the test runner keeps a `CREATEDB` role or stops working (it exits 2 without one), `pg_dump` needs at least `SELECT` on every table (145,667 bytes with the grants, a first-table refusal without), index builds and `TRUNCATE` move to the owner role, `VACUUM` and `GRANT` by the runtime role have to be treated as no-ops that exit 0, and the application loses the ability to read `pg_stat_activity` query text, to cancel another role's backend and to see `data_directory` | decision 1's second half and decision 6: two roles means two credential lifecycles, which is
  [the secret rotation plan](SECRET_ROTATION_PLAN.md)'s subject and not this one's |
| **H. Give the cluster an archive and a replica** | `archive_mode` on with an `archive_command`, and a standby taking WAL from one of the 10 sender slots | a server configuration change no file in this repository makes, a destination for WAL that nothing in the tree names, 1,214 ms and 8,058,024 bytes for the base backup a replica starts from, and the whole of [the backup and recovery plan](BACKUP_RECOVERY_PLAN.md)'s custody and retention options, whose prices are counted there; `wal_level` is already `replica` and `max_wal_senders` and `max_replication_slots` are already 10, so no setting has to move to allow it | decision 7: an archive with no objective, no custodian and no restore drill is a directory that fills up, and ADR 0232 measured that nothing here distinguishes a stale archive from a current one |

## Required behavior before any production connection

1. **Decide the role before deciding the pool.** A pooler multiplies whatever privileges the role
   behind it has: today that is one superuser that can read every credential hash in the cluster and
   drop any table.
2. **Price a request in connections, not in milliseconds alone.** At the measured default every
   request opens one connection for about 2 ms to run a query that costs about 0.1 ms; any lifetime
   above 0 trades that for one held slot per worker.
3. **Assume the ceiling is 100 and that 3 of the slots are not the application's to use.** A
   non-superuser role reached 97; the superuser role reached 100 and then locked out the operator
   too, because the reserved slots are reserved for the role that is holding them.
4. **Bound the three waits explicitly, and say which layer bounds them.** No statement, no lock wait
   and no idle transaction is bounded by the server; a lock waiter with no bound waited 3.003 s and
   was killed by an administrator, and an idle transaction was still holding 4 locks after 6.009 s.
5. **Treat `connect_timeout` as a handshake bound only.** It ended a silent listener after
   5,001.98 ms and nothing after that; with the setting at 0 the kernel ended the wait after
   130,001.02 ms.
6. **Count a backend's memory proportionally, not by resident set.** 97 idle backends reported
   1,003,684 kB of RSS between them and 107,105 kB of proportional set: 10,347 kB against 1,104 kB
   per backend, a 9.4× difference that decides whether a ceiling of 100 fits in a host.
7. **Know which maintenance commands report success without doing anything.** `VACUUM` and `GRANT`
   issued by a role that is not the owner exit 0 with a warning and change nothing, so a maintenance
   step has to verify its effect, not its exit status.

## Verification before any enablement

- Repeat the lifecycle experiment on synthetic data against throwaway databases and re-measure every
  number in this document: the connections opened per request at two lifetimes, the four connect
  and round-trip timings, the silent-listener table at four `connect_timeout` values, the three
  unbounded waits, the two ceilings and their refusals, the per-backend RSS and proportional set, the
  bloat table across a `VACUUM (ANALYZE)` and a `VACUUM FULL`, the two query plans and the index
  that separates them, the WAL volumes at three transaction shapes and the base backup.
- Confirm that a runtime role still fails `manage.py migrate` with `MigrationSchemaMissing` without
  `CREATE` on the schema, still exits 2 creating a test database, still cannot create an index or
  `TRUNCATE`, and still sees `<insufficient privilege>` for another role's query — and that its
  `VACUUM` still exits 0 while `vacuum_count` stays 0.
- Confirm that no pooler has appeared: no `pgbouncer`, `pgpool`, `psycopg_pool`, `HAProxy` or
  `pg_stat_statements` in any file, no third service in `compose.yaml`, and no resource limit that
  would stand in for one.
- Confirm that `db_options` is still `{'connect_timeout': 5}`, that `POSTGRES_CONN_MAX_AGE` still
  defaults to `'0'` and is still validated to 0..31,536,000 with the port in the same `try` block,
  that `CONN_HEALTH_CHECKS` is still `True`, that exactly one database alias exists, and that the
  seven `SET LOCAL` statements are still in the same four modules.
- Confirm that the two existing database suites still pass unchanged — the migration plan's and the
  backup and recovery plan's — and that this plan's suite reports the same counts they pin.
- Verify that no role, grant, index, setting, command, environment variable, document or workflow
  step this plan names as absent has appeared, and that the counts in
  `daroobank/test_database_connection_plan.py` are recomputed rather than deleted if a chosen option
  lands.
- Record named owners and evidence for operational, security and release approval. No connection
  lifetime, no pool size, no timeout value, no privilege model, no recovery objective and no claim of
  Phase 1 completion follows from implementing these tests.
