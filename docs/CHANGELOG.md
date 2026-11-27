# Implementation changelog

Entries describe the state at each change; later entries can supersede earlier limitations.

## 2026-11-27 — measure the API contract and permissions boundary, and price the open gaps

**Changes:** `docs/PHASE1_RELEASE_EVIDENCE.md` carries *"approve each route's requirement, approve exposure and permissions for the intended deployment, and add threat modeling and an independent security assessment"* as an open gate, `docs/AUTHORIZATION_REVIEW.md` is *"the inventory is derived and drift-checked; the judgement is unsigned"*, `docs/API_DESIGN.md` proposes 11 additional paths and scoped API tokens beyond `docs/openapi.json`'s 3 public GET routes, and `docs/SECURITY.md` asks for default deny, separation of author/reviewer and *"no automatic clinical approval bypass"*.

`docs/API_PERMISSIONS_PLAN.md` measures the boundary live on synthetic PostgreSQL 16.2 data and prices seven options (A through G) against eight open decisions: 55 named routes (43 debug-gated `staff_*` and 12 public), 16 checked permissions out of 63 `auth_permission` rows, `StaffLoginView` accepting `PUT` and overriding `LOGIN_REDIRECT_URL` (`staff_prices`) to `/staff/`, live OpenAPI drift (`8` undocumented 200 headers, HTML 405/403/429 responses, 120-character `q` truncation before control filtering and JSON vs HTML 404 split at 4,300 vs 4,301 digits in `/api/v1/products/{id}/`), 41/41 active superuser bypass, 16-permission single-user accumulation, 0 of 37 PostgreSQL `CHECK` constraints covering actor separation, cross-revision self-review in `clinical/services.py` and `catalog/identity.py`, 15 of 16 `lock=False` `recheck_actor` calls (`sources.review_claim` committing after reviewer deactivation and password invalidation), dormant session survival across off/on toggles and `5,000`-row caps in `list_staff_sessions` and `revoke_staff_sessions`, 6 management commands running under `DEBUG=False`, and `LOGGING == {}`.

`daroobank/test_api_permissions_plan.py` pins the plan, the codebase counts and the live PostgreSQL probes (`20` one-by-one Red check mutations caught and restored byte-for-byte). Nothing was implemented: no API token model, OAuth/JWT dependency, OpenAPI change, role exclusivity rule or DB trigger was added. `docs/API_DESIGN.md`, `docs/AUTHORIZATION_REVIEW.md`, `docs/SECURITY.md`, `docs/DEPLOYMENT.md`, `docs/OPERATIONS_RUNBOOK.md`, `docs/DEVELOPMENT_GUIDE.md`, `docs/PHASE1_RELEASE_EVIDENCE.md` and `docs/TESTING_STRATEGY.md` cross-link the plan and [ADR 0235](ARCHITECTURE_DECISIONS/0235-api-permissions-plan.md). Shared tree pins updated alongside (`DOCUMENT_COUNT = 269`, `ADR_COUNT = 235`, `LINK_COUNT = 1157`, `SUITE_LINE_COUNT = 25`, `DOCS_MARKDOWN_COUNT = 268`, `TEST_MODULE_COUNT = 241`/`242`, `LOGIN_ROUTE_TESTS = 45`, `TEST_MODULES_NAMING_COMMAND = 9`, `COMMAND_MENTIONS_IN_TESTS = 20`).

## 2026-11-27 — measure the network and TLS edge, and price the network and TLS options

**Changes:** `docs/PHASE1_RELEASE_EVIDENCE.md` carries *"Optional proxy-scheme trust and HSTS settings exist; both are off by default."* and *"actual network isolation, trusted proxy configuration and header sanitization, approved hostnames, TLS issuance/renewal, HTTPS/CSRF/cookie checks and HSTS rollback plan; see ADRs 0184–0185."* while `docs/DEPLOYMENT.md` says *"HSTS is off unless `DAROOBANK_HSTS_SECONDS` is explicitly set to a positive value outside debug."* and that the proxy flag *"is off by default and ignored in debug"*, and `docs/SECURITY.md` requires *"TLS in transit"* — two opt-in settings and a strip-by-default middleware, and no measurement of what a response actually carries.

`docs/NETWORK_TLS_PLAN.md` now measures before it proposes: a `What is true today, measured` section in six subsections, eight numbered decisions, seven priced options — leave the measured edge as it is, write the target public inventory into documents only, pin the public inventory in a suite of its own, emit more headers from the application, turn on the existing opt-ins in a deployment, add CORS to the application, and declare network and TLS out of Phase 1 scope — a seven-item `Required behavior before any production exposure` list and a six-item verification list. The measurements, one run in two fresh processes: two header profiles over the 12 public routes, the 3 API routes and the 43 staff routes (13 middleware entries at debug import and 14 in non-debug, the six-, eight-, ten- and nine-header response classes, 41 staff 302s against one 200 and one 405), HSTS at 0 of 3 features with plain HTTP answered 301, the forwarded scheme stripped unless the reviewed opt-in trusts the peer (trusted 200, untrusted 301, the flag without CIDRs failing startup, the flag ignored in debug), zero non-test `Access-Control` occurrences and zero such headers on any response, `Cross-Origin-Opener-Policy` from Django's default with `Cross-Origin-Resource-Policy`, `Cross-Origin-Embedder-Policy` and `Permissions-Policy` never sent, `Referrer-Policy: no-referrer` on 7 of 12 public routes and `same-origin` on the other five, the opt-in limiter's 200/200/200/429 with `Retry-After: 60` keyed on `REMOTE_ADDR` while `X-Forwarded-For` is read by no non-test module, 63 templates, 25,166- and 8,245-byte stylesheets, and a 217-line workflow with 0 TLS, HSTS or proxy mentions. Nothing is implemented: no header, middleware, environment variable, dependency, control or command was added. `daroobank/test_network_tls_plan.py` pins the plan's shape, its twenty-four quoted requirements, its numbers, the live settings and database-free response shape, the unchanged environment reads, and the neighbour links ([ADR 0234](ARCHITECTURE_DECISIONS/0234-network-tls-plan.md)).

## 2026-11-27 — measure what a migration costs, and price the staging upgrade and rollback options

**Changes:** `docs/DEPLOYMENT.md` asks a release to *"run tests/migrations on staging and validate
rollback compatibility"* and to *"Define rollback including content/cache and migration compatibility
before release"*, `docs/OPERATIONS_RUNBOOK.md` tells an operator to *"rerun in staging, then
explicitly resume from a safe checkpoint"*, `docs/DEVELOPMENT_GUIDE.md` warns that catalog migration
`0008` *"fails on existing violations and may wait for table locks"*, `docs/TESTING_STRATEGY.md`
counts *"All relevant tests pass in CI and staging"* as a release condition, `docs/ROADMAP.md` puts
*"DB migrations"* in Phase 1, and `docs/PHASE1_RELEASE_EVIDENCE.md` carried the subject as an open
gate that named its own gaps: *"it measured no duration, no WAL volume and no long-running `ALTER
TABLE` under load"* and *"Rollback of Django's own apps, other shapes of concurrency (an open writing
transaction, `CREATE INDEX CONCURRENTLY`, a running command, a standby) and tested recovery from a
real staging schema are unmeasured."* Two drills existed and answered the row-count question only.

`docs/DATABASE_MIGRATION_PLAN.md` now measures before it proposes: a `What is true today, measured`
section in nine subsections, eight numbered decisions, seven priced options — leave the migration path
as it is, write the staging sequence down as an ordered procedure, bound the migration session with a
timeout, move index builds out of atomic migrations, take a copy before every destructive migration
and drill restoring it, make a half-undone schema detectable, and declare staging migration and
rollback out of Phase 1 scope — a seven-item `Required behavior before any staging migration` list and
a six-item verification list. Every measurement was taken against the synthetic PostgreSQL 16.2 server
on throwaway databases that the experiment created and dropped, with the `pg_dump` and `pg_restore`
clients the `pgserver` wheel bundles.

Both directions are sub-second and cheap in WAL. `migrate` applied 32 migrations in 0.927 s writing
1,172,320 bytes; `migrate catalog zero` unapplied its 11-migration cascade in 0.711 s and 149,408
bytes, leaving 17 tables and 21 applied rows; the other five apps followed in 0.378 s and 61,536
bytes, leaving nine tables that are all Django's; and reapplying took 0.724 s and 885,624 bytes and
returned an inventory identical row for row — 279 columns, 111 indexes, 138 constraints — with zero
rows. A rollback's cost does not grow with the data it destroys: inserting 50,000 rows into
`staff_security_staffloginwindow` took 0.345 s and wrote 29,621,944 bytes into an 18,653,184-byte
table, and `migrate staff_security zero` then removed both of that app's tables and all 50,000 rows in
0.096 s writing 6,680 bytes, with a reapply that returned an empty table in 0.068 s.

Lock modes were read from `pg_locks` and the load numbers come from one writer thread committing an
insert every 5 ms, about 195 writes a second. `ALTER TABLE … ADD COLUMN` takes `AccessExclusiveLock`
on the table alone, `CREATE INDEX` takes `ShareLock`, an `ALTER COLUMN … TYPE` to the same width
rewrites under `AccessExclusiveLock` on the table, its primary key, its indexes and its TOAST table,
`DROP TABLE catalog_productpresentation` is refused with *"cannot drop table … because other objects
depend on it"* and `TRUNCATE` of it with *"cannot truncate a table referenced in a foreign key
constraint"*. A metadata-only column took 0.001 s and 1,344 bytes on an empty table and 0.001 s and
1,408 bytes at 50,000 rows; a rewriting column took 0.007 s and 27,016 bytes at zero rows, 0.143 s and
17,895,928 bytes at 50,000, and 3.631 s and 178,759,168 bytes at 500,000, rewriting a 186,662,912-byte
table into 174,104,576 bytes. Under the writer that rewrite waited 2.726 s and blocked exactly one
insert for 2.703 s, a blocking `CREATE INDEX` took 0.102 s and stalled one writer for 0.094 s, the
metadata-only column blocked nobody, and `CREATE INDEX CONCURRENTLY` took 0.003 s outside a
transaction and cannot run inside one at all — which no project migration can avoid, `atomic = False`
appearing in none of the 17 modules. An uncommitted `UPDATE` in a second session and a session that
only ran `SELECT count(*)` and `pg_sleep(4)` each cancelled a metadata `ALTER TABLE` after 2.001 s at
the drill's 2 s `lock_timeout`, and the same reader cancelled `migrate catalog zero` after 2.551 s,
leaving 32 tables, 31 of 32 applied migrations and 29 rows, the cascade's first migration —
`ingestion 0002`, not a `catalog` one — already committed.

Rolling back Django's own apps is the widest command in the tree. `migrate sessions zero` is one
migration, 0.156 s and 4,544 bytes, and costs `django_session` while every project row survives.
`migrate contenttypes zero` derives a cascade of 26 migrations of which 24 are project migrations —
`auth` 12, `contenttypes` 2, `catalog` 6, `clinical` 2, `ingestion` 2, `pricing` 1, `sources` 1 —
took 1.241 s and 346,936 bytes, and left five tables and six rows, after which an ORM read of
`ProductPresentation` still returned two rows while the model-derived inspection reported 28
unresolved tables, 49 missing foreign keys, 45 missing unique keys, 23 missing check constraints, 239
missing columns and 51 missing field indexes. `migrate auth zero` afterwards found nothing left to
take at 0.016 s and 752 bytes. Almost nothing notices that state: `manage.py check`,
`makemigrations --check --dry-run` and `showmigrations` all exit 0 on a half-undone database,
`migrate --check` exits 1, readiness reports *"1 migrations are not applied:
ingestion.0002_importreceiptitem_importreceipt_manifest_version_and_more"* with
`migration_history_consistent` true — the pair an unmigrated database also produces — and
`inspect_postgresql_schema` takes no `--database` and reads `django.db.connection`, so it cannot be
pointed at another database. Repairing forward took 0.198 s, returned an identical inventory and 32
applied migrations, and left 29 of 31 rows.

The one migration that reads data is cheap and fails atomically. `catalog 0008`, the validated
`catalog_published_requires_verified` check constraint, took 0.100 s and wrote 2,464 bytes of WAL
against 200,000 synthetic presentations — 0.068 s and 2,440 bytes on an empty table — and under the
write load 0.096 s, 6,200 bytes, zero blocked writes and a slowest write of 0.028 s; against a single
violating row it failed after 0.052 s with *"check constraint … is violated by some row"*, wrote 0
bytes, left the constraint absent and left `django_migrations` at 31 rows, so a forward migration that
fails leaves the schema as it was while a rollback that is blocked does not. A copy at that volume was
1,186,535 bytes in 0.154 s against the 136,001-byte fixture archive ADR 0232 measured, restored into a
database that did not exist in 0.327 s printing 0 bytes, and its next insert succeeded with no
`setval` because the archive carries its `SEQUENCE SET` entries. No standby exists to measure here:
`pg_is_in_recovery()` is false and `pg_stat_replication` and `pg_replication_slots` are both empty.

`daroobank/test_database_migration_plan.py` holds the plan to all of it: that the plan keeps its five
sections, nine measured subsections, eight decisions, seven priced options, seven required behaviors,
six verification items and its proposal disclaimers, and that no option reads as chosen; that it quotes
the twenty-four requirements it is priced against with the source documents' sentences intact; that the
tree still holds 17 atomic project migration modules in six linear chains, two data operations whose
declared reverse is a no-op, one `AddConstraint` migration, `db_options = {'connect_timeout': 5}` with
no migration timeout anywhere, three request-path modules that bound their own lock wait and four
statement timeouts, an inspection command with no `--database`, a workflow with no `environment:` key,
four settings modules, twelve commands, twenty-four models and a hash-pinned lock with no `pgserver`
in it; that the schema, cascade, fixture, document and module inventories a migration change would move
are still as counted; and that four measurements stay true because they are re-performed on PostgreSQL
— the cascade a rollback derives from the graph, the atomic refusal of the validated constraint
migration, every command's and both readiness checks' answer to a half-undone database before and after
a repair forward, and the absence of a replica. Twenty-two of its 26 tests are database-free. Twenty-eight
regressions were applied alone to a byte-identical backup of the tree and reverted afterwards, and all
twenty-eight are caught: between 1 and 2 of the 26 tests fail for each, and the one a first pass
missed — renaming the local `loader` inside `migration_history_consistent()`, which left the count of
`MigrationLoader(connection` at two — is recorded in the ADR with the pin it strengthened.

The pins that count the tree moved with it: 265 documents, 233 records, 1075 links, 31 external
links, 29 anchors and 23 `Suite:` lines in `daroobank/test_document_links.py`, 239 test modules in
the two suites that count them and 264 markdown documents in
`daroobank/test_backup_recovery_plan.py`. One pin outside this plan moved too:
`daroobank/test_mfa_implementation_plan.py` counts the test modules that name the login route, and
this suite names the `staff_security_staffloginwindow` table and the command that cleans up staff
login windows, so that count is 43 rather than 42. `docs/MFA_IMPLEMENTATION_PLAN.md` quoted *42 of
the 237 test modules*, stale since the tree grew past it, and now quotes 43 of the 239.

No migration control is implemented: no staging environment, no `lock_timeout` on any migration
connection, no migration-order control, no copy step, no command, no migration and no dependency was
added, and the deployment guide's four instructions — set `lock_timeout`, stop the writers, copy the
tables a cascade will drop, `setval` on restore — are unchanged, because turning them into a sequence
is option B and no option was chosen. The prices are counted from inventories rather than prototyped —
no migration control was built and reverted, so no cascade of pin failures was run the way ADR 0227
measured 20 across 7 suites — and every duration and byte count is one measured run on one machine
against synthetic data, not a budget. See
[ADR 0233](ARCHITECTURE_DECISIONS/0233-database-migration-plan.md).

## 2026-11-26 — measure what a restore proves, and price the backup and recovery options

 **Changes:** `docs/DEVELOPMENT_GUIDE.md` says *"PostgreSQL's `pg_dump` and `pg_restore` are
external client utilities, not an application backup service"* and *"A volume alone is not a
backup."*, `docs/OPERATIONS_RUNBOOK.md` asks an operator to *"define ownership, encrypted backup
cadence, off-host retention, RPO/RTO and recovery environment"*, says *"no values have been
approved"* and then forbids the one thing an incident would require — *"never restore into the
running database"* — `docs/PHASE1_RELEASE_EVIDENCE.md` carries *"encrypted off-site backups,
independent key custody, access control, retention, integrity and anti-replay/freshness policy,
recovery objectives, scheduled isolated restore drills and documented owner"* as an open gate,
`docs/SECURITY.md` assigns *"Operate backups and database"* to a database administrator role that
does not exist here, and ADR 0225 ends with *"Identity sequences are part of any restore."* The
drill exists and runs twice in CI under opt-in switches, and it answers a narrower question than the
gate asks.

`docs/BACKUP_RECOVERY_PLAN.md` now measures before it proposes: a `What is true today, measured`
section in four subsections, eight numbered decisions, seven priced options — leave the restore path
as documented, read the archive's own header before restoring, record every dump and restore in the
database, put the envelope keys in a custodian outside the repository, document and drill the
live-database shape, verify completeness against a manifest instead of a self-written fixture, and
declare backup and recovery out of Phase 1 scope — a seven-item `Required behavior before any
restore` list and a six-item verification list. The measurements, taken against the synthetic
PostgreSQL 16.2 server with the `pg_dump`, `pg_restore` and `createdb` clients the `pgserver` wheel
bundles: the documented sequence is `dump, list, createdb, restore, migrate, check` and its listing
step is `pg_restore --list --no-password -- "$SYNTHETIC_DUMP_FILE" > /dev/null`, while the drill
captures the same listing and asserts only `listed.returncode` — `listed.stdout` appears nowhere in
its 315 lines; the guide's target is the literal `daroobank_restore_drill`, created one line
earlier, and of the 262 markdown documents in `docs/` only the plan and its record name the flags a
restore over an existing database needs.

One replay dumped a synthetic fixture, wrote one later business fact, dumped again, and restored the
older archive into a new database: 136,001 bytes against 136,541, both listings stamped `2026-11-26
23:37:44 UTC` because the two dumps took 0.071 s and 0.053 s, the restore exiting 0 in 0.163 s and
printing 0 bytes, the target holding 33 public tables, 32 applied migrations, 2 accounts, 0
sessions, 1 package and 1 review while the source held 2 and 2, and `manage.py check` (0.372 s),
`migrate --check` (0.390 s), `inspect_postgresql_schema` (0.388 s) and the drill's ORM verification
(0.522 s) all exiting 0 with empty stderr — 1.673 s of verification that cannot tell a stale archive
from a current one. The archive's header counts `TOC Entries: 291` and its listing prints 287
selected entries — 33 `TABLE`, 33 `TABLE DATA`, 60 `INDEX`, 30 `SEQUENCE` and 30 `SEQUENCE SET`, 51
`CONSTRAINT` and 50 `FK CONSTRAINT`, matching the 50 foreign keys the schema inspection counts — of
which none is an ACL, an OWNER or a GRANT, while four `TABLE DATA` entries are `auth_user`,
`auth_user_groups`, `auth_user_user_permissions` and `django_session`. A second restore of the same
archive into the restored target exited 1 in 0.006 s on `ERROR:  relation "auth_group" already
exists`, and the two flags that made it exit 0 in 0.209 s are named in no other document.

`daroobank/test_synthetic_encrypted_restore.py` mints its own recipient and signing keys with
`openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=synthetic-only` at mode `0600` inside a
`0700` temporary directory the test destroys, `.github/workflows/checks.yml` references zero
`secrets.*` expressions, CI takes its clients from `docker run --rm --network host … postgres:16`,
one of the four mutable base-image references ADR 0226 counted, `LOGGING` is `{}`, no application
module imports `logging`, and none of the 24 project models is named like a backup, dump, archive,
restore or recovery record.

`daroobank/test_backup_recovery_plan.py` holds the plan to all of it: that the plan keeps its five
sections, four measured subsections, eight decisions, seven priced options, seven required behaviors
and its proposal disclaimers; that it quotes the sixteen requirements it is priced against with the
source documents' measured sentences intact; that the guide's script is still six steps that discard
the listing and still restore only into a database they just created; that no document except the
plan and its record names a live-database restore; that the drill still never reads the listing it
captures; that the envelope drill still mints and destroys its own keys; that the workflow still
holds no secret and no key file is committed; that the client tools are still not in the repository;
that nothing records a dump or a restore; that the schema, attribution, rollback, CI-gate, document
and module inventories a backup record or a custodian would move are still as counted; and that the
replay stays as measured, by re-performing it. Twenty regressions were applied alone to a
byte-identical backup of the tree and reverted afterwards, and all twenty are caught: between 1 and
3 of the 24 tests fail for each, except the renamed isolated test database, which
`daroobank/isolated_postgresql` refuses with *"Invalid isolated synthetic test database name."*
before any test runs.

No backup control is implemented: no record, manifest, custodian, schedule, command, dependency or
change to the restore target policy was added, and the guide's script, the runbook's prohibition and
the drill's new-database policy are unchanged, because changing them is option E and no option was
chosen. The prices are counted from inventories rather than prototyped — no backup control was built
and reverted, so no cascade of pin failures was run the way ADR 0227 measured 20 across 7 suites —
and the replay was performed once, on two accounts, one package, one review and a cross-domain
fixture in throwaway databases, so it says nothing about restoring a real volume, about the flags
that make a restore over an existing database succeed against a large or concurrently used one, or
about what an operator sees while it happens. No option was evaluated for security, lawfulness or
operational cost; custody was not measured, because no secret store, KMS or key file exists in this
tree; and the live-database shape was exercised mechanically on a throwaway target with no
authorization, downtime or privilege story. The 16 tests of the three restore suites still pass
locally in 23.8 s with the bundled clients on `PATH`, and no CI step runs the new suite's one opt-in
database test. `docs/DEVELOPMENT_GUIDE.md`, `docs/OPERATIONS_RUNBOOK.md`, `docs/SECURITY.md`,
`docs/DEPLOYMENT.md`, `docs/PHASE1_RELEASE_EVIDENCE.md` and `docs/TESTING_STRATEGY.md` now name the
plan and the record. See [ADR 0232](ARCHITECTURE_DECISIONS/0232-backup-recovery-plan.md).

## 2026-11-26 — measure what rotating the one secret does, and price the rotation options

 **Changes:** `docs/SECURITY.md` asks for *"encryption at rest where appropriate with isolated
managed keys and rotation"*, `docs/DEPLOYMENT.md` tells an operator to *"Supply a unique randomly
generated key through an approved secret manager"* and then concedes *"Changing a key affects
existing signatures and sessions; no production rotation policy is implemented"*,
`docs/OPERATIONS_RUNBOOK.md` tells an incident responder to *"rotate exposed credentials"* inside a
checklist that calls itself *"mostly a prospective checklist"*, and
`docs/PHASE1_RELEASE_EVIDENCE.md` carries *"secret manager, key generation/rotation and recovery"*
as an open gate. The requirement was written down four times and the procedure existed nowhere, and
the runbook went further than the others: it called `revoke_staff_sessions --all --apply` *"the
state to want after a secret rotation"*, which is the one instruction this measurement contradicts.

 `docs/SECRET_ROTATION_PLAN.md` now measures before it proposes: a `What is true today, measured`
section in three subsections, eight numbered decisions, seven priced options — leave key handling
as documented, write the procedure down only, add a read-only pre-rotation impact command, make
rotation graceful with `SECRET_KEY_FALLBACKS`, give each purpose its own key material, take the key
from an external secret manager or KMS, and declare rotation out of Phase 1 scope — a seven-item
`Required behavior before any rotation` list and a verification list. The measurements, taken with a
live `django.setup()` under `daroobank.synthetic_test_settings` on synthetic PostgreSQL data plus
file reads: `SECRET_KEY` is `os.environ.get('DAROOBANK_SECRET_KEY', '')` and `daroobank/settings.py`
is the only project module that reads it; in debug an empty value becomes the published
35-character `'development-only-not-for-production'`, which `require_nondebug_secret` rejects, while
a 53-character dictionary phrase passes it, because the check's own docstring says it *"cannot
determine randomness or secrecy"*; of the 127 non-test project modules 9 call `salted_hmac` and none
of the 9 passes an explicit `secret=`, so all of them take `settings.SECRET_KEY`, using 9 salts — 8
named constants and one inline literal — of which 5 compose a per-purpose suffix; 6 modules sign
through `django.core.signing` with the same secret; the session store signs its own rows under
`django.contrib.sessions.SessionStore`; `SECRET_KEY_FALLBACKS` is `[]` and no project module names
it; the 12 management commands include no rotate or rekey command; `LOGGING` is `{}` and no project
module imports `logging`; and the lock holds 7 names and 78 hashes with no key-management package.

 The rotation was then performed on one synthetic staff session. Before it, the account logged in,
read `staff/prices/` for 200 and wrote one login window and one read window. After the key changed:
the same request answered 302 to the login page; the `django_session` row kept its key and its
expiry and decoded to `{}`; exactly one `"Session data corrupted"` warning reached
`django.security.SuspiciousSession`, a logger with no handlers; `list_staff_sessions` reported
`scanned: 1, sessions_matched: 0, sessions_unbound: 0` with no accounts, so the sessions a rotation
invalidates disappear from the inventory rather than appearing in it;
`revoke_staff_sessions --all --apply` reported `matched: 0, revoked: 0` and left the row behind;
`cleanup_staff_login_windows --apply` reported `{"deleted": 0, "limit": 500}`, because its retention
is 24 hours and the orphans were minutes old, and no command prunes `PublicReadWindow` at all; both
window tables went 1 → 2 as the limiter counters restarted at zero; `recheck_actor` denied a guarded
write carrying the pre-rotation hash; and the `password` column stayed byte-identical with the
passphrase still verifying, while `get_session_auth_hash()`, the session fingerprint and the
inventory alias for the same session key all moved. With the old key listed in
`SECRET_KEY_FALLBACKS` the row decoded fully again and the signed cursor loaded, and the staff route
still answered 302, because `daroobank/session_guard.authorization_fingerprint` embeds
`get_session_auth_hash()` only; the inventory then showed the session as `bound: true,
guard_would_end_it: true` under a different alias, and `scanned: 0` after the guard ran, because
Django cycles the session key when a fallback matches and this project's guard deletes the cycled
row.

 `daroobank/test_secret_rotation_plan.py` (20 tests, ~7.4 s, 6 of them on the synthetic database)
pins both halves: that the plan stays an unowned proposal with its sections, decisions, options and
measured sentences intact and still quotes the five documents it answers; that every module, file
and record it names exists, including the nine keyed sites by path and line; that the key surface
stays as measured; and that the cascade stays as measured, by re-performing it. Fourteen regressions
were applied alone and reverted from backups that were re-hashed afterwards, and all fourteen fail
the suite, between 1 and 8 of the 20 tests each: dropping the proposal disclaimer (2), dropping a
measured cascade number (1), dropping a numbered decision (1), dropping an option row (1), no longer
quoting the release-evidence gate (1), misnaming a keyed site (1), configuring a fallback key in
settings (2), replacing the debug constant (1), teaching the guard about fallback hashes (8),
teaching `recheck_actor` about them (1), passing an explicit `secret=` at a keyed digest (3),
renaming a salt (2), making the shape check measure entropy (1) and claiming in the deployment guide
that a rotation policy exists (1).

 No rotation control is implemented: no command, setting, fallback entry, fallback-aware guard or
recheck, per-purpose key, logging configuration or dependency was added, and the deployment guide
still says no production rotation policy is implemented. The prices are counted from inventories
rather than prototyped — no rotation command was built and reverted, so no cascade of pin failures
was run the way ADR 0227 measured 20 across 7 suites — and the rotation itself was performed once,
on one synthetic account in a throwaway database, so it says nothing about the volume a real
rotation produces or how long a mass logout takes to drain. No option was evaluated for security,
lawfulness or operational cost; key custody was not measured, because no secret manager, KMS or key
file exists in this tree; and no recovery path was exercised, so a lost key and a rotated key are
alike only in what was measured of them. `docs/SECURITY.md`, `docs/DEPLOYMENT.md`,
`docs/OPERATIONS_RUNBOOK.md`, `docs/DEVELOPMENT_GUIDE.md`, `docs/PHASE1_RELEASE_EVIDENCE.md` and
`docs/TESTING_STRATEGY.md` now name the plan and the record, and the runbook no longer tells an
operator that revoking every session is the state to want after a rotation. See
[ADR 0231](ARCHITECTURE_DECISIONS/0231-secret-rotation-plan.md).

## 2026-11-26 — measure the authentication surface and price the MFA options

 **Changes:** `docs/SECURITY.md` asks for *"MFA for administrators"*, *"Argon2-compatible password
hashing"* and *"lockout/recovery controls"* and then states *"This is **not a production security
model**. No MFA."*; `docs/PHASE1_RELEASE_EVIDENCE.md` leaves *"MFA for the sixteen guarded write
services"* unchecked; `docs/AUTHORIZATION_REVIEW.md` carries *"There is no MFA"* as a residual risk
and *"Is MFA in scope for Phase 1"* as an open question with no owner, no date and no answer; and
`daroobank/settings.py` keeps the staff portal debug-only *"until MFA, throttling and audit exist"*,
which `check_deployment_readiness` enforces by failing `staff_portal_disabled` for that reason. The
document meant to close the gap, `docs/MFA_IMPLEMENTATION_PLAN.md`, stated no measurements, so
nobody could tell whether a second factor was one model away or whether this tree had anywhere to
put one. An earlier prototype of it had already been reverted before review.

 The plan grew from 26 lines to 176 and now measures before it proposes: thirteen counted facts,
seven numbered decisions, and six priced options — leave authentication as documented, a TOTP second
factor, WebAuthn or a passkey, an account-aware lockout, delegation to an identity provider, and
declaring MFA out of Phase 1 scope — each with a price counted from pins and files and a column for
what the option still does not answer. Its `Required flows`, `Secret and session boundaries` and
`Verification before any enablement` sections are byte-identical to the original. The measurements,
taken with a live `django.setup()` under `daroobank.synthetic_test_settings` on synthetic PostgreSQL
data plus file reads: `StaffLoginView` is the only `LoginView` subclass among the 127 non-test
project modules and its template renders exactly `username` and `password`, with 41 of the 236 test
modules naming that route; no field on any installed model matches `mfa`, `totp`, `webauthn`,
`passkey`, `otp`, `factor`, `device`, `credential`, `challenge` or `recovery`, no project module
names a factor mechanism, and the four modules that mention `MFA` mention it to exclude it;
`AUTH_USER_MODEL`, `AUTHENTICATION_BACKENDS`, `PASSWORD_HASHERS`, `SESSION_ENGINE`, `CACHES` and
`LOGGING` are all unset in project settings, so `auth.User` keeps its 11 stock columns and 19 of the
24 project models point at it; no project module calls `authenticate()`, `login()`, `cycle_key` or
`check_password`, exactly one project receiver is connected to `user_logged_in` and none to
`user_login_failed`, so nothing observes a failed login except the optional throttle; the session
fingerprint in `daroobank/session_guard.py` is a keyed digest of `is_active`, `is_staff`,
`is_superuser`, the session-auth hash and the sorted permission set, with nothing about the client,
the address or the session key, so a copied cookie passes while the account state is unchanged; both
limiters are keyed to an HMAC of `REMOTE_ADDR` — 10 login attempts and 120 reads per 60 seconds,
windows of `client_key, started_at, attempts` — fail open and are opt-in, so neither is account-
aware and neither is a lockout; `argon2-cffi`, `cryptography`, `pyotp`, `fido2` and `webauthn` are
not installed and the preferred hasher is `pbkdf2_sha256`, while `salted_hmac` already appears in 9
project modules, `constant_time_compare` in 7, `hashlib` in 9 and `hmac` in 1; the lock is 4 direct
requirements and 94 lines / 7 names / 78 hashes installed with `pip install --require-hashes`,
verified by `tools.verify_runtime_lock` and audited by `pip-audit --strict`, against 12 documented
environment variables of which 6 are `DAROOBANK_*`; both signed-token surfaces are stateless with no
consumption record and are reached by no route and no test; `tests/browser/smoke.cjs` is 1564 lines
with zero mentions of an authenticator or `webauthn`; and the schema is 33 tables, 279 columns, 111
indexes, 138 constraints, 50 foreign keys and 32 applied migrations built by 17 project migrations,
so one factor model is table 34, a third `staff_security` migration, 18 project migrations, 33
applied and 20 attributed models of 25.

 `daroobank/test_mfa_implementation_plan.py` (15 tests, no database, about a second) pins both
halves: that the plan is an unowned proposal whose six sections, seven decisions and six options
survive, that it still quotes the requirements it answers, that option B's price cell and the
measured schema sentence are exact rather than paraphrased, that every module, file, tool and
decision record it names exists, and that the thirteen measurements stay true. Eleven regressions
were applied alone and reverted from backups that `filecmp` then proved byte-identical, and all
eleven fail the suite, 18 failures in total: dropping a decision's number (1), renaming the options
heading (2), giving the plan an owner (2), renaming an option (1), overstating option B's migration
price (1), changing the measured schema count (2), removing the link to the decision record (1),
creating `daroobank/mfa.py` that names TOTP (3), adding `AUTHENTICATION_BACKENDS` to project
settings (1), raising `ATTEMPT_LIMIT` from 10 to 12 (1) and giving the session fingerprint a client
dimension (3). Two of the eleven were green on the first run — the price cell and the measured
sentence were not pinned exactly — so both pins were added and both checks were run again.

 No factor is implemented: no model, migration, setting, backend, route, dependency, template field
or module was added, the portal is still refused outside debug for exactly this gap, and the counts
the suite pins are the ones measured before the plan was rewritten. The prices are counted from
inventories rather than prototyped — no cascade of pin failures was run the way ADR 0227 measured 20
across 7 suites — so they are a lower bound on the work; no option was evaluated for security,
performance, availability or lawfulness; and the schema numbers are quoted by a database-free suite
whose live counterparts are pinned by the suites of ADR 0225, ADR 0227 and ADR 0228.
`docs/SECURITY.md`, `docs/DEVELOPMENT_GUIDE.md`, `docs/PHASE1_RELEASE_EVIDENCE.md`,
`docs/TESTING_STRATEGY.md` and the residual-risk list of `docs/AUTHORIZATION_REVIEW.md` now name the
plan and the record. See [ADR 0230](ARCHITECTURE_DECISIONS/0230-mfa-implementation-plan.md).

## 2026-11-26 — write down the decision for the two write paths that name nobody

 **Changes:** ADR 0220 measured attribution instead of assuming it — 19 of the 24 project models
name the account that appended them behind a protected foreign key and a creation timestamp — and
recorded two places that name nobody: `catalog.ProductPresentation`, the row the public reads, and
price staging from `manage.py stage_price_csv`, whose candidates the portal then refuses to let
anybody review and which, because an identical payload reuses the row, can never acquire an actor
later. Both were measurements. Neither was a decision, and `docs/SECURITY.md` asks for audit records
carrying *"actor, role, target, before/after versions or hashes, decision, time and request
correlation"* while the Phase 1 evidence carries source rights, protected audit and explicit
publication approval as open.

 `docs/ATTRIBUTION_GAP_PLAN.md` is that decision written down in the form `docs/READ_AUDIT_PLAN.md`
and `docs/MFA_IMPLEMENTATION_PLAN.md` already use: a proposal, explicitly not an approved control
and explicitly without an owner, naming six options with a counted price each, seven decisions
owners have to make, and what has to be verified before any implementation. Three facts were
measured first because the options are priced against them, and ADR 0220 had not measured any of
them: **no code path publishes a presentation at all** — `published=True` appears once in project
code and only as a read filter, `verified_at` is never assigned by anything although a database
constraint and `clean()` both require it on a published row, and the only write to the model is the
projection repair's `.update(...)` of two derived columns; **a command-line import bypasses the
whole receipt layer** — the staff route stages through
`ingestion.receipts.stage_price_with_receipt`, which refuses a missing actor, rechecks it and writes
one `ImportReceipt` whose `actor` is a required `PROTECT` foreign key plus one item per row, while
the command writes no receipt and no items, so its import appears in no inventory at
`/staff/operations/imports/`, has no manifest and no per-row outcome record; and **the command is
the only project write path that is not debug-gated** — neither the command module nor
`pricing/importer.py` mentions `DEBUG`, and staging succeeds with debug off, while the projection
repair, the staff portal and the login throttle all refuse to run outside a debug environment.

 `daroobank/test_attribution_gap_plan.py` (12 tests, ~0.5 s) pins the plan and re-measures both
gaps, including the command's surface (four options, no `--staged-by`; 12 commands and 24 options in
total) and its test surface (8 modules, 16 mentions, 8 committing calls, one operator document), so
a price the plan quotes cannot go stale silently. Eight red checks were applied alone and reverted
from backups, each verified byte for byte: dropping a decision's number (1 failure), paraphrasing a
quoted requirement (1), giving the plan an owner (1), naming a module that does not exist (1),
renaming an option (1), adding `--staged-by` to the command (2), adding `published_by` to the model
(1) and adding a `DEBUG` mention to the importer (1).

 Nothing is implemented and nothing is attributed: no row gained an actor, no command-line import
gained a receipt, no publication path exists, and the candidates already staged from a shell are
still unreviewable. The prices are counted rather than prototyped — no option was built and
reverted, so no cascade was run and a count of pins is a lower bound on the work — the AST scans are
literal, so `setattr`, raw SQL, a variable-bound queryset or a signal would not be seen, and
`override_settings(DEBUG=False)` changes a setting at runtime rather than reproducing a non-debug
process. `docs/SECURITY.md`, `docs/DEVELOPMENT_GUIDE.md`, `docs/PRICE_DATA_MODEL.md`,
`docs/PHASE1_RELEASE_EVIDENCE.md` and ADR 0220's limits now state the receipt absence and name the
plan. See [ADR 0229](ARCHITECTURE_DECISIONS/0229-attribution-gap-plan.md).

## 2026-11-26 — add an opt-in limit on public reads that records nothing

**Changes:** ADR 0223 measured that nothing in this application limits a public request: 48
sequential anonymous reads of six routes all answered 200, no module sent `Retry-After`, and the
only limiter was the debug-only staff login window of ADR 0181, so rate limiting was assigned to
the edge. `docs/SECURITY.md` lists rate limits among the controls this product is supposed to have
and the Phase 1 evidence carries abuse protection as open, which left an operator with nothing to
turn on — including on a development preview that is reachable from the public internet.

This adds a second limiter, opt-in and off by default in every environment.
`staff_security/read_limit.py` counts public reads in a fixed window of 120 per keyed client in a
rolling 60 seconds, under a one-second lock timeout and a two-second statement timeout in one
atomic block; `PublicReadLimitMiddleware` sits directly above `SessionMiddleware`, counts only
`GET`, never a staff path and never a health probe, and refuses an over-limit read with **429**, an
empty body, a `Retry-After` delay and the public privacy headers, which it sets itself because a
refusal is produced before URL resolution; `DAROOBANK_PUBLIC_READ_LIMIT=1` turns it on, with no
debug term, because a floor that cannot be enabled in a non-debug deployment is not a control.

`staff_security_publicreadwindow` stores exactly three columns — a keyed digest of the normalized
address under the scope `staff_security.public_read.v1`, a window start and a count. No path,
route, query, user agent, account or per-read timestamp is stored, and because the login window's
scope is `staff_security.login.client.v1` the two tables cannot be joined on a shared key. ADR
0221's property therefore survives: with the limiter on, a read increments a counter; with it off —
the default — 48 repeated reads still write nothing in any of the 24 project tables. An unkeyable
address, a non-PostgreSQL backend, an open transaction, a backwards clock and any `DatabaseError`
all return `unavailable` and **serve the read**, the deliberate opposite of the login limiter's
fail-closed 503: on a public path, refusing every read because a counter table is unreachable turns
one database problem into an outage.

The change moved 19 pins, measured by running the whole suite against a copy of the tree holding it
(1658 tests, 622.8 s, 20 failures — the twentieth was pre-existing, the decision index listing 0227
above 0226, and was fixed on its own). ADR 0221's suite moves four (middleware 12 → 13, project
middleware 7 → 8, models 23 → 24, tables 32 → 33), ADR 0223's two (one module answering 429 → two,
`Retry-After` in none → one, plus the limiting middleware now pinned rather than absent), ADR 0216's
four (`staff_security` 1 → 2 migrations and 16 → 17 in total, applied 31 → 32, a fresh database
33 tables / 279 columns / 111 indexes / 138 constraints, 17 tables left after `catalog zero`), ADR
0225's five (the fixture fills 24 tables and 31 rows, and the applied, blocked-rollback and forward
counts each move by one), and ADRs 0220, 0222, 0217, 0218 and 0227 one each.

`daroobank/test_public_read_limit.py` (11 tests, ~1.2 s) pins the shape and both states: the
constants, the middleware's position, the key's derivation and its separation from the login key,
the six unkeyable addresses, 48 unlimited reads that write nothing, one keyed row for five reads,
the refusal's status, empty body, delay and headers, the absence of any request marker in the table,
window rollover, a backwards clock, the excluded paths and methods, and a failing database that
serves the read. Eight red checks were applied alone and reverted from backups, each verified byte
for byte: enabling the limiter by default (5 failures across three suites), returning the raw
address as the key (4), adding a `path` column (1 failure and 3 errors), deleting `Retry-After` (1
error), counting `POST` (1), failing closed (1), moving the middleware below the session layer (3)
and deleting the health-probe exclusion (6).

Not load-tested, and not a substitute for the edge provision `docs/DEPLOYMENT.md` still requires —
that guide now says "no rate limit that is on by default" and names this limiter as defense in
depth. One row per distinct client key is kept forever and no command prunes it, so whoever enables
the limiter owns that maintenance; the key is whatever `REMOTE_ADDR` the server sees, so a proxy
that does not set it per client gives every reader one shared window; failing open means the limit
is not a guarantee; and the refusal is an empty 429 with no explanation. See
[ADR 0228](ARCHITECTURE_DECISIONS/0228-public-read-limit.md).

## 2026-11-26 — write down the read-audit decision and measure its price

**Changes:** ADR 0221 measured that nothing records a read and declined to add logging, because an
access log is a decision about retention, reader identity and tamper-resistance that this project
had not made. The requirement behind that decision is not optional: `docs/SECURITY.md` asks for
audit records carrying *"actor, role, target, before/after versions or hashes, decision, time and
request correlation, without PHI in general logs"*, protected *"from modification by application
roles"*; its privacy section requires a recorded legal basis, retention and deletion policy *"with
legal review"*; `daroobank/settings.py` keeps the staff portal development-only *"until MFA,
throttling and audit exist"*; and the operations runbook tells a responder to review access and
audit logs after a restore. What was missing was a decision, and a decision without a price tag is
a guess.

`docs/READ_AUDIT_PLAN.md` is that decision written down in the form `docs/MFA_IMPLEMENTATION_PLAN.md`
already uses: a proposal, explicitly not an approved control, naming the six decisions that block
implementation — scope, identity and privacy, retention, tamper-resistance, placement, enablement —
the two precedents the code already offers (append-only models that refuse `save()` and `delete()`,
and the keyed HMAC of a normalized address in `staff_security/throttle.py` that stores no raw IP),
the two alternatives, and what has to be verified before any enablement.

The price was measured, not estimated. A prototype was built in a scratch copy of the tree — one
append-only `ReadAuditEntry` model in `staff_security`, its migration, and one middleware writing a
row per GET behind a new `DAROOBANK_READ_AUDIT` setting — and nine pin-holding suites were run
against it: 138 tests, **20 failures across 7 suites**. ADR 0221's five pins move (the middleware
tuple, the table inventory, the model-name scan and both sweeps, which write 43 and 12 rows), ADR
0225's five rollback measurements shift with a 24th project table, ADR 0216's four migration pins
move (`staff_security` holds 2 migrations, 17 in total), ADR 0223's three abuse pins move (48
repeated public reads write 48 rows), and ADRs 0220, 0222 and 0217 move one each. On a freshly
migrated throwaway database the prototype measured 33 tables, 283 columns, 113 indexes, 139
constraints, 51 foreign keys and 32 applied migrations against today's 32, 276, 108, 136, 50 and 31,
while `inspect_postgresql_schema` still reported `no_selected_issues`, because its expectations are
derived from the models. The prototype was then discarded: the tree holds no model, no migration, no
middleware and no setting, and reads still write nothing.

`daroobank/test_read_audit_plan.py` (6 tests, ~0.005 s, no database) pins the plan — its proposal
wording, its five sections, the six decisions in order, the requirements it quotes, every suite and
record it names, failure counts that add to 20, the prototype's schema numbers, the seven records it
would supersede, and the continued absence of an implementation. Seven red checks were applied alone
and reverted from backups: deleting the retention decision (1 failure), understating a cascade row
(1), changing the measured column count (1), dropping a record from the supersede list (1), creating
`daroobank/read_audit.py` (1), naming a suite that does not exist (1) and paraphrasing a quoted
requirement (1).

The cascade is a lower bound — nine suites were sampled rather than the full 1632 tests — one design
point was prototyped, no performance property was measured, and the tamper-resistance options are
named rather than evaluated. The plan decides nothing; it makes the decision costed and a quiet
implementation impossible. See
[ADR 0227](ARCHITECTURE_DECISIONS/0227-read-audit-plan.md).

## 2026-11-26 — pin what CI verifies and what it never produces

**Changes:** `docs/DEPLOYMENT.md` asks the release gates to *"Pin and scan dependencies and base
images, generate SBOM where practical, run tests/migrations on staging"*, and the Phase 1 evidence
carries *"immutable production artifacts and image digests"* plus *"staging/release gates"* as
open. The dependency half of that sentence is implemented and was already partly measured; the
artifact half was neither, and no suite read `.github/workflows/checks.yml` at all — the action
pinning lived only in prose in `docs/TESTING_STRATEGY.md`, so a widened permission, an unpinned
action or a published image could land in a diff no test reads, and the continuing absence of a
gate was equally invisible.

`daroobank/test_ci_artifact_gate.py` (9 tests, ~0.004 s, no database) reads the workflow,
`Dockerfile`, `compose.yaml`, the five `tools/` modules and the three requirement files and pins
both halves. What is immutable: one workflow of two jobs and 22 steps triggering only on push and
pull request, exactly `contents: read` at the top level and no job-level permissions, all five
action references pinned to 40-character commit SHAs with their versions commented, both checkouts
disabling credential persistence, 7 packages and 78 hashes in `requirements.txt` plus 2 packages
and 4 hashes in `requirements-build.txt`, `--require-hashes` on the install and on a negative
control that requires pip to reject a zeroed hash, `tools.verify_runtime_lock` running first, and
`pip-audit --strict` run against both the lock and the packages installed inside the built image.

What does not exist: zero occurrences of `upload-artifact`, `build-push-action`, `buildx`,
`docker push`, `sbom`, `syft`, `cyclonedx`, `cosign`, `sigstore`, `attest`, `@sha256:`, `ghcr`,
`retention-days`, `id-token`, `packages:` or `GITHUB_OUTPUT` anywhere in CI; `needs:` and
`environment:` both zero, so no job gates another and none runs in a protected environment; ten
`::error::` annotations and 35 `$RUNNER_TEMP` references as the whole output of a run. All four
base-image references are mutable tags — `postgres:16` three times, `python:3.11-slim` once — so
the same commit can build a different image, and the only image this repository can build is
untagged, has no `USER`, serves through `runserver`, calls itself a development image on its first
line, and is destroyed by `docker compose down -v` inside the run that built it.

Seven red checks were applied alone and reverted from backups: unpinning one checkout to a tag
(1 failure), adding an `upload-artifact` step with `retention-days` (5), widening permissions with
`packages: write` and `id-token: write` (3), adding a `release:` trigger (2), digest-pinning the
postgres service image (3), installing without `--require-hashes` (1) and adding a non-root `USER`
to the Dockerfile (1).

Parsing is textual because the exact runtime lock carries no YAML library, which makes indentation
part of the contract; the suite sees only this repository's CI, so a registry policy or an external
pipeline could implement part of this gate unobserved; absence of a named token is not absence of a
capability; and nothing is checked against a registry or a runner. The gate itself stays open —
this makes its absence fail loudly instead of quietly. See
[ADR 0226](ARCHITECTURE_DECISIONS/0226-ci-artifact-gate.md).

## 2026-11-26 — measure what a rollback does to a database that has data in it

**Changes:** ADR 0216 measured the rollback direction on throwaway databases and named its own
limits twice: *"These are empty databases"* and *"No timing, locking or concurrency is
measured"*. `docs/PHASE1_RELEASE_EVIDENCE.md` carried both as open, which left the question an
operator actually has unanswered — not whether a rollback works, but what it costs.

`daroobank/test_populated_rollback_drill.py` (7 tests, ~19.9 s) populates a throwaway PostgreSQL
database with a pinned fixture — 30 synthetic rows across all 23 project tables plus one staff
account that wrote them, satisfying every check constraint the schema enforces — and then rolls
back. Rolling catalog alone destroys 23 of the 30 rows and leaves an import receipt claiming
`rows=2, created=2` above an item table that no longer exists. Rolling all six apps back destroys
every project row while `auth_user` keeps the account that wrote them. Reapplying returns an
inventory identical to the first migration and all 23 tables empty. A copy of three tables taken
beforehand replays in foreign-key order and restores those rows exactly, and the next insert then
fails on a duplicate key until `setval(pg_get_serial_sequence(…), max(id))` advances the identity
sequence the copy reused.

The busy case uses a real second session holding `SELECT … FOR UPDATE` on one product row while
`migrate catalog zero` runs with `lock_timeout = 2s`. It fails with `canceling statement due to
lock timeout` and leaves the database **half undone**, because the plan is 11 migrations that are
not ordered by app (`ingestion 0002` first, then pricing's two, then catalog 0008 down to 0001)
and each migration commits on its own: 30 of 31 migrations still applied, 31 tables, 47 foreign
keys, 28 of 30 rows, inspection `attention`. The step that died was
`DROP TABLE "pricing_pricecandidatereview" CASCADE` waiting for an `AccessExclusiveLock` on
`catalog_productpresentation`, because dropping a child table has to take the foreign key off its
parent. Migrating forward repairs the schema and restores none of the rows; the same rollback
completes once nothing holds the lock.

Seven red checks were applied alone and reverted from backups: pinning the fixture at three
product presentations (1 failure), asserting the staff account dies with a full rollback (1),
asserting a reapply restores the 30 rows (1), asserting a single-app rollback destroys none (1),
asserting a blocked rollback leaves 31 migrations applied (1), inserting into a restored table
without advancing its sequence (1 error, duplicate key) and asserting that migrating forward
brings the two dropped receipt items back (1).

This is a measurement, not a recovery capability. Thirty rows is a fixture rather than a
representative volume, one shape of concurrency is exercised, the copy round-trip covers three of
23 tables through raw inserts that deliberately bypass the append-only models, Django's own apps
are never rolled back, and no backup, restore tool, recovery objective, staging environment or
rollback **plan** with an owner exists. See
[ADR 0225](ARCHITECTURE_DECISIONS/0225-populated-rollback-drill.md).

## 2026-11-26 — pin the documentation graph so a broken link fails a test

**Changes:** this repository documents itself heavily — 251 markdown files, 224 of them numbered
decision records, cross-linked to each other, to the operator documents, to `SECURITY.md` and to
the suites that measure each decision — and a broken link in that graph fails quietly: a record
citing a suite that was renamed, an index that forgets the newest record because a script
replaced a heading instead of inserting above it, an anchor that stopped matching after a heading
was reworded, a document that survives linked from nowhere. None of that is visible in a diff, a
test run or CI.

`daroobank/test_document_links.py` (7 tests, ~0.09 s, no database) resolves the graph
mechanically: every relative link in `README.md` and `docs/` must point at a file that exists
(895 links, 31 of them external), every fragment must match a heading slug in its target using
GitHub's rule (29 anchors), every document must open with exactly one top-level heading, the 224
decision-record numbers must be unique and contiguous so a record can be superseded but not
silently removed, `docs/ARCHITECTURE_DECISIONS/README.md` must list every record by filename and
link nothing missing, every `.py` path named in a `Suite:` line must exist (14 lines), and no
document except `README.md` may be orphaned. Text inside fenced code blocks is not prose, so the
three shell comments in the development guide that begin with `# ` are not headings and an
example path in a code block is not a link.

Nothing had to be repaired to make it pass; the graph was already intact, and this pins it. Six
red checks were applied alone and reverted: retargeting the index's link to ADR 0223 at a missing
file (3 failures), rewording the heading that `docs/DEPLOYMENT.md` links to (1), deleting the
0223 index bullet (2), pointing ADR 0223's `Suite:` line at a nonexistent module (1), adding an
unlinked `docs/ORPHAN_PROBE.md` (2) and moving `docs/ARCHITECTURE_DECISIONS/0100-*.md` out of the
tree (6).

The pinned counts fail on legitimate growth, including the growth this entry caused, which is the
point: adding a document or a decision record is an event that also updates the pins. These are
mechanical checks — nothing here can tell whether a link points at the right document, whether an
index summary still matches the record it summarizes, or whether a document says something true.
See [ADR 0224](ARCHITECTURE_DECISIONS/0224-documentation-graph.md).

## 2026-11-26 — measure the abuse protection that does not exist, and assign it to the edge

**Changes:** `SECURITY.md` lists rate limits among the controls this product should have and says
the upload size check happens after Django receives the request; neither claim was measured, and
no document said who is responsible for the rest. `daroobank/test_no_abuse_protection.py`
(10 tests, ~1.1 s) measures the shape. The only rate limiting in the project is the opt-in,
debug-only staff login window: the literal `429` appears in exactly one non-test module
(`pricing/staff_views.py`), `Retry-After` appears in none, `staff_security.throttle` is imported
by exactly one non-test module, no project class has a limiter-like name, and the pinned
twelve-entry middleware stack contains no limiter. With the flag forced on and `consume_attempt`
patched, `limited` answers 429 as plain text with no rate-limit header and no CSRF token in the
body, `unavailable` answers 503, `allowed` reaches the login form, and with the flag off the
limiter is never consulted.

Nothing limits a public read: six routes — home, about, price list, search, search API, OpenAPI
document — read eight times each by one anonymous client produce 48 requests, all 200, none
carrying `Retry-After`, `X-RateLimit-*`, `X-Rate-Limit-*` or `RateLimit-*`, every one carrying
`content-security-policy` as the positive control that the header inspection sees headers at all,
and no change in any of the 23 project table counts. No request-size ceiling is configured either:
`settings.py` defines neither `DATA_UPLOAD_MAX_MEMORY_SIZE` nor `FILE_UPLOAD_MAX_MEMORY_SIZE`,
both sit at Django's 2621440 default, no module contains `413`, and the limits that do exist —
1 MiB for product intake, 2 MiB for price staging — are `upload.size` checks in forms, so they run
on a body Django has already spooled. An authorized stager POSTing a 2 MiB + 1 KiB CSV gets a 200
with `form.errors['csv_file']` and no candidate row: refused by validation, not by a ceiling.

`docs/DEPLOYMENT.md` gains an "Abuse protection is external" section stating plainly that the
application has no rate limit and no request-size ceiling, what was measured, and what the edge
must therefore provide — per-client and per-route rate limiting, a size limit that refuses before
the body is buffered, connection and slow-client timeouts and volumetric absorption — reviewed
against the bounded page sizes and the 2 MiB validation limit so a legitimate upload is not
refused by the proxy or accepted by it and refused later by the form. `SECURITY.md` now carries the
measured sentence next to the claim it qualifies.

Six red checks were applied alone, each verified by the failure it produced, and reverted: a second
`429` in `catalog/views.py`; a `Retry-After` header on the login 429, which fails two assertions;
`DATA_UPLOAD_MAX_MEMORY_SIZE` in settings; a second module importing the throttle; a
`RateLimitHeaderMiddleware` added to the stack, which fails 53 assertions including all 48 public
reads; and deleting the new deployment section. An earlier attempt at the `Retry-After` check did
not apply at all and was redone. This pins what happens inside the process: a proxy, CDN, WAF or
host control is invisible to it, the 48-request sweep is not a load test, and the absence of
`Retry-After` is recorded as today's fact rather than as a virtue — adding it would fail the suite
until the record is updated. See
[ADR 0223](ARCHITECTURE_DECISIONS/0223-no-abuse-protection.md).

## 2026-11-26 — document every environment variable where it is set, and pin the inventory

**Changes:** the fail-closed behavior of each configuration variable was already measured
(`test_nondebug_configuration.py`, `test_hsts_configuration.py`, `test_database_configuration.py`,
ADR 0217), but nothing measured the documentation, and it had drifted where it matters most.
`.env.example` named all fifteen variables the application reads and the development guide named
the eleven a local operator sets, while `docs/DEPLOYMENT.md` — the document an operator follows
for a non-debug deployment — named six. It never mentioned `DAROOBANK_DEBUG`, the switch that
decides whether diagnostic pages are served, whether the host and secret guards apply, whether
HSTS is sent and whether the staff portal exists, and it never mentioned a single `POSTGRES_*`
variable, so whether the database connection is verified (`POSTGRES_SSLMODE`) and whether
connections persist (`POSTGRES_CONN_MAX_AGE`) were documented only in files that say they are not
production configuration.

`docs/DEPLOYMENT.md` gains a configuration reference: all fifteen variables with whether each is
required, what a non-debug deployment is expected to set, and what enforces it
(`require_nondebug_secret`, `require_nondebug_hosts`, `parse_hsts_seconds`,
`require_trusted_proxy_networks`, `required_database_setting`, or the decision record behind it),
plus the note that `DJANGO_SETTINGS_MODULE` is the one variable the project only ever defaults.
The development guide now links to it from the line that tells a reader to copy the template.

`daroobank/test_environment_documentation.py` (8 tests, ~0.7 s, no database) reads the inventory
from the code instead of a list anybody keeps: an AST scan of every project module collects each
environment name used as a literal in `os.environ.get(...)`, `os.environ[...]`,
`os.environ.setdefault(...)` or `required_database_setting(...)` and sorts it into four audiences
— fifteen application reads (all in `settings.py`, twelve directly and three through the required
database helper), four opt-in test switches each read by exactly one test module and each
documented in the development guide, the testing strategy or the CI workflow, one default
(`DJANGO_SETTINGS_MODULE`, in four modules) and one foreign variable the project reads
(`GITHUB_ACTIONS`). It then holds each document to that inventory: `.env.example` names exactly
the fifteen in both directions; `compose.yaml` sets exactly eleven variables, all of them read by
the code, with the fail-fast `${VAR:?…}` form for the four that are required — once for the secret
key and twice for each database credential, since both services need those; the deployment guide
names all fourteen variables that are not development-only, says in the debug row's expectation
cell that it stays unset or `0` and names `verify-full` in the TLS row; the development guide
names the eleven a local operator sets and the two audiences together cover the inventory; and no
`DAROOBANK_*` or `POSTGRES_*` name in the README, the operator documents, the testing strategy,
the template, the Compose file or the CI workflow is a variable the code does not read.

Six red checks were applied alone and reverted: deleting the `POSTGRES_SSLMODE` line from the
template, appending a `DAROOBANK_RATE_LIMIT` sentence to the README, adding that read to
`settings.py`, replacing both Compose occurrences of the required database password with a
default, rewriting the debug row's expectation cell, and removing `verify-full` from the TLS row.
Three earlier attempts at these red checks were themselves faulty — a prefix filter that missed a
commented assignment, replacing only the first of two Compose occurrences, and removing one
off-marker from a row that still said "off" in another column — which is why occurrences are now
checked individually and the content checks read one table cell rather than a whole line. This
checks names, not meaning: it cannot tell whether a documented default, range or warning is
correct. See [ADR 0222](ARCHITECTURE_DECISIONS/0222-documented-environment.md).

## 2026-11-26 — record and pin that nothing logs a read

**Changes:** ADR 0220 measured who a row names; the other half of an audit question had no
answer and nothing said so. `SECURITY.md` asks for audit records carrying actor, role, target,
decision, time and request correlation, `settings.py` opens by saying the staff portal stays
development-only until MFA, throttling and audit exist, and the operations runbook told an
incident responder to "review access/audit logs after restoration" — an instruction that cannot
be followed inside this application.

`daroobank/test_no_read_audit.py` (8 tests, ~0.9 s) pins the absence from four directions.
Configuration: `settings.LOGGING` is `{}`, Django's default with no handler, logger or file,
and `MIDDLEWARE` is exactly twelve pinned entries of which the seven project ones set privacy
headers, resolve the proxy scheme or guard staff sessions — the guard deletes sessions; nothing
records a request. Code: no module in the seven project packages imports `logging`, checked by
parsing the AST, with a positive control that the same scan finds `catalog/intake.py` importing
`json`. Schema: exactly the 32 tables ADRs 0216 and 0218 pin, by name, no `django_admin_log`,
and no project model whose camel-case name contains an `access`, `audit`, `event`, `log`,
`track` or `visit` token — matched on words so `StaffLoginWindow` does not match on "log" —
while the four revision tables do carry `recorded_by_id` and `created_at`: writes are recorded,
reads have no counterpart. Behavior: a fully permitted account GETting all 43 staff routes with
a missing primary key answers 19×200, 18×404, 6×405 and never 403 and creates no row in any of
the 23 project tables and no session row, an anonymous sweep of all 12 public routes answers
8×200 and 4×404 and likewise writes nothing, and as a positive control the same counter sees an
ORM insert and sees the one session row the login itself creates.

Four red checks were applied alone and reverted: appending `import logging` and a module logger
to `catalog/services.py`; adding a `LOGGING` dictionary to settings; adding an `AccessLog` model
with its migration plus a middleware that writes one row per response — which fails the
middleware pin, the 32-table inventory and both sweeps, counting 43 rows after the staff sweep
and 12 after the public one; and adding the same model without a migration, which fails the
model-name pin and errors the three database tests.

No logging was added. Whether this product needs a read audit is a governance decision with
retention, PHI and tamper-resistance consequences, and it stays open; what changed is that the
gap is measured, and the runbook and `SECURITY.md` no longer imply an access log exists. The
suite cannot see recording outside the process — a proxy access log, PostgreSQL statement
logging, a host audit daemon or an APM agent — and `DEPLOYMENT.md` arranges none.
See [ADR 0221](ARCHITECTURE_DECISIONS/0221-no-read-audit.md).

## 2026-11-26 — measure who a row names, and pin the two places where it names nobody

**Changes:** ADR 0218 removed the component that would have kept a `django_admin_log` row for
administrative changes, which makes "who did this, and when?" a question about this schema
rather than about a log. The answer was never written down. `daroobank/test_actor_attribution_inventory.py`
(10 tests, ~0.8 s) measures it: of the 23 project models, 19 carry a foreign key to the account
responsible — `staged_by`, `reviewer`, `recorded_by`, `author`, `actor` — every one of them
`on_delete=PROTECT` so deleting an account cannot erase attribution, 18 of them `NOT NULL`, and
each paired with an `auto_now_add` creation timestamp (`created_at` on 16, `collected_at` on the
two candidates, `recorded_at` on `SourceClaim`). No project model has an `auto_now` field at all:
the schema records when a row appeared and never when one changed, because every staff write
appends a new row rather than editing one.

The four models that name nobody are pinned with their reason: `FormulationComponent` and
`ImportReceiptItem` are children whose required, protected parent link reaches an attributed
parent; `StaffLoginWindow` is a synthetic throttle row keyed by an address digest; and
`catalog.ProductPresentation` — the published catalog record the public reads — has no actor
column, no creation timestamp and no create call site anywhere in the project. It is named by
exactly seven non-test modules and written by exactly one, the projection repair, which a
PostgreSQL-backed test shows reports `fields: {irc_normalized, search_text}`, leaves every other
column of the row byte-identical and creates **no row in any of the 23 tables**: the only
in-app write to the published catalog leaves no attribution anywhere.

The second exception is behavioral. `PriceCandidate.staged_by` is the one nullable actor column,
and the two staging entry points differ: `manage.py stage_price_csv --commit --attest-authorized`
stores a candidate naming no account, while the staff import route passes the session account
(ADR 0195 records that actor-less CLI staging is deliberate). What had not been measured is the
cost — a reviewer holding `pricing.review_pricecandidate` gets a 200 detail page with no stager,
`can_review` false and no review form, and since an identical payload reuses the existing row,
replaying that candidate through the route never gives it an actor: a row first staged from the
command line is permanently unreviewable in the portal. The development guide now says so where
the command is documented.

Five red checks were applied alone and reverted: adding a `ProductPresentation` create call site,
making a second actor column nullable, adding an `auto_now` field, dropping
`display_stager is not None` from the portal's `can_review` rule, and making the importer fill in
`staged_by` on replay — each fails the assertions that carry it. This is attribution, not an
audit: nothing measured is tamper-resistant, reads are not recorded, no management command
records its operator, and whether an unattributed candidate should be reviewable is an open
governance decision. See
[ADR 0220](ARCHITECTURE_DECISIONS/0220-actor-attribution-inventory.md).

## 2026-11-26 — document the staff login throttle and hold the command surface to the operator documents

**Changes:** with `django.contrib.admin` deliberately absent (ADR 0218), management commands
are the only administrative interface outside the staff portal, and an inventory of them
against the operator documents had drifted. `cleanup_staff_login_windows` — the only way to
keep `staff_security_staffloginwindow` from growing without bound — was named in no operator
document, only inside ADR 0181 and ADR 0218. `revoke_staff_sessions --all` was documented
nowhere; the runbook showed only `--username`. And the development guide's staff paragraph
listed "login throttling" among capabilities that "remain missing" although a limiter exists
behind `DAROOBANK_STAFF_LOGIN_THROTTLE=1`.

The development guide gains a section on the opt-in throttle (ten attempts per client key in a
rolling sixty seconds, a no-op inside a test transaction, not a production abuse control) and
on both forms of `cleanup_staff_login_windows`, including the bounds the command sets for
itself: debug-only, PostgreSQL in autocommit, a one-second lock timeout and a two-second
statement timeout, at most 500 rows per run, oldest first, with each row's age rechecked after
any lock wait. The "missing capabilities" sentence now says *production-grade login abuse
protection* and names the development limiter as not being one. The runbook documents
`--all --apply` alongside `--username` and states that both forms are read-only without
`--apply`, delete at most one bounded batch and print one JSON object.

`daroobank/test_command_documentation.py` (7 tests, ~0.01 s, no database) holds the documents
to the registry: a pinned inventory of the twelve commands across five apps, command files and
registered names as the same set, every command named in at least one operator document, all 24
project-specific options mentioned in the documents that name their command (read from each
command's live parser, so a new option is a documentation event), each of the four
write-capable commands documented as read-only without its `--apply`/`--commit` flag and
documenting that flag, every `manage.py <name>` mentioned in the README or the operator
documents existing, and the operator documents not being empty. Deleting the new guide
section, removing `--all` and adding an undocumented probe command together fail six
assertions across five tests; replacing the deployment guide with a stub fails the emptiness
guard. This checks that commands and options are *named*, not that the prose around them is
correct, safe or current — a document may still describe `--apply` as read-only and pass.
See [ADR 0219](ARCHITECTURE_DECISIONS/0219-documented-command-surface.md).

## 2026-11-26 — record why `django.contrib.admin` is not installed, and pin its absence

**Changes:** the roadmap asks for an "auth/admin baseline" and the technology decision
record names Django's admin as a reason to pick Django, but the implementation never
installed it and nothing recorded why — the shape of an omission that gets "fixed" later
with one line in `INSTALLED_APPS`. ADR 0218 records the decision: the administrative
surface is the hand-built staff portal, whose 43 routes are measured across ADRs 0199–0217
and collected in the generated authorization review, and the admin would add a second
surface with its own login and password-change routes, `is_superuser`-driven permissions, a
`django_admin_log` table, a route per model per action, and none of that measurement — plus
two template context processors that Django's own system checks demand and that would apply
to every public render. `daroobank/test_no_django_admin.py` adds 7 tests (~1.1 s) pinning
the absence: exactly eleven installed app labels with none containing `admin`; seven admin
paths raising `Resolver404` while `/staff/login/` resolves; `GET /admin/` answering a
byte-identical 179-byte plain 404 to an anonymous caller and to a logged-in superuser with
no `administrator`, `Django admin`, `Log in`, `csrfmiddlewaretoken` or `username` marker;
only `django_content_type`, `django_migrations` and `django_session` among the `django_*`
tables, no table matching `%admin%`, 32 tables in total; no module in the seven project
packages importing the admin, checked by parsing the AST with a positive control that the
same scan finds `django.contrib.sessions` imports; every named route in the resolver being
one of the 43 staff routes or one of the 12 probed public routes; and the five operational
commands still registered with their app labels. Two supporting fixes came out of the red
check: `daroobank/authorization_review.py` now walks nested resolvers instead of raising
`AttributeError` on a mounted `include()`, and reports a non-staff route with no probe row
as uncovered instead of raising `KeyError` — the generated review is byte-identical for the
current flat URLconf. The "no third surface" assertion takes its public set from the ADR
0202 probe matrix rather than from the walked inventory, or a newly mounted surface would
define itself as public and the check would pass.

**Limits:** this pins an absence, not the adequacy of what replaces it; the review's
judgement is still unsigned. The app-label assertion fails on any installed-app change,
including a legitimate one, which is deliberate but means the judgement lives in editing the
test. The AST scan cannot see `importlib` loading, an app pulled in by a third-party
package, or an admin mounted from an included URLconf. The 179-byte assertion pins today's
not-found page. Not installing the admin also gives up `django_admin_log`: domain review
rows record who staged and reviewed each candidate and ADRs 0192–0199 recheck the actor
inside those writes, but there is no general administrative change log, and that gap belongs
to the governance gate. One red check: installing and mounting the admin — with the messages
app, middleware and the two context processors — fails all seven tests plus three in the
review drift suite, and without the context processors `manage.py test` stops at `admin.E402`
and `admin.E404` before the suite runs at all.

## 2026-11-26 — report the settings a deployment has to get right, in one read-only command

**Changes:** `manage.py check_deployment_readiness` collects what `health/ready/` (one
`SELECT 1`), the non-debug startup checks (which refuse to boot but say nothing afterwards)
and `inspect_postgresql_schema` (model-derived database expectations) each cover only in
part. It reads settings and the migration table, writes nothing, prints one JSON report and
exits 1 when not ready. Ten **required** checks decide `ready`: debug off, staff portal
off, secret shape via the existing `require_nondebug_secret`, explicit hosts via
`require_nondebug_hosts`, secure session and CSRF cookies, the session flags ADR 0208 pins,
HTTPS redirection, no pending migrations, no applied migration without a file in this
release, and a reachable database via the existing `database_ready()`. A separate
**review** list carries conditions that need a decision rather than a fix — HSTS off,
HTTPS redirection with no trusted proxy header, development hostnames, health probes
answering, the synthetic login limiter, `XFrameOptionsMiddleware` absent — and `--strict`
fails on those too. In the synthetic environment the command reports not ready and names
the four checks that fail there; against a hardened test fixture it reports ready with an
empty review list and exits 0. `daroobank/test_deployment_readiness.py` adds 10 tests whose
point is that every required check can fail on its own: seven broken alone from the
hardened fixture, an unmigrated throwaway database failing `migrations_applied` with 31
pending, an applied row for `catalog.0099_never_written` failing
`migration_history_consistent`, a run inside an open transaction failing
`database_reachable`, each of the six review conditions appearing alone with a reason, two
runs byte-identical, the secret value and its first 24 characters absent from the output,
and no writes to the 14 counted domain models, the migration table or the database list.
`daroobank` was added to `INSTALLED_APPS` so a command belonging to the project rather than
to one domain app is discoverable; it declares no models, so the schema inventory ADR 0216
pins is unchanged and 96 tests across the schema-sensitive suites still pass. The command is
named in `docs/DEPLOYMENT.md` and in `docs/OPERATIONS_RUNBOOK.md`, which also gained a
deployment-readiness section and, under the security/privacy incident steps, the staff-session
containment procedure that uses `list_staff_sessions` and `revoke_staff_sessions`;
`docs/AUTHORIZATION_REVIEW.md` was added to the README document index, and one test now fails
if either the runbook and deployment guide stop naming the readiness command or the README
stops linking the review.

**Limits:** a zero exit status is **not** a deployment authorization. The report describes
the shape of one process's settings and one database connection; it serves no request and
checks nothing about collected static files, logging, clock synchronization, connection
pooling, replicas or external dependencies. The hardened fixture is a test fixture, not a
recommended production profile — real values depend on TLS topology, proxy configuration and
hostnames that do not exist yet. The report is only as complete as its ten checks, review
items are prompts rather than decisions, and `migration_history_consistent` cannot detect a
release older than its database in any other way, a squashed history or an out-of-order
apply. Nothing aggregates, stores or alerts on these reports, and the command has never run
against a real deployment. Two red checks: making `debug_disabled` unable to fail, and
echoing the secret into a detail line, each fail exactly one test. Documenting this work
also destroyed two `## ` entry headings in this file — a patch script replaced a heading
instead of inserting above it and nothing noticed — so both were restored and
`daroobank/test_release_notes_structure.py` (2 tests, no database) now fails on that
defect: headings must be unique, the four legacy undated headings are pinned so a new
entry cannot join them, dated entries must stay newest-first, and every `**Changes:**`
paragraph must sit under its own heading. Structure only; it cannot judge accuracy.

## 2026-11-26 — measure migration rollback and reapply on throwaway databases

**Changes:** `daroobank/test_migration_reversibility.py` adds 7 tests (~5.7 s) covering the
direction the Phase 1 data-model gate names but nothing had measured. Each test creates its
own throwaway PostgreSQL database (`daroobank_migration_probe_<12 hex>`), migrates it,
rolls back and reapplies, and drops it in a `finally`; one test asserts no probe database is
left behind. The probe connection is registered dynamically instead of being added to
`DATABASES`, because a test case may only reach the aliases it declares and Django allows
runtime connections — declaring the alias instead makes every migration call fail with
`DatabaseOperationForbidden`. The existing model-derived inspection is reused by patching
`postgresql_inspection.connection`, so a freshly migrated probe database must report
`no_selected_issues` and a rolled-back one `attention`. Measured: 16 migrations over six
apps, each app one linear chain from its `0001_initial`; exactly two data operations, both
`RunPython`, both reversing to `migrations.RunPython.noop`; a fresh database holding 32
tables (23 project tables), 276 columns, 108 indexes, 136 constraints, 50 foreign keys and
31 applied migrations; `migrate catalog zero` unapplying exactly the 11 migrations derived
from the graph as its dependents (catalog's 8, pricing's 2, ingestion's 1) and leaving 16
tables, 17 foreign keys and no foreign key without its target table; a full rollback of all
six apps leaving only Django's own tables; and the reapply reproducing an identical column,
index and constraint inventory. `makemigrations --check --dry-run` now also runs inside the
suite, mirroring the CI step. The cascade expectation is derived from
`MigrationGraph.backwards_plan` over every catalog migration — nothing depends on catalog's
leaf, so the leaf alone yields an empty plan.

**Limits:** every database in this suite is empty, so nothing here shows a rollback with
data in it; Django drops tables and columns without preserving their contents, and a real
rollback plan still needs a backup and restore step, an environment, an order and an owner.
The two no-op reverses mean a rollback of catalog 0002 or 0004 leaves the backfilled rows
behind. PostgreSQL only, one server, one role that may create databases, no staging
environment. No timing, locking or concurrency is measured, and rollback of Django's own
apps is not. The comparison covers columns, indexes and constraints in the `public` schema.
Three red checks: a model field with no migration fails three tests, removing a no-op
reverse fails one and errors two with
`django.db.migrations.exceptions.IrreversibleError`, and adding an empty migration fails
four.

## 2026-11-26 — collect the endpoint-by-endpoint authorization inventory, generated from the resolver

**Changes:** the Phase 1 checklist has carried an open gate reading "complete
endpoint-by-endpoint authorization review". The inventory that review has to be based on
was already measured across four suites but existed nowhere as one reviewable document,
and typing it would have created a fourth copy of the route names that goes stale
silently. `docs/AUTHORIZATION_REVIEW.md` now carries both tables between `GENERATED`
markers, produced by `daroobank/authorization_review.py` from the live URL resolver,
`test_staff_authorization_matrix.ROUTES` (the requirement each staff route declares),
`test_staff_csrf_gate` and `test_staff_method_sweep` (the allowed methods),
`test_staff_write_route_inventory` (which routes write and which in-flight test covers
them) and `test_public_route_privacy_matrix.PUBLIC_ROUTES` (the non-staff probes and their
expected statuses). `write_review()` replaces exactly that block and refuses to rewrite a
document whose markers are missing. It reports **43 staff routes** — 36 requiring `all of`
a permission list, four requiring `any of` one, one requiring `is_staff` alone, two
authentication endpoints stating their own requirement — and **12 non-staff routes** across
17 probe rows, with 14 routes classified as writing and 29 as read-only.
`daroobank/test_authorization_review_drift.py` adds 12 tests, run in ~0.01 s with no
database: the block must match a fresh render byte for byte under four different
`PYTHONHASHSEED` values, the counts and route-name sets must match the resolver in both
directions, every row must agree with its derived counterpart in all five data columns,
every cited ADR number must have a document, every module named in a writes column must
exist and still park a write around a password invalidation, the document must keep stating
its own limits, and the sign-off table's owner, date and answer cells must stay empty.

**Limits:** this is the inventory, **not** the review the gate asks for. Nobody has judged
whether a requirement is correct, there is no threat model, and threat modeling plus an
independent security assessment remain open. Everything was measured against synthetic data
in a test transaction on a DEBUG-only portal — `STAFF_PORTAL_ENABLED = DEBUG`, and every
`/staff/…` request is answered 404 when the flag is off — so describing these routes
precisely is not a recommendation to expose them. Generated content is only as true as its
inputs: if a suite stops covering a route without the matrix changing, the evidence column
keeps citing it, and the drift test can verify that cited ADRs exist and that named modules
mention their route but not that a suite still sends requests to every route it claims. The
tables cover the URL surface only, not management commands, middleware, signals or
background jobs. Two red checks: dropping `sources.add_sourceclaim` from a route's declared
requirement fails two assertions, and citing a nonexistent ADR `0299` fails 43. One real
defect surfaced while writing this: `AUTH_ROUTES` is a frozenset, so iterating it to place
the two authentication endpoints made the generated block depend on the interpreter's hash
seed; the render now uses an explicit `AUTH_ORDER` tuple asserted equal to that set.

## 2026-11-26 — add a read-only inventory of synthetic staff sessions

**Changes:** `staff_security/management/commands/list_staff_sessions.py` reports which sessions are in the store, whose they are, and which of them the ADR 0213 guard would end on the next request — the dormant sessions a guard that only fires on arrival cannot itself see. It is read-only, development-only, scans at most 5 000 unexpired sessions and emits one JSON report: per account `account_id`, `username`, `account_exists`, `is_active`, `is_staff`, `is_superuser` and `session_count`; per session `alias`, `bound`, `expires_at` and `guard_would_end_it`. The alias replaces the key — the first 32 hex characters of `salted_hmac('daroobank.staff.session.inventory.v1', session_key)` — so sessions can be told apart and two reports compared without the output being usable as a credential; no session key, cookie value or stored digest is emitted. Expired sessions are excluded, a non-integer session identity is skipped, a session whose account was deleted is still listed with `account_exists: false` and flagged, and `--username` narrows the report while an unknown or empty username is a `CommandError` rather than an empty-looking store. `daroobank/test_staff_session_inventory.py` adds 7 tests, including the residual case end to end: deactivate an account with no intervening request, see the row still listed and flagged, revoke it, see the report empty. Emitting the key instead of the alias fails three assertions.

**Limits:** aliases are keyed on `SECRET_KEY`, so a rotation breaks correlation between reports, and a truncation identifies without authenticating. The report contains usernames and account flags, so it is sensitive operational output and a production inventory with access control, audit and retention remains an open gate. Scanning is linear with a 5 000 cap and no pagination cursor; `scanned` and `scan_limit` make a partial report visible but do not fix it. It records no history and is not an audit log, and it covers database-backed sessions only.

## 2026-11-26 — end a staff session when its account state changes

**Changes:** this is the first change to production code in this series, and it closes the release blocker ADR 0191 named. `daroobank/session_guard.py` binds each session at login (through a `user_logged_in` receiver) to `salted_hmac('daroobank.staff.session.v1', …)` over `is_active`, `is_staff`, `is_superuser`, the session-auth hash and the account's effective permissions, direct and group. `StaffSessionGuardMiddleware`, last in `MIDDLEWARE` and only on staff paths, recomputes that digest for the account the session names and calls `logout()` on any difference, on a missing or malformed digest, or when the account no longer exists; the request then continues anonymous, so all 41 staff routes answer the 302 an expired session already produced and no view changed. Deactivation, staff-flag removal, removing one or all permissions, clearing a group's permissions, leaving a group, deleting the account and changing the password each delete the session row, and restoring the state does not revive it. Two measurements drove the design: the documented revival reproduced (302 while inactive, 200 after reactivation), and a guard written against `request.user` could not see the change at all, because the default backend resolves no user for an inactive account — that variant was built first and left the gap open. Signals were rejected because `QuerySet.update()`, which the tests and any incident script use, emits none. Grants end sessions as revocations do; edits that cannot change effective access (a superuser's own grants, joining an empty group) do not. `staff_security/management/commands/revoke_staff_sessions.py` deletes the sessions of one account or all of them — read-only unless `--apply`, at most 5 000 scanned and 500 deleted per batch, JSON report, development-only — for the transition no request observes. `daroobank/test_staff_session_guard.py` adds 12 tests over all of this, including a walk of all 41 routes behind a positive control and a check that public reads are untouched. Enabling the middleware produced 257 failures in 7 pre-existing tests that encoded per-request denial; five were updated, including the two that demonstrated the gap, which are now inverted. Removing the middleware fails 263 assertions and the `request.user` variant fails exactly 4 tests. The full synthetic suite is 1 528 tests with 9 skips.

**Limits:** the guard fires only when a request arrives, so an off/on transition that no request observes leaves a dormant session usable until it is revoked explicitly; closing that would need a write-time counter, and signals are bypassed by `.update()`, so it would take a database trigger. A request that has already passed the guard runs to completion, backend removal from `AUTHENTICATION_BACKENDS` is not observable at request time, there is still no session inventory or lifecycle UI, the revocation command is development-only, and MFA, replay protection and any production procedure with audit and ownership remain open. Each staff request costs three extra queries; public reads cost none. Account lifecycle and MFA remain production gates.

## 2026-11-26 — exclude the per-second `Expires` stamp from parity comparisons

**Changes:** CI run `45832496897` (`bad5999`) failed on `test_staff_method_sweep.StaffMethodSweepTests.test_the_method_gate_runs_before_authorization` while a full local 1 515-test regression at the same commit passed. The comparison, not the new suites, was at fault: `LoginView` and `LogoutView` are wrapped in `never_cache`, which stamps `Expires` with second granularity, and `comparable()` in `daroobank/test_staff_denial_parity.py` excluded only `Date` and `Set-Cookie`. Two identical logout requests straddling a second boundary therefore compared unequal. Measured directly: logout GET 405 and logout/login OPTIONS 200 all carry `Expires`, and 1.2 s apart `comparable()` returns False. Of the 43 staff routes only those two class-based endpoints emit the header — the 41 function views do not, and CSRF rejections are produced by middleware before any view, which is why the ADR 0204–0207 comparisons were unaffected. `expires` is now in the shared `VOLATILE_HEADERS`, and `test_the_comparison_ignores_the_per_second_expires_stamp` requires, for both auth endpoints, that `Expires` is present, that two answers 1.1 s apart carry different stamps, and that they still compare equal — so the exclusion cannot be reverted silently or go vacuous. The method sweep is now 10 tests, roughly 22 s; the five parity suites (34 tests) pass together in optimized mode. No production code changed.

**Limits:** Parity comparisons now ignore `Expires` everywhere, so a route that began emitting a wrong `Expires` would not be caught by them; caching stays pinned by ADR 0210, which requires exact `Cache-Control` and `Pragma` values on all 1 204 swept responses and a closed header inventory. The guard test depends on a wall-clock sleep, and any other per-second header a future view emits would have to be excluded the same way. The earlier green CI runs for `b870959` and `0134e26` were timing luck rather than evidence the comparison was sound.

## 2026-11-26 — probe caller-controlled redirect targets on the staff surface

**Changes:** `daroobank/test_staff_redirect_targets.py` sends 21 caller-supplied `next` values — 12 hostile (protocol-relative, absolute, single-slash, backslash, `javascript:`, `data:`, embedded userinfo, upper-cased scheme, leading space) plus 8 that Django's validator accepts and the empty string — to the login and logout endpoints and to all 41 matrix routes. A hostile value never becomes a target: a successful login falls back to `/staff/`, logout to `/`, a failed login emits no `Location` at all, logout answers 405 to GET, and each of the 492 anonymous route redirects lands on `/staff/login/` with the requested staff URL — not the hostile value — as its own `next`. Following any chain stays on-host and inside {200, 302, 400, 403, 404, 405, 409}. The login form echoes only the validated target, so a hostile value renders as an empty hidden input; eight other parameter names are ignored; a duplicated query parameter resolves to its unsafe last value; and a body `next` beats a query one. Accepted values are honoured verbatim after `iri_to_uri`, each with an empty netloc, and the suite changes no row in the 14 counted models. A naive `get_redirect_url` override on the login view produces 25 failures.

**Limits:** `allowed_hosts` is `{request.get_host()}`, so whatever a deployment accepts as a `Host` header becomes an allowed target; `require_https` is false for these plain-HTTP requests. `/%2f%2fevil.example/` is emitted unchanged because `urlsplit` does not decode `%2F`, and a relative target without a leading slash is emitted as-is for the browser to resolve — both recorded as observed behavior, not proven safe. Only form-encoded `next` on these two endpoints and on anonymous route redirects is probed.

## 2026-11-26 — pin the complete staff response-header inventory

**Changes:** `daroobank/test_staff_header_inventory.py` sweeps all 43 `staff_*` routes with seven methods (GET, HEAD, OPTIONS, PUT, PATCH, DELETE, POST) and four account shapes — 1 204 responses — and pins the whole header surface. Seven headers must appear on every response with exact values: `Cache-Control: private, no-store, max-age=0`, `Pragma: no-cache`, `X-Robots-Tag: noindex, nofollow`, `Referrer-Policy: same-origin`, `X-Content-Type-Options: nosniff`, `Cross-Origin-Opener-Policy: same-origin` and the development `Content-Security-Policy` verbatim. Nine further names are tolerated only in a pinned shape: `Allow` appears solely on a 405 or on the 200 OPTIONS answer of the two class-based endpoints, with one of the five values ADR 0209 recorded; `Content-Type` is HTML everywhere except the two sample downloads, which are the only routes allowed `text/csv` and the only ones carrying `Content-Disposition`; a 302 `Location` goes to the staff login or home and cannot be turned off-host by a `next` parameter. Any other header name fails, every status must be in {200, 302, 400, 403, 404, 405, 409}, and the sweep changes none of the 14 counted write and audit models. Removing one line — `Pragma` — from `_staff_headers` produces 1 205 failures.

**Limits:** The inventory describes the synthetic test configuration, where `DEBUG` is true: `X-Frame-Options`, `Strict-Transport-Security` and secure cookie flags are absent there and are deliberately not exempted, so running the suite against a non-debug configuration fails the closed-set check on purpose. The CSP is compared against `DEVELOPMENT_CSP` by import, so a divergent production CSP would not be caught here. Header order is not asserted, TRACE and CONNECT are not sent, and per-route status counts belong to ADR 0200, 0205 and 0209 rather than being duplicated.

## 2026-11-26 — sweep six HTTP methods across every staff route

**Changes:** `daroobank/test_staff_method_sweep.py` sends GET, HEAD, OPTIONS, PUT, PATCH and DELETE to all 43 `staff_*` routes with real rows in place, for five account shapes. PUT, PATCH and DELETE must be rejected with an empty 405 on every matrix route and on logout, and must never be named in `Allow`; `Allow` must equal exactly what the decorators declare — `GET, HEAD` on the 27 safe-only routes, `GET, POST` on the 9 dual-method routes, `POST` on the 5 review routes, `POST, OPTIONS` on logout and `GET, POST, PUT, HEAD, OPTIONS` on login; HEAD must mirror GET in status and headers on the safe-only routes and login and answer 405 elsewhere; OPTIONS must be 405 on function views and 200 with `Allow` on the class-based endpoints; and a method rejection must be byte-identical for a fully permitted and a permissionless account. The login form's accepted PUT (Django's `ProcessFormView.put` delegating to `post`) must create no session, and a separate `TransactionTestCase` shows ten PUT attempts fill the opt-in throttle window so a following POST with correct credentials returns 429, and ten POST attempts block a following PUT. Sweeping everything leaves fourteen write and audit model counts unchanged. A red check — widening `catalog/quality_views.py::quality_irc` to accept DELETE — failed three assertions before being reverted. No production code changed. See ADR 0209.

**Limits:** HEAD is recorded as unsupported on nine form routes, five review routes and logout, which is an availability detail for caches and monitors rather than an authorization control. PUT and PATCH carry an empty JSON document, so payload validation is not exercised. TRACE and CONNECT are not sent. The login PUT behavior is Django framework behavior, with CSRF coverage from ADR 0207 and throttling measured only in the two directions above. `Allow` expectations are pinned to today's decorators. ADR 0191 remains a release blocker.

## 2026-11-26 — walk session lifecycle events across every staff route

**Changes:** `daroobank/test_staff_session_lifecycle.py` drives four lifecycle events against one fully permitted staff account and walks all 41 matrix routes after each, requiring a 302 to the staff login with `no-store` and `noindex, nofollow`: an explicit logout (which must delete the session row, leaving the login page reachable at 200 and logout POST-only at 405), a replayed pre-logout cookie, a password change behind the session's back (the account keeps `is_active`, `is_staff` and all 16 permissions, and a fresh login with the new password works), and an expiry forced into the past. Every walk is preceded by a positive control asserting the same session reached the workspace and a real source-claim detail page moments earlier, so a blanket redirect cannot pass vacuously. The documented session settings are pinned (`SESSION_COOKIE_AGE == 3600`, browser-close expiry, `HttpOnly`, `SameSite=Lax`) and all four walks leave fourteen write and audit model counts unchanged. A red check — replacing `StaffLogoutView.post` with a redirect that never flushes the session — failed the replay assertion and the logout walk before being reverted. No production code changed. See ADR 0208.

**Limits:** This covers the password field only. Deactivating and reactivating an account, changing permissions or groups, removing a backend or rotating a session key without touching the password still does not end an existing session; ADR 0191 remains an open release blocker. Expiry is forced by writing `expire_date` directly, so clock skew, non-database session stores and `SESSION_SAVE_EVERY_REQUEST` are untested. No administrative log-out-everywhere control exists, and the replay case reuses a cookie value in a new test client rather than modeling theft or fixation.

## 2026-11-26 — measure the CSRF gate across every staff route

**Changes:** `daroobank/test_staff_csrf_gate.py` probes all 43 `staff_*` routes with real rows in place under `enforce_csrf_checks=True`. A token-less POST must produce one single canonical 403 across five account shapes (215 requests, one distinct response in status, body and headers, with the staff privacy headers); a client holding a CSRF cookie but sending no token must get one identical 403 on every route and the same body whatever its permissions; a valid token with `Origin: https://evil.example`, a mangled token, a foreign token and an empty token header must be indistinguishable; and with a valid same-session token each route must answer as its view decorators declare — 405 with an empty body and `Allow: GET, HEAD` on the 27 safe-only routes, 400 on the 5 POST-only review routes, a rendered form on the 9 dual-method routes and login, 302 on logout. An account without the route's permission still gets 403 once the token is accepted. The 5/9/27 classification is read from the decorators and pinned, and the suite asserts the POST-only set equals the routes the authorization matrix marks POST. Every probe leaves fourteen write and audit model counts unchanged. A red check — adding `@csrf_exempt` to `clinical/staff_views.py::review` — failed four assertions before being reverted. No production code changed. See ADR 0207.

**Limits:** The ordering is a Django framework property; the suite pins its consequences so a future exemption or middleware reordering is visible. The cookie-less and cookie-holding rejection bodies differ, which reveals a client's own prior navigation rather than permissions, and is asserted rather than ignored. Origin checking used one hostile origin and no Referer, so HTTPS referer validation, `CSRF_TRUSTED_ORIGINS`, token rotation and session-bound masking are not measured here. Valid-token posts send empty bodies, so they prove form handling was reached, not that submissions succeed. ADR 0191 remains a release blocker.

## 2026-11-26 — measure query-parameter parity across all staff routes

**Changes:** `daroobank/test_staff_query_parity.py` builds one receipt per kind with a distinct source name and URL and probes all 41 staff routes with nine caller-controlled query shapes across five account shapes. An unauthorized denial must stay byte-identical for every variant, an authorized request must never produce a 500 and must keep `no-store` and `noindex, nofollow`, the anonymous redirect must not change, and a kind filter must not widen scope: a product-only account sees its own receipt name and never the price receipt's name or URL, gets a 403 for `?kind=price` whose body contains neither, and gets a cross-kind detail or manifest-inspection response byte-identical to a receipt that does not exist. The only legitimate query-driven 403 — the receipt list's kind filter — is pinned as such. Probing every route with every variant and shape leaves fourteen write and audit model counts unchanged. A red check (dropping `kind__in=kinds` from `ingestion/staff_views.py::receipt_detail`) rendered the cross-kind receipt and failed the assertion before being reverted. No production code changed. See ADR 0206.

**Limits:** Nine variants are a sample, not fuzzing: no generator, dictionary or coverage measurement is involved. The suite asserts statuses, headers and marker absence, not that each route interprets its parameters correctly; a route that silently ignored a parameter would pass. The allowed status set is pinned and must be reviewed when a route changes. Hostile values are appended raw to POST URLs, so encoding is the test client's. Timing is not compared. ADR 0191 remains a release blocker.

## 2026-11-26 — measure identifier-shape and method parity on staff object routes

**Changes:** `daroobank/test_staff_identifier_parity.py` probes all 23 staff object routes with thirteen invalid identifiers and both method directions across five account shapes, reusing the ADR 0201 row fixtures. Identifiers the `<int:pk>` converter accepts must give one identical 403 to every unauthorized shape (existing row included) and one identical 404 to every authorized shape; identifiers it rejects must give the same unmatched-URL 404 to every shape, anonymous included, with the staff privacy headers; a wrong method must be answered identically for all authenticated accounts, as an empty 405 with an `Allow` header on the 14 safe-only and 5 POST-only routes and with no method gate on the 4 dual-method form routes; and anonymous requests redirect to login everywhere. Probing every identifier plus the wrong-method request against existing rows leaves fourteen write and audit model counts unchanged. A red check — moving the identifier range check in `ingestion/staff_views.py::receipt_detail` ahead of the permission check — failed two assertions before being reverted. No production code changed. See ADR 0205.

**Limits:** The 405-before-authorization answer is recorded, not removed: it discloses accepted methods to any authenticated account but not row existence. Group B parity comes from Django's URL dispatcher and says nothing about the views. Thirteen identifiers are a sample; percent-encoded traversal beyond `1%2f..`, very long identifiers, NUL bytes and normalization-only differences are not probed. Dual-method routes are POSTed an empty body. Timing is not compared. ADR 0191 remains a release blocker.

## 2026-11-26 — require identical staff denials for existing and missing rows

**Changes:** `build_object_rows` was extracted from `daroobank/test_staff_authorization_objects.py` so the new `daroobank/test_staff_denial_parity.py` compares the same real rows. For all 23 object routes and every unauthorized account shape it requires the response for an existing row to be identical to the response for a missing primary key in status, body bytes and all headers except `Date` and `Set-Cookie`; requires the denial to be identical across a non-staff account, a permissionless staff account and a staff account holding other permissions, with at least two denied shapes asserted per route; requires a fully permitted account not to be denied for the same rows (200 on GET, 400 on a POST-only review route with an empty form); re-asserts `no-store`, `noindex, nofollow` and `same-origin` on every denial; and leaves fourteen write and audit model counts unchanged after probing every route twice with four shapes. A red check — reordering `ingestion/staff_views.py::receipt_detail` so an account with no visible kinds got 404 for a missing receipt and 403 for an existing one — failed two assertions before being reverted. No production code changed. See ADR 0204.

**Limits:** Timing is deliberately not compared; wall-clock differences in a test process measure the harness, so no timing-channel claim is made. One missing primary key and one existing row per route, so malformed, negative, oversized or non-numeric identifiers are not compared. The 18 staff routes without a primary key have no existing/missing pair and stay in ADR 0200. Headers are compared as the test client renders them, so anything a reverse proxy adds or reorders is outside scope. Byte-for-byte body comparison will also fail on unrelated denial-page template churn, which is intended. ADR 0191 remains a release blocker.

## 2026-11-26 — measure staff authorization for group, superuser and alternate-backend grants

**Changes:** `daroobank/test_staff_grant_paths.py` repeats the 41-route staff matrix for five further account shapes and records what actually happens: a group holding all permissions reaches the same 41 routes as an identical direct grant, a view-only group reaches the same 25, an active superuser with no explicit grant reaches all 41, a superuser without `is_staff` gets 403 on all 41, and a deactivated group member is never served content. With `AllowAllUsersModelBackend` a deactivated account authenticates and gets a real session, yet all 41 routes still return 403 with a body byte-identical to the default backend's denial of an active non-staff account. A further test primes an in-memory actor's permission cache, revokes the group grant through a second object and shows the stale object still reporting the permission while `recheck_actor` denies it, with and without a matching session hash, and accepts again once the grant is restored. Denials across all shapes carry `no-store` and `noindex, nofollow`. A red check — dropping `is_staff` from the full-group account — produced 42 failures before being reverted. No production code changed. See ADR 0203.

**Limits:** The superuser result is recorded as a finding, not an endorsement; separation of author and reviewer is a service-level guarantee not re-measured here. Only `AllowAllUsersModelBackend` was exercised and no custom backend was written, so denial for a deactivated account still depends on each destination checking `is_active`. Nested groups, object-level permissions and grants through custom managers are out of scope, routes are probed with missing primary keys, and ADR 0191 remains a release blocker.

## 2026-11-26 — inventory every public route and check it for private-data leakage

**Changes:** `daroobank/test_public_route_privacy_matrix.py` enumerates all non-staff routes from the live URL resolver and fails if the declared list drifts, then creates one marked private row per service — source claim, product candidate, price candidate, clinical draft, ingredient draft, import receipt — plus one published presentation carrying its own marker. Every route is probed with an anonymous client and a fully permitted staff client: statuses must match the declaration for both, none of the ten private markers may appear in any public body, the five known public read routes must keep `no-store`/`noindex, follow`/`no-referrer`, and the health probes are covered in both settings states. Two positive controls keep the absence assertions honest: one proves every marker really is stored in a private model and that only the marker presentation is published, the other proves searching for the published marker renders its URL and ID while searching for private rows returns the empty state and `[]`. A red check (publishing a private marker as the presentation source name) failed four assertions before being reverted. No production code changed. See ADR 0202.

**Limits:** Literal text matching only; derived, split, re-encoded, header-borne or unmarked private data is invisible to it. One row per marker and one published presentation, so bulk content, pagination, cursors, projection repair output and malformed-request error pages are not enumerated. Query-echo probes are excluded from marker absence and asserted on their result set instead. The inventory is name-based. ADR 0191 remains a release blocker.

## 2026-11-26 — repeat the staff authorization matrix against existing rows

**Changes:** `daroobank/test_staff_authorization_objects.py` builds one real synthetic row per object route — a source claim, product candidate, price candidate, import receipt, clinical draft, identity chain and a published presentation — and reuses the ADR 0200 route table for the 23 routes whose argument identifies a stored row. Unauthorized accounts must get the same 403 they get for a missing row, authorized accounts must get exactly 200 on a GET and exactly 400 on a POST-only review route with an empty form, both with staff privacy headers, anonymous requests must redirect to login, and probing every route with all five account shapes must leave fourteen write and audit model counts unchanged. No production code changed. See ADR 0201.

**Limits:** Existence-oracle coverage is status-code only: bodies, headers and timing are not compared. One row per route through the normal services, so ownership, per-object scoping beyond the receipt kind filter, inconsistent or oversized rows and multi-database routing are not exercised. The 400s come from deliberately empty forms, not successful reviews. ADR 0191 remains a release blocker.

## 2026-11-26 — add an endpoint-by-endpoint staff authorization matrix

**Changes:** `daroobank/test_staff_authorization_matrix.py` declares one row for each of the 41 staff routes (all `staff_*` names except login and logout) with its URL arguments, the method that reaches its authorization check and its requirement — staff only, all of a permission set, or any of a permission set. Expectations are derived from that declaration for six account shapes: anonymous (302 to login), active non-staff (403), staff without the requirement (403), staff with it (never 403, and a 302 must not go to login), and a deactivated full-permission account (302 or 403, never content). Denials must still carry staff privacy headers, exact shape counts are pinned, and a coverage assertion enumerates the live URL resolver so a new route cannot appear undeclared. No production code changed. See ADR 0200.

**Limits:** The matrix records and enforces current behavior; it does not judge whether each requirement is the right one, and the expectations are declared by the same authors as the code. Direct permission grants only — groups, superuser shortcuts, alternate backends and cross-request caching are out of scope. Authorized requests are asserted only to be not-403 with a missing primary key, so object-existence, ownership and row-level scoping differences are not covered. The deactivated-account denial is a login redirect, not durable revocation; ADR 0191 remains a release blocker.

## 2026-11-26 — cover every staff write route with an in-flight guard test

**Changes:** `daroobank/test_staff_inflight_revision_writes.py` adds synchronized HTTP tests for the three remaining revision routes (clinical revise, identity package revise, identity component correction), parking each CSRF-valid POST at the service-level `require_staff` the views import by name and asserting 403 with unchanged row counts after disable, password invalidation and reactivation, a login redirect for the next request, a still-commits flag-only case and a CSRF negative control. `daroobank/test_staff_write_route_inventory.py` enumerates all 43 `staff_*` route names and requires each to be mapped to a covering test module — which must name the route and park a password invalidation — or explicitly classified as read-only, download or auth. No production code changed. See ADR 0199.

**Limits:** The inventory is name-based: it does not prove a route's write is guarded or that reads are safe, and its park point is a test seam that depends on views importing `require_staff` by name. The guards themselves are unchanged partial mitigations; every flag-only case still asserts the write commits. ADR 0191 remains a release blocker.

## 2026-11-26 — extend the actor recheck to the identity workspace writes

**Changes:** All seven identity write services (`create_ingredient`, `create_formulation`, `create_product`, `create_package`, `revise_package`, `revise_identity`, `review_package`) accept an optional `session_auth_hash` and call the shared `recheck_actor` with their own permission pair before any row is written — inside the guarded transaction and before the first row lock, or before the single create call for the transaction-less ingredient path. The four identity staff write views pass the request session's password hash. `catalog/test_identity_actor_recheck.py` and `daroobank/test_staff_inflight_identity_writes.py` cover matching/omitted/stale hashes, password rotation, disabled/destaffed/deleted writers, permissions removed through a second instance, parked races and the CSRF negative control. See ADR 0198.

**Limits:** The rechecks are unlocked point-in-time reads, so a parked package revision still commits after disable, password invalidation and reactivation, and a flag-only disable/reactivate still permits parked HTTP writes. Sixteen services across fourteen staff routes are covered; inspection, lineage and read services, the projection repair command, permission serialization and durable session revocation remain open. ADR 0191 remains a release blocker.

## 2026-11-26 — extend the actor recheck to the clinical write paths

**Changes:** `clinical.services.create_draft` and `clinical.evidence.add_reference` accept an optional `session_auth_hash` and call the shared `recheck_actor` as the first statement inside their writer transactions, before the draft lock, so no row is written against a stale actor. The clinical create, revise and reference-create views pass the request session's password hash. `clinical/test_write_actor_recheck.py` and `daroobank/test_staff_inflight_clinical_writes.py` cover matching/omitted/stale hashes, password rotation, disabled/destaffed/deleted writers, a permission removed through a second instance, parked races and the CSRF negative control. See ADR 0197.

**Limits:** The rechecks are unlocked point-in-time reads, so parked-writer tests still create a draft and a reference after disable, password invalidation and reactivation; a flag-only disable/reactivate still permits a parked HTTP create. Nine services across ten staff routes are covered, identity/revision services and reads are untouched, permission changes remain unserialized and durable session revocation is still absent. ADR 0191 remains a release blocker.

## 2026-11-26 — extend the actor recheck to staging and correct stale-cache evidence

**Changes:** `catalog.intake.stage_products` and `pricing.importer.stage_csv` recheck their stager through the shared helper in commit mode, after the source-stage lock and before any row is written; the receipt wrappers forward the hash and both upload views supply it from the session. Permission-removal tests across the ADR 0192–0196 suites now remove permissions, group membership or group permissions through a second user instance, because Django clears an instance's own permission cache and the earlier tests could pass without exercising the recheck. A near-miss session hash in `daroobank/test_actor_recheck.py` is now derived by flipping one character; a fixed digit made that case fail in one optimized-mode run when it coincided with the real hash. See ADR 0196.

**Limits:** The staging rechecks are unlocked point-in-time reads, so parked-writer tests still stage rows and receipts after disable, password invalidation and reactivation; preview mode and actor-less price staging are not rechecked. Seven services on seven staff routes are covered, permission changes remain unserialized and durable session revocation is still absent. ADR 0191 remains a release blocker.

## 2026-11-26 — extend the shared actor recheck to catalog product review

**Changes:** `catalog.intake.review_product` now rechecks its reviewer through the shared helper after locking the candidate row, and the staff product review view passes the request session's password hash. `catalog/test_review_actor_recheck.py` and two HTTP cases in `daroobank/test_staff_inflight_review_writes.py` cover stale/disabled/destaffed/deleted reviewers, removed permissions behind a primed cache, stale and malformed hashes, password rotation, a parked race and the CSRF negative control.

**Limits:** The reviewer read is unlocked to preserve one lock order, so a credential change committed after it still races and a flag-only disable/reactivate still lets a parked review commit. Five services on five routes are covered; staging paths, other writes, permission serialization and durable session revocation remain open. ADR 0191 remains a release blocker.

## 2026-11-26 — cover the price and clinical review guards over HTTP

**Changes:** `daroobank/test_staff_inflight_review_writes.py` parks CSRF-valid price and clinical review POSTs inside service input validation. Disable plus password invalidation plus reactivation before the guard now provably yields 403 with no review and a login redirect for the next request from that session; a flag-only disable/reactivate still commits, and a missing CSRF token is rejected.

**Limits:** Two routes and selected orderings. These tests assert the views pass the session hash; they do not make revocation durable or race-free, and ADR 0191 remains a release blocker.

## 2026-11-26 — share one write-actor recheck across four guarded services

**Changes:** A new `daroobank/actor_recheck.py` helper reloads a write actor, repeats its active/staff/permission checks on the fresh instance and optionally binds the write to the session password hash, with an opt-in account-row lock. Source-claim creation and review now use it, and `pricing.reviews.record_preliminary_review` and `clinical.services.review_draft` gain the unlocked recheck plus session-hash binding, supplied by their staff views. See ADR 0195.

**Limits:** Only `record_claim` locks the account row; the other three rechecks are unlocked point-in-time reads, so selected parked-writer tests still commit a review after disable, password invalidation and reactivation. Four services on four routes are covered, the hash reflects the password only, permission changes are still not serialized, and durable session revocation remains absent. ADR 0191 remains a release blocker.

## 2026-11-26 — recheck the source reviewer and bind review to the session hash

**Changes:** `review_claim` accepts an optional `session_auth_hash`, which the staff review view supplies from the request session. After locking the claim row and before creating a review, the service rejects an invalid actor key, reloads the reviewer without a row lock, repeats the active/staff/permission checks on that fresh instance and compares the supplied hash in constant time, denying with 403. Synchronized synthetic tests now show disable plus password invalidation plus reactivation before the guard are denied. See ADR 0194.

**Limits:** The reviewer read is unlocked to preserve the single account-then-claim lock order, so a credential change after that read still races; a parked review commits in a selected test, as does a flag-only disable/reactivate. One service and route are covered, the hash reflects the password only, and durable session revocation remains absent. ADR 0191 remains a release blocker.

## 2026-11-26 — bind the source-claim write to the session password hash

**Changes:** `record_claim` accepts an optional `session_auth_hash`; the development staff create view passes the request session's authentication hash, and the guarded transaction compares it in constant time with the freshly locked account's current hash, denying a mismatch or non-string value with 403. A synchronized synthetic test now shows disable, password invalidation and reactivation committing before the guard are denied. See ADR 0193.

**Limits:** One service and one route are covered; review and other writes are untouched. The hash reflects the password only, so a flag-only disable/reactivate still lets the parked write commit, permission/group changes still race, and there is no durable session revocation. ADR 0191 remains a release blocker.

## 2026-11-26 — document reactivation race around the source-claim guard

**Finding:** A synchronized synthetic HTTP test shows that when account disable, password invalidation and reactivation all commit before the guarded source-claim write, the in-flight already-authorized old session still creates the claim; its next request is denied and the CSRF negative control stays intact.

**Limits:** One route and one ordering are covered. The guard checks current account state, not the requesting session's authentication hash, so there is still no race-free revocation; ADR 0191 remains a release blocker.

## 2026-11-26 — recheck source-claim permissions on a fresh actor

**Changes:** The selected source-claim transaction rechecks required permissions on its freshly loaded actor, rather than relying only on a possibly cached request actor.

**Limits:** Permission or group removal after the recheck can still race and allow the write. This is not durable permission revocation; see ADR 0192.

## 2026-11-26 — serialize source-claim account status with selected writes

**Changes:** The PostgreSQL source-claim recording transaction locks and checks its actor's current active/staff flags before creating or replaying a claim. Synthetic tests cover both account-update orderings and key-share compatibility.

**Limits:** This orders only one service and cannot cancel an earlier writer; session reactivation, cached permissions, other writes, lock waits and broader account lifecycle remain open. See ADR 0192.

## 2026-11-26 — document selected in-flight staff write race

**Finding:** A CSRF-valid synthetic source-claim POST already past its authorization checks can commit after account disable and password invalidation; a new request while disabled does not create another claim.

**Limits:** One route and one ordering are tested. No race-free revocation control or production procedure is implemented; ADR 0191 remains a release blocker.

## 2026-11-26 — document in-flight staff read boundary

**Finding:** A synchronized synthetic workspace request can finish successfully after the account is disabled and its password invalidated; two selected old sessions fail on later requests after the password change, while another account remains unaffected.

**Limits:** These are selected observations, not a revocation implementation, an in-flight write test, or a production procedure. The production blocker in ADR 0191 remains open.

## 2026-11-26 — document unresolved staff-session revocation gap

**Finding:** Synthetic tests show that reactivating an account or restoring its staff flag can make an existing unexpired session usable again. A selected password-change test invalidates an old session on a later request but is not a complete incident or revocation procedure.

**Status:** Durable session revocation remains a production blocker; see ADR 0191.

## 2026-11-26 — revoked-staff boundary regression

**Changes:** A synthetic existing-session test exercises named staff routes after the staff flag is revoked, including an account that retains superuser permissions.

**Limits:** This does not establish concurrent revocation, production security or complete authorization coverage; see Testing strategy.

## 2026-11-26 — optional stdin for synthetic projection repair token

**Changes:** The one-row repair command accepts a bounded token via non-terminal stdin as an alternative to the legacy argument. Invalid combinations and non-debug use fail before reading.

**Limits:** Preview output, token files, other processes, pipes and logs still need protection; this is not authorization or a production tool. See ADR 0190.

## 2026-11-26 — privacy headers on selected early errors

**Changes:** The existing outer known-path middleware now applies staff/public privacy headers to selected early errors as well as redirects, including invalid-host 400 responses.

**Limits:** Unknown routes, infrastructure responses and logs are not covered; see ADR 0189.

## 2026-11-26 — frame protection on early non-debug responses

**Changes:** Non-debug frame middleware now wraps the HTTPS redirect and disabled-staff gate; fresh-process tests cover early and ordinary responses and Django's explicit exemptions.

**Limits:** Debug previews remain embeddable, view exemptions remain effective, and upstream/static responses are outside this Django header policy; see ADR 0188.

## 2026-11-26 — suppress selected catalog command traceback chains

**Changes:** Catalog IRC inspection and synthetic projection repair no longer chain selected cursor/token errors into their command tracebacks. Synthetic canaries test both commands, including one real CLI invocation.

**Limits:** Command-line arguments may remain visible to the operating system and shell; service exceptions, other errors and logs are not sanitized by this change.

## 2026-11-26 — bound selected login-window maintenance waits

**Changes:** Synthetic cleanup now refuses outer/non-autocommit transactions and runs with PostgreSQL-local lock and statement timeouts. Timeout and connection-reuse tests exercise selected failures and the refreshed-row race remains covered.

**Limits:** These are server-side statement/lock limits, not full request/network deadlines or a scheduler; see ADR 0187.

## 2026-11-26 — disabled staff boundary regression tests

**Changes:** Tests enumerate currently named staff routes, verify the shared gated path, and exercise private 404 responses for GET, HEAD and POST before session loading when the portal is disabled.

**Limits:** These are Django-level tests, not production access controls, a review of future unnamed routes or proof of network isolation.

## 2026-11-26 — PostgreSQL connection lifetime bound

**Changes:** `POSTGRES_CONN_MAX_AGE` now fails startup outside 0–31,536,000 seconds. Extremely large integers previously passed configuration and could overflow Django's connection deadline.

**Limits:** The upper bound changes compatibility and is not a recommendation for long-lived connections or a network deadline. Real pooling and timeout policies need separate review.

## 2026-11-26 — selected maintenance traceback redaction

**Changes:** Generic database failures in synthetic login-window cleanup and the PostgreSQL schema/access inspectors no longer chain driver errors into formatted tracebacks. The offline schedule command likewise suppresses chained parser errors, which may contain input. Synthetic canary tests include `--traceback` CLI runs.

**Limits:** This does not scrub database/server logs, other commands, direct exception introspection or unexpected exception types; operators must still control diagnostic access and logging.

## 2026-11-26 — development staff-login password bound

**Changes:** The staff form rejects passwords over 4,096 characters before calling the backend, with the generic invalid-login error. CSRF-valid attempts still count toward the opt-in synthetic throttle.

**Limits:** This is a compatibility change for longer existing passwords, not a request-body limit, MFA or a production abuse control; see ADR 0186.

## 2026-11-26 — database configuration error redaction

**Changes:** Invalid PostgreSQL port or connection lifetime still fails startup, but no longer chains Python's conversion exception, which may contain the configured value. Fresh-process tests exercise synthetic canaries.

**Limits:** This covers these two integer settings only, not all startup, process, infrastructure or database logs; secrets must still be managed and logs reviewed separately.

## 2026-11-26 — optional non-debug HSTS duration

**Changes:** A bounded explicit HSTS max-age can be configured outside debug; the default remains off and subdomain/preload directives stay disabled.

**Limits:** HSTS persists in browsers, and resetting this option to zero does not clear an earlier policy. TLS, ownership and recovery require independent review; see ADR 0185.

## 2026-11-26 — opt-in trusted proxy scheme

**Changes:** A default-off non-debug option accepts a single forwarded scheme only from configured immediate peer networks, and rejects universal or malformed network lists.

**Limits:** This does not authenticate a proxy or firewall the app; a proxy must overwrite client-supplied headers and preserve the approved host. No TLS infrastructure or production authorization follows. See ADR 0184.

## 2026-11-26 — fail closed on selected non-debug configuration

**Changes:** Outside debug, startup requires a secret of an accepted minimum shape and explicitly configured, syntactically valid non-wildcard hosts. Debug preview defaults are unchanged.

**Limits:** This is a compatibility change, not proof of key randomness, host ownership, TLS, production security or authorization. See ADR 0183.

## 2026-11-25 — reject repeated staff-login credentials

**Changes:** The development staff login form rejects repeated enabled username/password values before invoking an authentication backend, preserving the generic error and existing sessions.

**Limits:** Other parameters and authentication routes remain outside this check; see ADR 0182.

## 2026-11-25 — opt-in synthetic staff-login throttle

**Changes:** An optional development-only shared PostgreSQL fixed-window throttle limits CSRF-accepted staff-login POSTs by pseudonymized server client address. A dry-run-first, bounded synthetic maintenance command removes older windows when explicitly requested.

**Limits:** Default off, disabled outside debug; not MFA, distributed-attack protection or a production access policy. Proxy configuration, unbounded row growth, manual cleanup and security review remain important; see ADR 0181.

## 2026-11-25 — opt-in process and PostgreSQL probes

**Changes:** Added default-off, minimal HTTP process liveness and database-connectivity probes; database errors return a generic unavailable response and selected responses are not cached.

**Limits:** The unauthenticated paths require separate network restriction. A successful probe does not verify migrations, backups, workers, data or production readiness; the SQL timeout is not an end-to-end deadline. See ADR 0180.

## 2026-11-25 — respect disabled form fields

**Changes:** Shared selected raw-input checks ignore request values for server-disabled fields, consistent with Django's initial-value semantics. Enabled fields retain duplicate and control rejection.

**Limits:** No current workflow was made disabled; other fields and direct service calls remain outside scope. See ADR 0179.

## 2026-11-25 — clinical child preview author status

**Changes:** The capped clinical child preview distinguishes a missing current author account from invalid or oversized child data using one batched existence check.

**Limits:** This is not historical identity or clinical verification and can change immediately. See ADR 0178.

## 2026-11-25 — preserve implicit partial presentation saves

**Changes:** Deferred same-database presentation saves preserve the originally loaded/assigned field set before projection generation and use the existing locked prospective-row path. A selected concurrent synthetic update no longer gets overwritten by an unloaded stale field.

**Limits:** Loaded stale fields, full saves, bulk/direct SQL and other interleavings remain outside this guarantee. See ADR 0177.

## 2026-11-25 — reject selected duplicate staff inputs

**Changes:** Selected single-value staff fields, choices and upload files reject duplicate submissions; an otherwise-empty component row with a duplicate value is no longer silently skipped.

**Limits:** This is not a general defense for every input, proxy, login or direct service. See ADR 0176.

## 2026-11-25 — formulation formset management validation

**Changes:** Selected create and correction formsets reject raw control characters or duplicate values in their total/initial management fields before attempting a write.

**Limits:** Hidden fields are still client-controlled; this does not establish authorization or identity. See ADR 0175.

## 2026-11-25 — clinical lock-test coordination

**Changes:** The synthetic oversized clinical writer test signals immediately before its target-row lock rather than before preliminary reads, while retaining the real PostgreSQL blocker and rollback assertions.

**Limits:** One earlier concurrent full-run failure has no confirmed root cause; timing-sensitive tests cannot establish complete concurrency safety. See ADR 0174.

## 2026-11-25 — checkbox state after form errors

**Changes:** Selected checkboxes now render their validated boolean state after form errors; false or malformed raw values no longer appear checked or echo as the input value.

**Limits:** This does not establish consent or cover all form widgets. See ADR 0173.

## 2026-11-24 — defensive bounded JSON decoding

**Changes:** Selected bounded candidate and review reads decode text defensively, so unusually deep or very large numeric JSONB values do not crash these reads before validation. Incompatible values are suppressed and comparison remains unknown.

**Limits:** The JSON can still be valid PostgreSQL data; this inspection outcome is not an authenticity or clinical finding and does not cover every read. See ADR 0172.

## 2026-11-24 — explicit staff checkbox values

**Changes:** Selected acknowledgements, source scopes and upload-rights checkboxes reject unknown or duplicate values; explicit `0` is false. Normal browser submissions remain supported.

**Limits:** A submitted checkbox does not establish consent, rights, authorization or safety; clients using other strings must update. See ADR 0171.

## 2026-11-24 — bounded price-list CLI payloads

**Changes:** The local price-list command limits selected candidate JSON transfer and emits an explicit oversized/unknown row without matching or printing its payload.

**Limits:** Consumers must handle this new shape; the bound does not cover database work or make output confidential. See ADR 0170.

## 2026-11-24 — reject raw controls in selected staff dates

**Changes:** Source and clinical date forms reject control characters in the original date value instead of silently stripping them or treating them as empty.

**Limits:** This covers selected forms, not all inputs or direct service callers. See ADR 0169.

## 2026-11-24 — reject raw controls in identity numeric inputs

**Changes:** Selected identity IDs and quantities now report field errors instead of silently stripping control characters from raw form submissions.

**Limits:** This is a form-level check, not comprehensive validation of every input or direct service call. See ADR 0168.

## 2026-11-24 — omit discarded projection from partial save

**Changes:** The locked read used for partial presentation saves no longer transfers the old search projection before rebuilding it from the current prospective row.

**Limits:** Other reads, full or bulk writes and database work remain outside this bound. See ADR 0167.

## 2026-11-24 — omit unused matching projections

**Changes:** Product comparison and price matching no longer transfer the unused stored search text, including on their lookahead and selected locked reads.

**Limits:** A later access to a deferred field can still fetch it; database work, other fields and other paths are not bounded. See ADR 0166.

## 2026-11-24 — canonical new clinical revision reasons

**Changes:** The direct clinical revision service validates the original reason, then strips outer whitespace before storing and hashing new revisions; internal whitespace is retained. Existing reasons and fingerprints are not rewritten.

**Limits:** Valid oversized historical reasons remain uninspected and can block selected writers. Input size, other fields and database work are not bounded by this change. See ADR 0165.

## 2026-11-24 — bounded locked clinical draft text

**Changes:** Revision, reference and review writers bound target and immediate-parent text under their existing row locks and conflict on uninspected values.

**Limits:** Even a valid long whitespace-bearing reason may conflict; inputs, database work and other paths are not bounded by this change. See ADR 0164.

## 2026-11-24 — bounded clinical detail and lineage

**Changes:** Selected draft, immediate-parent and child text in private clinical detail and lineage reads is bounded; excessive values remain uninspected and disable unsafe affordances.

**Limits:** This is not a snapshot or clinical validation; locked writer reads and other paths remain outside this bound. See ADR 0163.

## 2026-11-24 — bounded clinical scan text

**Changes:** Clinical queue and technical scan bound selected draft and parent text, reporting oversized values as uninspected rather than necessarily inconsistent.

**Limits:** Direct detail reads, database work and other paths remain outside this bound. See ADR 0162.

## 2026-11-24 — bounded locked source evidence notes

**Changes:** Source replay and review writers avoid transferring oversized evidence notes and reject them under their existing row locks.

**Limits:** Database work and other fields remain outside the bound. See ADR 0161.

## 2026-11-24 — bounded source evidence-note reads

**Changes:** Selected source claim displays and inspections bound evidence-note transfers and hide over-limit content, which is provably invalid under the existing field limit.

**Limits:** Other fields, writers and database work remain outside this bound. See ADR 0160.

## 2026-11-24 — bounded staging replay JSON

**Changes:** Product and price staging pre-lookups select only existing IDs and duplicate rereads bound candidate JSON under the existing lock; oversized replay conflicts roll back.

**Limits:** This is not a database-work bound or authenticity check. See ADR 0159.

## 2026-11-24 — bounded current candidate review

**Changes:** Product and price details and preliminary-review writer lock reads bound selected current-candidate JSON; oversized candidates are uninspected and review creation fails closed.

**Limits:** Other fields, database work, other writers and endpoints remain outside the bound. See ADR 0158.

## 2026-11-24 — bounded candidate queues

**Changes:** Staff product and price queues bound selected candidate JSON transfers and mark oversized content uninspected without changing pagination or counts.

**Limits:** Direct detail requests and database work are outside this bound. See ADR 0157.

## 2026-11-24 — bounded related candidate comparisons

**Changes:** Selected product and price comparison queries avoid transferring oversized related candidate JSON; uninspected comparisons do not yield details or price arithmetic.

**Limits:** Current candidate, database work, other fields and endpoints remain outside this bound. See ADR 0156.

## 2026-11-24 — bounded receipt candidate JSON

**Changes:** Private receipt detail and manifest inspection avoid transferring oversized candidate JSON, report it as uninspected and preserve pagination.

**Limits:** This does not bound database work or other fields and endpoints. See ADR 0155.

## 2026-11-24 — bounded identity revision-link reasons

**Changes:** Identity detail and lineage reads bound selected revision-link reason transfers while keeping existing validation and pagination.

**Limits:** Database work, other graph fields and write paths are not bounded. See ADR 0154.

## 2026-11-24 — bounded locked identity review

**Changes:** Identity review and revision writers bound selected fields in the same locked latest-review read; revision refuses an uninspected oversized latest review without partial classification.

**Limits:** Database work and other graph reads remain unbounded; review creation retains its prior latest-ID-only policy. See ADR 0153.

## 2026-11-24 — bounded identity review display

**Changes:** Private identity-package history and revision pages bound selected review graph and reason transfers. Oversized reviews are explicitly uninspected and preserve ordering and latest-review IDs.

**Limits:** Database work, current graphs and other pages are not bounded; the later ADR 0153 bounds selected latest-review fields in the identity writer lock read. See ADR 0152.

## 2026-11-24 — hidden review-token recovery

**Changes:** Five staff review forms offer an explicit same-origin GET restart for invalid hidden tokens, with a warning that unsaved inputs are discarded.

**Limits:** Reopening does not bypass validation, preserve inputs or guarantee a subsequent submission. See ADR 0151.

## 2026-11-24 — bounded review-scan parent fields

**Changes:** Selected current source and clinical TextFields are bounded during review scans; invalid product/price scan requests check candidate existence without loading candidate JSON.

**Limits:** Other pages and database work remain unbounded. See ADR 0150.

## 2026-11-24 — bounded source and clinical review-scan content

**Changes:** Private source and clinical review scans bound selected snapshot and reason transfers, mark oversized rows as uninspected and retain scoped batch continuation.

**Limits:** Database work and other data, including parent records, remain unbounded. See ADR 0149.

## 2026-11-24 — bounded recent-review content

**Changes:** Four private detail pages bound selected review snapshot and reason transfers, suppress oversized content and retain the newest review's concurrency token.

**Limits:** Database processing, other fields and pages remain unbounded; source and clinical review scans did not inherit this display protection at this step (see the subsequent ADR 0149). See ADR 0148.

## 2026-11-24 — bounded candidate-review scan content

**Changes:** Private product and price review scans bound selected candidate JSON, review snapshot and reason transfers; oversized reviews are explicitly uninspected and filterable.

**Limits:** The database may still read and process large values, and other pages are outside this boundary. This is neither authenticity nor a complete memory/work limit. See ADR 0147.

## 2026-11-24 — selected raw concurrency-token controls

**Changes:** Selected private review, revision and reference forms reject raw control characters and surrogates in hidden concurrency fields before field cleanup can hide them. Synthetic HTTP tests check invalid requests do not write and selected clean retries succeed.

**Limits:** This is not token authentication or a stronger locking guarantee; other writers, logging and possible redisplay of bound values remain outside scope. See ADR 0146.

## 2026-11-24 — offline window form boundaries

**Changes:** The offline schedule form independently validates its three inputs, rejects raw boundary controls and provides an error title and linked summary.

**Limits:** This is only a calculation, not dispatch or source authorization; selected browser checks do not establish comprehensive accessibility. See ADR 0145.

## 2026-11-24 — identity revision error navigation

**Changes:** Selected identity revision forms show an error title and summary with links to visible fields and component errors; unavailable forms do not receive dangling links.

**Limits:** Conflicts still require reloading, and automated/keyboard checks are not comprehensive accessibility validation. See ADR 0144.

## More review error summaries

**Changes:** Selected source, clinical and identity review responses now have an error-specific title and summary; unavailable forms use a fixed notice instead of broken links.

**Limits:** Selected tests are not comprehensive accessibility validation; identity conflicts still require reloading. See ADR 0143.

## Selected raw multiline controls

**Changes:** Selected staff review reasons, clinical statements and revision reasons reject forbidden raw controls before form whitespace cleanup can hide them; permitted multiline whitespace remains supported.

**Limits:** This is not a comprehensive Unicode or log-safety guarantee, and bound forms may redisplay submitted values. See ADR 0142.

## Candidate-review inspection

**Changes:** Private product and price candidate pages offer bounded, read-only review-history inspection with post-batch filtering and explicit continuation.

**Limits:** This is not an audit or authentication; reads are separate and scans are not snapshots. See ADR 0141.

## Product-review snapshot clues

**Changes:** The product candidate detail checks selected recent review snapshots, suppresses inconsistent review details, and compares consistent snapshots with the current candidate.

**Limits:** Unkeyed checks are not authentication or audit; coherent rewrites can pass, reads are not snapshots and other outputs remain outside this display. See ADR 0140.

## 2026-11-24 — candidate review error summaries

**Changes:** Product and price review errors receive a descriptive page title and server-rendered summary; when the form is unavailable, a fixed notice replaces links to absent fields.

**Limits:** Selected synthetic keyboard and automated checks are not comprehensive accessibility validation. See ADR 0139.

## 2026-11-24 — synthetic source deadlock probe

**Changes:** The actual PostgreSQL source-review deadlock probe checks both worker results and permits either real `40P01` victim, with the appropriate rollback or success outcome.

**Limits:** Only a service-victim run exercises translation of a real deadlock through the writer; injected tests cover mappings separately. See ADR 0138.

## 2026-11-24 — price-review snapshot clues

**Changes:** The selected price detail history checks recent stored review snapshots, suppresses details of inconsistent records, and compares consistent snapshots with the current candidate.

**Limits:** This is not authentication, audit or price approval; coherent rewrites can pass, reads are not snapshots and other outputs remain outside this display. See ADR 0137.

## 2026-11-24 — synthetic CSV sample downloads

**Changes:** The two staff upload pages link to their fixed repository-provided synthetic CSV examples, with the same permissions as upload and private download headers.

**Limits:** The files contain invented figures and are public repository examples, not verified source data; arbitrary spreadsheets and real-source permissions are not validated by this convenience. See ADR 0136.

## 2026-11-24 — selected staff form error summaries

**Changes:** Selected source, clinical, identity-create and upload forms show a linked error summary and an error-prefixed title after failed validation, including component-formset errors.

**Limits:** No automatic focus or general assistive-technology guarantee; other forms and manual accessibility review remain outstanding. See ADR 0135.

## 2026-11-24 — empty staff POST feedback

**Changes:** Six selected create, revision, reference and upload views bind even an empty authorized POST so required-field errors are shown; GET stays unbound.

**Limits:** Other views and all client or assistive-technology combinations were not exhaustively checked. See ADR 0134.

## 2026-11-24 — raw controls on selected staff forms

**Changes:** Selected source, clinical and identity assertion forms reject controls and surrogates in raw single-line input even when Django would trim them away; ordinary outer spaces and clinical multiline statement behavior remain unchanged.

**Limits:** This is form-level hardening, not a general Unicode, service, database or secrecy guarantee; unchanged empty extra component rows are skipped. See ADR 0133.

## 2026-11-24 — synthetic identity deadlock test coordination

**Changes:** The selected identity deadlock probe now coordinates from the actual lock holder and uses longer bounded waits while still requiring SQLSTATE `40P01`.

**Limits:** A prior full-suite run failed with a lock timeout; the exact scheduling cause was not established, and this is not a proof of determinism. See ADR 0132.

## 2026-11-24 — unknown source and clinical status labels

**Changes:** Selected source and clinical queues and related-source hints distinguish unknown non-null reviews from no review.

**Limits:** This does not validate history, prevent writes or establish source rights or clinical approval; nulls and other paths remain outside the check. See ADR 0131.

## 2026-11-24 — unknown candidate status labels

**Changes:** Selected product and price queues and review histories show a fixed invalid label instead of mapping an unknown status to a normal one.

**Limits:** This is defensive display for selected constraint-bypass cases, not history validation or repair; null latest decisions and other domains remain ambiguous. See ADR 0130.

## 2026-11-24 — candidate queue consistency display

**Changes:** Private product and price queues check each displayed candidate and replace inconsistent identity fields with a warning, retaining the ID, link and historical status.

**Limits:** This adds per-row validation but does not bound fetched JSON, verify authenticity or hide all metadata and history. See ADR 0129.

## 2026-11-24 — suppress inconsistent detail values

**Changes:** Private product and price detail pages replace selected identity and amount panels with a warning when candidate consistency checks fail; review gating remains independent.

**Limits:** Other pages, metadata, histories and logs can still contain untrusted values. Consistency is neither authenticity nor approval, and reads are not snapshots. See ADR 0128.

## 2026-11-24 — bounded catalog-quality projection fetch

**Changes:** The quality inspector selects a bounded search projection and flags oversized rows with unknown public-filter status instead of transferring the whole value.

**Limits:** This adds an issue code and suppresses other quality conclusions for such rows; database work and omitted-suffix controls remain unchecked. See ADR 0127.

## 2026-11-24 — bounded synthetic repair projection fetch

**Changes:** Synthetic projection-repair preview and locked commit select at most 8193 characters of the stored search projection; an oversized projection remains unsafe. Safe-length snapshots retain the complete text.

**Limits:** This bounds returned text, not database work or other readers, and does not authorize repair of real data. See ADR 0126.

## 2026-11-24 — public detail ID type

**Changes:** The direct public-detail service rejects non-integer and out-of-range IDs before database access, using the existing generic not-found response.

**Limits:** Direct callers passing coercible values must change; HTTP integer routes are unchanged. This is not authorization or source verification. See ADR 0125.

## 2026-11-24 — reject controls in retained search queries

**Changes:** Search rejects Unicode controls and surrogates in the retained query before cursor validation or database access, with a generic no-echo error.

**Limits:** This tightens existing behavior. Edge whitespace stripped by HTTP views and content beyond the prefix are not checked; logs and Unicode spoofing remain concerns. See ADR 0124.

## 2026-11-24 — defer internal projections on public reads

**Changes:** Search and detail reads avoid selecting two unused stored projection columns; the search still uses and rechecks its projection. Synthetic tests cover selected HTML, JSON and SQL paths.

**Limits:** The database still searches the text, and direct service callers accessing deferred fields make additional, potentially later-state queries. This is not a capacity guarantee; see ADR 0123.

## 2026-11-24 — publication/date database constraint

**Changes:** The catalog migration adds a check that a presentation marked published has a non-null verification date. Synthetic tests cover direct write rejection, legacy migration failure without rewrites and one DDL lock timeout.

**Limits:** Existing invalid rows make migration fail; no date or publication is automatically repaired. The date is not verification evidence or clinical approval; deployment and recovery require separate review. See ADR 0122.

## 2026-11-24 — baseline content-security policy

**Changes:** Django responses receive a same-origin CSP baseline; synthetic Chromium checks selected blocked inline/off-origin behaviors and existing workflows. It intentionally leaves preview framing to existing environment-specific controls.

**Limits:** Same-origin script remains allowed, views and upstream infrastructure can set different headers, no reports are collected, and this is not a security assessment or deployment approval. See ADR 0121.

## 2026-11-24 — synthetic search index experiment

**Changes:** Added an opt-in 100,000-record synthetic PostgreSQL experiment comparing existing search and temporary trigram and ordering indexes, with selected warm search queries, four-client probes for one query, result checks and rollback-only updates.

**Limits:** No index is added to application migrations. Selected timings do not establish representative concurrency, deployment safety or production performance. See ADR 0120.

## 2026-11-24 — explicit intake commit mode

**Changes:** Product and price intake services require an actual boolean for `commit`, before reading a file or writing. The synthetic projection-repair command also rejects non-boolean programmatic flags before any query. Synthetic tests cover selected non-boolean values, callbacks, preview and attested staging/repair.

**Limits:** This changes direct-call compatibility and does not replace source-rights verification or protect direct database writers. See ADR 0119.

## 2026-11-24 — raw controls at intake boundaries

**Changes:** Product and price CSV parsers reject control/surrogate characters before cell trimming; price source validation and the two upload forms check raw source fields before controls can be erased. Synthetic direct and authenticated upload tests cover selected no-write paths.

**Limits:** Ordinary spaces still trim, this intentionally rejects formerly accepted input, and other forms/writers and Unicode spoofing remain out of scope. See ADR 0118.

## 2026-11-24 — reject hidden characters in price amounts

**Changes:** Price amount conversion rejects selected Unicode controls, format characters, marks and line separators before normalization; CSV checks the raw cell before trimming. Synthetic direct, atomic CSV, legacy integrity and Unicode-category tests cover selected cases.

**Limits:** Some formerly accepted legacy candidates will require review; compatibility digits and ordinary outer spaces remain supported. This is not complete Unicode, source or financial validation. See ADR 0117.

## 2026-11-24 — synthetic encrypted restore probe

**Changes:** Added an opt-in OpenSSL CMS envelope, detached synthetic signature and isolated PostgreSQL restore exercise with selected tamper, wrong-key, replacement-archive and replay controls; CI opts in.

**Limits:** Ephemeral keys and intermediate archives are plaintext locally; encryption alone does not authenticate the backup creator, and the test signature lacks trusted key distribution and replay protection. No production backup, key-management or off-host policy is implemented; see ADR 0116.

## 2026-11-24 — synthetic public-read role probe

**Changes:** A disposable PostgreSQL test exercises anonymous presentation pages and APIs under selected restricted-role grants and verifies several denied operations.

**Limits:** Table-wide SELECT still exposes unpublished rows to direct SQL; the test is not an authenticated role, deployment configuration or complete privilege assessment. See ADR 0115.

## 2026-11-24 — isolated test teardown name guard

**Changes:** The isolated test backend records a successful CREATE on the creation instance and allows a single teardown attempt only for that exact name. A real synthetic canary and mocked failed-DROP tests cover selected refusal paths.

**Limits:** The record is not ownership or database identity, and replacement before DROP remains possible. Crashes and failures may leave databases behind; see ADR 0114.

## 2026-11-24 — historical migration failure and lock evidence

**Changes:** Four historical catalog migration tests register schema restoration before setup can fail; synthetic injected failures verify restoration is attempted before Django flush. Presentation projection migration tests also cover selected old rows, transactional failure and a two-connection lock conflict. One-off 5,000-row probes counted per-row updates for both projection backfills.

**Limits:** Cleanup can fail or be interrupted; these selected synthetic checks and timings do not establish safe production deployment, recovery or performance. See ADRs 0112 and 0113.

## 2026-11-24 — selected legacy-data migration tests

**Changes:** PostgreSQL migration tests verify selected old receipt summaries and clinical draft/review fixtures survive existing additive migrations without invented manifest or reference rows; selected new constraints reject invalid values.

**Limits:** This is synthetic sampled evidence, not a production migration or rollback plan. See ADR 0111.

## 2026-11-24 — PostgreSQL session-access clues

**Changes:** Added a development-only, one-statement aggregate inspection of selected current/session-role attributes, current-role table-level privileges, RLS flags and server-observed transport. Synthetic restricted-role and RLS-bypass tests cover selected limits.

**Limits:** It reports facts, not a security pass or production authorization; column grants, role escalation paths, policies and end-to-end transport remain outside scope. See ADR 0110.

## 2026-11-24 — isolated PostgreSQL test-database collision guard

**Changes:** The synthetic, browser and restore test settings use a PostgreSQL test-creation backend that fails on a colliding name without dropping or reusing the pre-existing database. Real synthetic canaries cover all three settings with and without `--noinput`.

**Limits:** Only initial test-database creation is guarded. Normal teardown, privileged writers, interruptions, shared cluster resources and default settings remain separate risks; use a disposable authorized cluster. See ADR 0109.

## 2026-11-24 — direct price-conversion bound

**Changes:** The direct amount helper enforces the existing 50-character input limit and uses exact digit-string arithmetic independent of decimal context; selected oversized and 3,000 synthetic compatibility-digit cases are tested.

**Limits:** The CSV parser already imposed its own limit; the direct-helper change is not evidence of a CSV exploit or a price-approval mechanism. See ADR 0108.

## 2026-11-24 — projection length boundary coverage

**Changes:** Added synthetic tests for normalization expanding a short IRC to the exact or over-limit 80-character derived column, including full/partial rejection and explicit correction of a bypassed row. Corrected the API privacy documentation to include known-path early redirects.

**Limits:** This tests existing model validation, not arbitrary bulk/SQL writes or every Unicode normalization case. Redirect headers do not redact queries or control upstream proxies.

## 2026-11-24 — partial presentation validation

**Changes:** Nonempty partial presentation saves validate the prospective combination of locked stored fields and explicitly updated values, closing stale-state publication/date mismatches; synthetic two-connection and unit tests cover selected cases.

**Limits:** Bulk and SQL writes bypass this validation, full saves can overwrite newer values, and signal instances can still carry stale omitted fields. See ADR 0107.

## 2026-11-24 — architecture decision index

**Changes:** Restored 22 missing decision links and sorted the index; an offline test now checks coverage, uniqueness and order.

**Limits:** The test checks index entries, not the correctness or currency of each decision.

## 2026-11-24 — selected check expression reuse

**Changes:** The one-statement inspector reuses a materialized set of selected named-check expressions for its exact constant counts; a mixed-constraint test checks aggregate outcomes.

**Limits:** Materialization costs vary; expression coverage and privacy boundaries are unchanged. See ADR 0106.

## 2026-11-24 — selected constant-false check clues

**Changes:** The inspector flags exact deparsed false expressions on selected named model checks; a synthetic test confirms an otherwise valid insert is rejected.

**Limits:** Equivalent always-false expressions can remain undetected, and intentionally false checks can be flagged; see ADR 0105.

## 2026-11-24 — selected constant check clues

**Changes:** The PostgreSQL inspector flags exact deparsed true/null expressions on selected named model checks; synthetic tests demonstrate rows that those checks allow.

**Limits:** Other tautologies and unexpected checks remain outside this narrow test; it is not full expression comparison or data validation. See ADR 0104.

## 2026-11-24 — selected auto-sequence settings

**Changes:** The single-statement PostgreSQL development inspector flags selected owned auto sequences with nonpositive increment, minimum below one or cycling enabled. Synthetic tests include a sequence that reissues a value and a rewound-value negative control.

**Limits:** Intentional settings may be flagged; current values, data alignment and future insert success are not proven. See ADR 0103.

## 2026-11-24 — synthetic backup argument guards

**Changes:** The synthetic backup guide rejects non-absolute archive paths and libpq connection-string-like source database names before invoking client commands; restore operands use an option terminator. Offline guards and a disposable PostgreSQL restore probe cover selected paths.

**Limits:** It cannot verify server identity, a trusted filesystem or inherited environment and intentionally accepts only simple ASCII database names; see ADR 0102.

## 2026-11-24 — PostgreSQL trigger session clues

**Changes:** The single-statement development schema inspector flags replica session mode and selected trigger enabled modes that do not fire in that session, in addition to disabled triggers. Synthetic tests demonstrate an origin-mode replica-only trigger and a replica-mode foreign-key bypass.

**Limits:** A trigger mode mismatch may be intentional and the result covers only the inspecting session and selected tables; no repair or production certification is implied. See ADR 0101.

## 2026-11-24 — manifest header consistency

**Changes:** Validate selected version-1 receipt header totals, domain limits and suggestion counts before aggregating manifest rows; invalid headers stop row inspection, while legacy receipts stay legacy.

**Limits:** Selected consistency only; the check is not a snapshot, provenance proof or schema repair. See ADR 0100.

## 2026-11-24 — manifest ordinal distinctness

**Changes:** Manifest structural checks now count distinct ordinals, detecting gaps masked by duplicate positions even if a uniqueness constraint is missing or bypassed. Product and price detail and inspection stop displaying structurally inconsistent rows.

**Limits:** This adds aggregate database work and is neither schema repair nor a snapshot or proof of provenance; see ADR 0099.

## 2026-11-24 — selected failed-restore relation counts

**Changes:** The synthetic restore drill compares selected target `public` relation-kind counts before and after a failed truncated restore; target-only canaries test detection and the equal-count replacement blind spot.

**Limits:** Equal counts do not establish schema equivalence, and objects outside the selected relation kinds are not covered. See ADR 0098.

## 2026-11-24 — price staging replay integrity

**Changes:** Committed price staging locks and checks duplicate candidates and derived price fields before recording them, with rollback on conflict. Actorless CLI candidates remain replayable and the original suggestion remains unchanged.

**Limits:** Per-duplicate checks add work and locks; a null recorder has no provenance proof and source rights or prices are not verified. See ADR 0097.

## 2026-11-24 — product staging replay integrity

**Changes:** Committed product staging locks and checks duplicate candidates before counting them or recording receipt items; unsafe replays roll back the stage and return a conflict. Synthetic PostgreSQL tests include integrity failures and concurrent row updates.

**Limits:** Locks and account checks add per-duplicate work; rights and authenticity are not verified, and price staging is unchanged. See ADR 0096.

## 2026-11-24 — source-claim replay integrity

**Changes:** Duplicate source-claim replays lock and re-read the existing row, checking its current payload, exact submitted fields and recorder existence; unsafe replay returns a private conflict. PostgreSQL concurrency tests cover timeout, outer lock lifetime and a mutation between lookup and locked read.

**Limits:** Recorder identity and rights are not proven, later writes remain possible, and outer-transaction failures are outside the local boundary. See ADR 0095.

## 2026-11-24 — PostgreSQL legacy serial-default clue

**Changes:** Selected legacy serial defaults are compared to a canonical `nextval` expression for their owned sequence, rejecting selected wrong defaults and a shadowed custom function.

**Limits:** Equivalent noncanonical expressions can be flagged; function safety and sequence state are not proven. See ADR 0094.

## 2026-11-24 — PostgreSQL auto-field generation clues

**Changes:** The read-only inspector checks selected model and recorder auto fields for an owned sequence and supported identity or legacy-default clues; synthetic DDL covers missing/always identity, missing ownership and missing default.

**Limits:** The legacy default expression and current sequence value are not verified; a wrong default can pass. See ADR 0093.

## 2026-11-24 — PostgreSQL migration-recorder primary-key clue

**Changes:** The catalog inspector checks selected primary-key index properties for Django's migration recorder; a synthetic DDL test removes the key and substitutes a standalone unique index.

**Limits:** The primary-key physical type remains skipped, and sequence, defaults and migration records are not verified. See ADR 0092.

## 2026-11-24 — fail-stop synthetic backup example

**Changes:** The manual synthetic backup example chains all stages so a failed target creation cannot be followed by a restore. Offline fake-command tests exercise each failure; a separate PostgreSQL 16 synthetic-cluster probe checks target collision and a successful restore.

**Limits:** This is not an atomic, encrypted or production backup tool and relies on running the entire block against a disposable cluster. See ADR 0091.

## 2026-11-24 — optimization-safe synthetic restore checks

**Changes:** The opt-in synthetic restore fixture and identity-graph verification use explicit checks instead of Python assertions, so optimization cannot erase them. PostgreSQL tests verify valid and deliberately corrupted fixtures under `python -O`.

**Limits:** Only selected fixture checks and corruptions are exercised; this does not prove recovery of production backups. See ADR 0090.

## 2026-11-24 — PostgreSQL migration-recorder column clues

**Changes:** The inspector checks recorder-column presence, nullability and supported non-primary types. PostgreSQL tests remove each recorder column and alter selected nullability and types in rolled-back transactions.

**Limits:** The recorder primary-key type is skipped and counted; key constraint, sequence and migration-history content remain unchecked. See ADR 0089.

## 2026-11-24 — PostgreSQL unique-key operator and collation clues

**Changes:** Selected simple unique-key matches require B-tree, default operator-class flags and index collations matching their current columns. Rolled-back PostgreSQL tests cover discrepancies on both keys of a composite index.

**Limits:** A default flag is not an exact operator-class comparison; column collation versus model intent and full definitions remain unchecked. See ADR 0088.

## 2026-11-24 — PostgreSQL unique-key enforcement timing

**Changes:** Selected simple uniqueness matches must be enforced immediately; synthetic DDL tests cover deferrable constraints in both initial modes.

**Limits:** A standalone immediate unique index still matches and full constraint equivalence remains unchecked. See ADR 0087.

## 2026-11-24 — unsupported unique declarations

**Changes:** The read-only schema inspector reports unsupported managed-model unique declarations as an aggregate attention count instead of silently omitting them. Synthetic metadata tests cover conditions, expressions, include, operator classes, explicit null semantics, deferrability and subclasses.

**Limits:** This is a model-metadata coverage clue, not a comparison of those definitions or full schema equivalence. See ADR 0086.

## 2026-11-24 — PostgreSQL selected unique-key null semantics

**Changes:** The inspector flags `NULLS NOT DISTINCT` substitutes for selected model unique keys expecting PostgreSQL's default semantics; a synthetic PostgreSQL 16 DDL test exercises the discrepancy.

**Limits:** Explicit model null-semantics declarations and full uniqueness equivalence are not covered; other PostgreSQL versions are not tested. See ADR 0085.

## 2026-11-24 — PostgreSQL named-index collation and included-column clues

**Changes:** Supported simple named indexes are checked for index-versus-column collation mismatch and additional included columns; synthetic DDL tests cover both.

**Limits:** Column collation is not compared with model intent; exact operator class, storage options, plans and full definitions remain unchecked. See ADR 0084.

## 2026-11-24 — PostgreSQL named-index operator-class clues

**Changes:** The inspector flags supported named B-tree indexes whose key operator classes are not marked default; synthetic DDL tests include a nondefault pattern operator class.

**Limits:** This is not an exact operator-class comparison. Collation and complete definitions remain unchecked, and useful alternatives can be flagged. See ADR 0083.

## 2026-11-24 — PostgreSQL named-index null-order clues

**Changes:** The catalog inspector checks supported named index keys for the PostgreSQL default null order corresponding to each model-declared direction; synthetic DDL tests cover both ascending and descending mismatches.

**Limits:** Operator class, collation, performance and full definitions remain unchecked, and equivalent alternatives can be flagged. See ADR 0082.

## 2026-11-24 — PostgreSQL named-index direction clues

**Changes:** The read-only inspector compares each supported named index key's ascending or descending direction with the model declaration. Rolled-back PostgreSQL tests exercise mismatches on both keys of a two-key index.

**Limits:** Direction is only a conservative clue, not a plan or performance guarantee; null ordering, collation, operator class and full definitions remain unchecked. See ADR 0081.

## 2026-11-24 — PostgreSQL model-index presence clues

**Changes:** The catalog inspector checks selected field-index coverage and named model B-tree indexes against the current metadata, reporting unsupported named definitions as attention. Rolled-back PostgreSQL tests cover missing, partial, hash, reordered and alternate indexes.

**Limits:** Sort direction, operator class, collation, complete schema definitions and query performance are not verified; a useful alternative can be flagged. See ADR 0080.

## 2026-11-24 — synthetic post-restore sequence probes

**Changes:** The disposable PostgreSQL restore drill exercises new service writes across selected domains and checks generated IDs advance beyond restored records. A negative control rewinds one target-only synthetic sequence, detects an integrity failure, then resets it for a successful probe.

**Limits:** This is not a general sequence-repair recipe or proof that every sequence, backup or production workflow is safe. The modified target is disposable; see ADR 0079.

## 2026-11-24 — PostgreSQL managed-column type clues

**Changes:** Catalog inspection compares selected managed field types, including varchar length and numeric precision, against PostgreSQL. Unsupported types cause an incomplete/attention result. Synthetic rolled-back DDL exercises varchar, numeric and timestamp mismatches.

**Limits:** Auto-created many-to-many primary-key types are skipped and counted because runtime metadata and historical migrations differ; defaults, collations, generation, sequence state and complete schema equivalence are not checked. See ADR 0078.

## 2026-11-23 — cross-domain synthetic restore drill

**Changes:** The opt-in PostgreSQL restore drill now also restores and verifies selected synthetic source, product, price, receipt and clinical records and relationships, and runs the read-only catalog inspector on the restored database. A corruption probe checks that altered manifest and evidence snapshots are detected; additional fixture guards run before writes.

**Limits:** This sample does not prove complete restoration, provenance, encrypted/off-host backups, recovery time or production safety; see ADR 0077.

## 2026-11-23 — PostgreSQL readiness retry window

**Changes:** The development startup helper no longer starts a new readiness attempt after its monotonic retry window ends; it still performs one initial attempt even for a zero window. Deterministic clock tests and actual synthetic PostgreSQL success/absence tests cover the selected behavior.

**Limits:** This is not a hard wall-clock timeout or query cancellation; a connection, query or DNS operation already in progress can overrun it. See ADR 0076.

## 2026-11-23 — PostgreSQL managed-column clues

**Changes:** The development catalog inspection counts missing managed-model columns and differences in PostgreSQL nullability versus current model metadata. Synthetic rolled-back DDL tests cover a missing column and changes in both nullability directions.

**Limits:** It does not compare column types or defaults; a type change with the same name and nullability passes. It does not establish schema equivalence or production safety; see ADR 0075.

## 2026-11-23 — PostgreSQL named-check clues

**Changes:** Catalog inspection now reports missing explicitly named model check constraints and wrong constraint types; unvalidated checks remain separately flagged. Synthetic rolled-back PostgreSQL DDL exercises each case.

**Limits at that point:** The check compared name and type only. ADR 0104 later added exact true/null clues, but other tautologies still pass and an equivalent check under another name is flagged. It does not validate data, compare migrations or certify production safety; see ADR 0074.

## 2026-11-23 — PostgreSQL unique-key clues

**Changes:** The development-only catalog inspection flags missing selected simple model-declared unique and primary-key indexes, ignoring nonunique, partial, invalid or wrong-column indexes. Rolled-back PostgreSQL tests exercise composite keys, partial indexes and primary-key loss.

**Limits:** Order-sensitive clues can flag a logically equivalent reordered key; null semantics and other properties are not compared. This is not migration equivalence, data validation or production readiness; see ADR 0073.

## 2026-11-23 — PostgreSQL foreign-key behavior clues

**Changes:** The read-only catalog inspection now also counts matching expected foreign keys that depart from the current Django/PostgreSQL deferred and `NO ACTION` conventions, including unexpected duplicate immediate or cascading constraints. Selected PostgreSQL DDL tests verify these cases with rolled-back synthetic data.

**Limits:** This compares current model-declared pairs and observed catalog attributes, not complete migrations or ORM deletion behavior. It does not repair or certify the database; see ADR 0072.

## 2026-11-23 — isolated general PostgreSQL test databases

**Changes:** Opt-in general synthetic test settings assign a fresh random test database per invocation and reject reuse and Django parallel mode; CI uses them for the ordinary suite. A local two-process probe verified distinct databases and passing PostgreSQL catalog tests.

**Limits:** This is probabilistic name isolation on an already disposable cluster, not a production safeguard; abrupt termination can leave orphaned databases. A previous overlapping run against the shared default database failed when one process removed it; see ADR 0071.

## 2026-11-23 — PostgreSQL catalog clues

**Changes:** A development-only, read-only command reports aggregate counts of unresolved managed tables, non-table relations, missing model-declared single-column managed-table foreign keys, unvalidated constraints, unusable index states and disabled triggers. Synthetic PostgreSQL tests create actual selected defects, including a failed concurrent index build and a missing or wrong-target foreign key; CI runs the command after migrations.

**Limits:** It does not compare complete schema definitions with migrations, detect missing non-FK constraints or indexes, validate application data or certify backups, security or production readiness. Only scoped resolved tables are examined; see ADR 0070.

## 2026-11-23 — product detail consistency gate

**Changes:** Product detail reuses its existing candidate comparison availability to suppress the review form and show a warning when the observed candidate payload or derived identity is inconsistent. Tests cover changed payloads, stale and invalid submissions, coherent rewrites and a selected non-snapshot race; write-side validation remains independent.

**Limits:** Raw fields and history remain visible to authorized staff. This is not authenticity, legal authorization, confidentiality or snapshot isolation; see ADR 0069.

## 2026-11-23 — source detail review comparisons

**Changes:** Source detail checks up to 25 displayed review snapshots and reports limited comparisons to the observed claim, suppressing review details if the current claim or historical review is inconsistent, or the reviewer account is missing. The latest-review token and write-side behavior remain unchanged. Tests exercise a selected stale-read race and successful fresh review after a corrupt historical row.

**Limits:** Separate reads are not a snapshot and coherent alteration may pass. Raw current claim data remains visible to authorized staff. No source rights, authenticity, reviewer qualification, chronological cause or history completeness is established; see ADR 0068.

## 2026-11-23 — source review snapshot inspection

**Changes:** Authorized development staff can scan up to 50 source-review records per section for structural and payload consistency without displaying snapshot content, reasons, accounts, or hashes. Filters operate within the scanned section and malformed inputs receive private non-reflecting recovery. Synthetic database and Chromium checks cover permissions, bounded pagination, keyboard access, and non-snapshot behavior.

**Limits:** Coherent rewrites can pass; this is not an authenticity, source-rights, account-existence, qualification or completeness check. Reads are not a snapshot; see ADR 0067.

## 2026-11-23 — source claim creation conflict handling

**Changes:** Source-claim creation translates selected PostgreSQL write conflicts after rollback, and the staff form returns a private HTTP 409 rather than a raw database failure. Tests include a real unique-insert lock timeout at the service and HTTP boundaries, plus simulated selected failures after insertion and explicit replay preserving the original recorder.

**Limits:** No automatic retry, source authorization, production guarantee or outer-commit handling is added. Real deadlock and serialization failures on this path were not reproduced; see ADR 0066.

## 2026-11-23 — price detail consistency gate

**Changes:** A staff price detail now checks the staged payload before computing its current suggestion; an inconsistent payload shows a warning and suppresses that suggestion and new review form. A stale POST still fails at the existing write-side check. Queue and detail candidate queries no longer join an unused stored suggestion. Synthetic regressions cover changed amount, fields, hash and URL, conflict responses and SQL joins.

**Limits:** Raw fields and review history can remain visible to authorized staff. Consistency is not authenticity or confidentiality, the queue does not run this check, and reads are not snapshots; see ADR 0065.

## 2026-11-23 — unsafe presentation text in price matching

**Changes:** Price matching marks an identity ambiguous when a matching presentation has invalid matching text or an unsafe displayed Persian name, rather than ignoring it or suggesting it. An unassignable non-string matching field makes its IRC group ambiguous. Staging, fresh suggestions and acceptance use the shared check; stored history is unchanged. Synthetic tests cover all fields, duplicate conservatism, receipts and acceptance.

**Limits:** This is a narrow text check, not product verification, spoofing protection or uniqueness under concurrent writes. Unpublished rows may still be suggested; see ADR 0064.

## 2026-11-23 — projection repair conflict handling

**Changes:** The default-database synthetic projection writer now translates three selected PostgreSQL concurrency failures after rollback into its existing domain error; the CLI reports its generic failure. Tests exercise a real lock timeout at service and command boundaries and simulated selected failures after an update.

**Limits:** There is no automatic retry. Real deadlocks and serialization failures in this path, surrounding-transaction commits and production operation are not established; see ADR 0063.

## 2026-11-23 — price candidate CLI consistency check

**Changes:** The local listing now checks stored price payload/derived values before emitting full fields or computing a current suggestion. Inconsistent rows receive a reduced JSON shape and `payload_status: invalid`; consistent rows receive `payload_status: consistent`. The stored-status filter and row limit are unchanged. Synthetic tests cover malformed and altered payloads, filtering and coherent recomputation.

**Limits:** This is not a confidentiality, authenticity, source-rights or review-eligibility check; coherent alteration and sensitive content can still pass. Local CLI access is not controlled by web authorization. See ADR 0062.

## 2026-11-23 — identity lineage cursor depth bound

**Changes:** Identity-lineage continuation rejects a signed depth greater than the positive ID gap between anchor and current record. Synthetic tests reproduce the previously accepted impossible depth, verify a private error and check all four identity kinds.

**Limits:** This necessary arithmetic bound does not prove that any skipped links existed or remain unchanged. Signing-key holders can still produce plausible cursors; see ADR 0061.

## 2026-11-23 — clinical scan guide correction

**Changes:** Corrected the development guide's clinical scan sequence, author-presence precedence and maximum four service SELECTs to match ADR 0056 and the existing implementation. The prior guide text was stale; no application behavior changed.

## 2026-11-23 — inactive-user backend login edge

**Changes:** If an authentication backend returns an inactive user, the staff form now clears its cached identity and returns the same generic invalid-login error as bad credentials. Synthetic tests override the backend to exercise this path, session behavior and independent destination permissions.

**Limits:** The default backend already rejects inactive users, and no HTTP login bypass was demonstrated. Custom backends and production authentication still need independent review; this adds no MFA or throttling. See ADR 0060.

## 2026-11-23 — synthetic stream and time-window regression coverage

**Changes:** CSV tests compare fragmented reads and replay manifest membership across multiple chunk sizes and invalid tails. A seeded, independent UTC-window enumeration checks returned plans across ten time zones and selected transition dates; a larger 50,000-sample local probe found no returned-plan mismatch.

**Limits:** These sampled synthetic tests do not prove complete timezone coverage, inspect cases the implementation rejects, establish source rights or operate a scheduler; local tzdata determines the rules tested.

## 2026-11-23 — skip-link viewport failure diagnostics

**Changes:** A failed skip-link visibility assertion's allowlisted CI annotation now identifies affected viewport sides and coarse overflow distances, without copying geometry or arbitrary diagnostic text. Reduced-motion CSS now uses zero transition/animation duration instead of inadvertently introducing a 0.01ms transition even on the previously non-transitioning skip link. Chromium checks the computed timings and rejects a nonzero-duration mutation.

**Limits:** CI run 45263717417 failed forced-colors home visibility with an element outside the viewport; its log download returned EOF and GitHub rejected the rerun. The failure's side and cause remain unknown; this CSS correction and diagnostic are not proven to resolve it or to establish accessibility.

## 2026-11-23 — bounded CSV short-read handling

**Changes:** Both synthetic CSV parsers now join ordinary short reads up to EOF or one byte beyond the existing size cap before validating any rows. A reproduced prefix-acceptance bug could otherwise stage a partial file; tests check valid and invalid tails, no partial receipt, byte and call limits, HTTP and CLI read failures.

**Limits:** EOF is trusted, reads can block and callers with exceptionally fragmented streams may hit the read-call cap. This is not file provenance, source authorization or a production availability guarantee; see ADR 0059.

## 2026-11-23 — ID-only account existence reads

**Changes:** Source and clinical queue presence checks and both account checks in the clinical technical scan now select only account IDs, rather than full account objects. Tests cover invalid/duplicate IDs, inactive users, alias forwarding, query columns and the existing bounds.

**Limits:** This applies only to selected existence reads; authentication, display and other workflows may still fetch account attributes, and IDs may be logged. Existence is not identity, qualification or authorization, and the separate reads are not a snapshot; see ADR 0058.

## 2026-11-23 — source queue recorder-presence clue

**Changes:** The source queue now uses a single page-local account lookup and flags currently missing recorders while retaining the claim and independent date status. Synthetic tests cover privacy, inactive accounts, page bounds, the empty result and separate reads; Chromium exercises the explanatory text.

**Limits:** Existence is not identity, activity, authorization or source-rights verification, and the unlocked reads do not form a snapshot. Date inspection retains its separate behavior. See ADR 0057.

## 2026-11-23 — clinical inspection author-presence clue

**Changes:** The bounded clinical scan now reports a separate current-author-missing status before checking supplementary references. A page-local account lookup adds at most one SELECT, and the private page offers a filter and explains the limited check. Synthetic tests cover precedence, account absence, pagination, privacy and the unexamined parent author.

**Limits:** Account existence is not activity, identity or qualification; reads are separate and non-snapshot, and parent authors and reviews remain unchecked. This is not clinical approval; see ADR 0056.

## 2026-11-23 — selected CSV staging conflict handling

**Changes:** Product/price staging and their receipt transactions translate selected PostgreSQL concurrency failures after rollback. Uploads return a private 409 and ask for the file to be selected again; the price CLI reports a command error. Synthetic tests cover actual advisory-lock timeouts and simulated candidate/manifest rollback.

**Limits:** No timeout, automatic retry, source verification or publication is introduced. Unknown errors, connection loss and later enclosing-transaction commits remain outside the guarantee; see ADR 0055.

## 2026-11-23 — clinical draft and reference write conflict handling

**Changes:** Clinical draft creation/revision and supplementary-reference creation translate selected PostgreSQL concurrency failures after rollback; initial draft creation now also returns a private generic 409. Synthetic tests cover actual lock timeouts for revision/reference and simulated errors, rollback and HTTP responses for all three forms.

**Limits:** No timeout or retry is configured; enclosing-transaction commit, pre-write reads and unrelated errors remain outside scope. Deadlock and serialization tests for these writers are simulated; see ADR 0054.

## 2026-11-23 — selected header action accessibility checks

**Changes:** The header search action has an opaque background. Chromium checks its label and decorative arrow against the selected background at rest and on hover in four widths, rejects selected low-contrast/compositing mutations, and follows the accessible link using a real keyboard sequence.

**Limits:** These are computed-style and selected keyboard checks, not pixel rendering, a screen-reader test or an accessibility certification. Axe still reports the decorative arrow as inconclusive; manual review remains necessary.

## 2026-11-23 — selected triage write conflict handling

**Changes:** The four preliminary review writers translate selected PostgreSQL lock/deadlock/serialization errors into their existing conflict responses after transaction/savepoint rollback; synthetic tests cover rollback and private HTTP 409 responses, with real lock-timeout races across all four domains.

**Limits:** No timeout or retry is configured; a failure at an enclosing transaction's later commit and other services/errors remain outside the boundary. Deadlock and serialization are exercised on PostgreSQL for the source writer and simulated for the other three; see ADR 0053.

## 2026-11-23 — selected product-candidate latest-review lock

**Changes:** Product triage locks its latest existing review while comparing the prior ID. Synthetic PostgreSQL tests cover selected competing writers, transaction boundaries and deferred insertion; the private detail page describes history limitations.

**Limits:** Only the latest existing row and its ID are involved; prior content is not checked, deferred insertion and later bypass remain possible, and additional locks may wait or deadlock. No retry, approval or publication is added; see ADR 0052.

## 2026-11-23 — selected price latest-review lock

**Changes:** Price triage locks its latest existing review while comparing the prior ID. Synthetic PostgreSQL tests cover selected competing writers, transaction boundaries, deferred insertion and the acceptance path holding the existing product lock; the private page describes history limits.

**Limits:** Only the latest existing row and its ID are involved; prior content is not checked, deferred insertion and later bypass remain possible, product matching is not a uniqueness guarantee, and added locks may wait or deadlock. No retry, approval or publication is added; see ADR 0051.

## 2026-11-23 — selected source latest-review lock

**Changes:** Source triage locks its latest existing review while comparing the prior ID. Synthetic PostgreSQL tests cover selected competing writers, transaction boundaries and deferred insertion, and the private detail page describes history limitations. A clinical test also checks a preceding update with unchanged ID.

**Limits:** Only the latest existing row and its ID are involved; prior content is not checked, deferred insertion and later bypass remain possible, and lock waits/deadlocks are possible. No retry, legal approval or source access is added; see ADR 0050.

## 2026-11-23 — selected clinical latest-review lock

**Changes:** Clinical triage locks the latest existing review row while checking its prior-ID token. Synthetic PostgreSQL tests cover competing updates/deletions, an earlier deletion, outer transaction lifetime and selected non-guarantees; the private page clarifies that this is not full history validation.

**Limits:** Only the latest existing row is locked, only its ID is checked, deferred bypass inserts and later changes remain possible, and additional locks may wait or deadlock. No retry or clinical approval is added; see ADR 0049.

## 2026-11-23 — development staff login policy

**Changes:** The development staff login form rejects authenticated nonstaff accounts using the same visible error as invalid credentials, without creating a new authenticated session. Staff with no domain permission can still sign in but are denied domain access; tests cover subsequent demotion and an existing session.

**Limits:** This only affects the staff form, not other authentication mechanisms or existing sessions. It does not add MFA, rate limiting, audit or production readiness. See ADR 0048.

## 2026-11-23 — stronger hero contrast test boundaries

**Changes:** Selected hero text and search-placeholder contrast checks run at four viewport widths and fail closed on selected opacity, filter, blend and background layers. Deliberate compositing and low-contrast mutations verify the checks.

**Limits:** This checks computed colors, not actual pixels, all overlays, states or accessibility criteria; other axe contrast results still need manual review.

## 2026-11-23 — oversized public product paths

**Changes:** Known public product URL shapes retain privacy headers when an extremely long numeric ID fails URL resolution, including HTTPS redirects. A synthetic test reproduced the previously missing headers before the fix.

**Limits:** This does not redact URLs from logs or govern unrelated or upstream-generated responses. See ADR 0044.

## 2026-11-23 — malformed signed cursor timestamps

**Changes:** The shared cursor decoder now maps Django's `IndexError` and `OverflowError` for validly signed empty or extreme timestamps to generic invalid-cursor errors. A synthetic test reproduced the previous public HTTP failure before the fix and now covers all four cursor decoders.

**Limits:** Generating these valid signatures requires the signing key; development's fallback key is public. This is not key management or a production security assessment. See ADR 0047.

## 2026-11-23 — in-flight search observation boundary

**Changes:** Coordinated synthetic PostgreSQL tests demonstrate that a name change or withdrawal committed after search fetch does not alter the already-fetched in-flight result. Subsequent reads reflect the change; API and architecture documentation now state this exposure window.

**Limits:** These tests characterize selected schedules, not a fix, immediate-withdrawal guarantee or proof of all concurrency behavior. See ADR 0046.

## 2026-11-23 — future-dated cursor rejection

**Changes:** Public search, catalog IRC inspection, identity lineage and clinical lineage now reject correctly signed cursors dated after the verifying host's clock, in addition to their existing maximum-age checks. Controlled-clock and synthetic HTTP tests cover the four consumers.

**Limits:** Clock skew or rollback can reject legitimate cursors; monitoring and synchronization are not implemented. Tokens remain signed, not encrypted. See ADR 0047.

## 2026-11-23 — current-field public search recheck

**Changes:** Before displaying a SQL search candidate, recheck that its fetched current normalized fields still contain the query. Synthetic tests cover stale positives and negatives, unchanged valid matches, Persian normalization and continuation after 150 stale hits.

**Limits:** Stale indexes can still hide matches; this does not repair data, offer a snapshot or prove identity or clinical correctness. See ADR 0046.

## 2026-11-23 — early HTTPS redirect privacy

**Changes:** A response-only middleware wraps Django's security middleware so its early HTTPS redirects receive the existing privacy headers for known public-read and staff paths. The HTTPS redirect and the disabled staff gate retain their order; synthetic tests cover both, methods, query retention and lookalikes.

**Limits:** Proxy-generated redirects, request logging and other paths remain outside scope; redirect locations retain queries. See ADR 0044.

## 2026-11-23 — public display control-character guard

**Changes:** Shared public presentation eligibility now rejects non-string display fields and Unicode control/surrogate characters, including in optional fields and source metadata. Synthetic bypass tests cover HTML and JSON search/detail; Persian zero-width non-joiners remain valid.

**Limits:** This does not repair records or establish identity, source authenticity, Unicode spoofing protection, clinical validity or production readiness. See ADR 0045.

## 2026-11-23 — slashless privacy boundaries

**Changes:** Known slashless search and product routes receive the public privacy headers even on Django's append-slash redirect; the staff root without a slash receives staff privacy headers and is blocked when the development portal is disabled. Exact path boundaries and redirect queries are tested.

**Limits:** Redirects retain query strings; upstream redirects, logging, proxies and other unresolved paths remain outside scope. See ADR 0044.

## 2026-11-23 — isolated synthetic restore drill

**Changes:** An opt-in PostgreSQL test creates separate random synthetic source and target databases, verifies archive creation, one failed truncated restore, a full restore, migration state and a synthetic identity graph. CI runs it with matching PostgreSQL 16 client commands in a container; the designated test runner refuses parsed reuse and parallel options for restore and browser exercises, including abbreviations. Explicit runner overrides bypass that guard.

**Limits:** This is not an encrypted/off-host backup, production recovery policy, complete-data verification or clinical assurance. Use a disposable cluster only; see ADR 0043.

## 2026-11-23 — skip-link diagnostic classification

**Changes:** Restore privacy-preserving CI classification of the structured skip-link visibility assertion; report only fixed failure categories, not the diagnostic JSON. Test malformed and injected input. A separate local 100-context forced-colors probe passed.

**Limits:** The earlier CI failure was not reproduced and its cause remains unknown; the probe is not a real-device accessibility test.

## 2026-11-23 — selected identity write concurrency errors

**Changes:** After rollback, selected private identity writer boundaries convert PostgreSQL lock-not-available, deadlock and serialization SQLSTATEs to a generic conflict; private HTTP writers return 409. Actual synthetic PostgreSQL timeout, deadlock and serialization tests cover selected schedules.

**Limits:** No timeout or automatic retry is configured; errors at a later outermost commit remain the caller's responsibility. The whole enclosing transaction must be abandoned/retried as appropriate after deadlock or serialization failure. See ADR 0042.

## 2026-11-23 — latest identity package review lock

**Changes:** Package review and correction now lock the latest existing review before their existing optimistic-token checks; correction still validates that row structurally. Synthetic PostgreSQL tests cover selected update, delete, outer-transaction, older-row and concurrent insertion cases.

**Limits:** This is not a history, absent-row or predicate lock; review creation still checks only the previous ID, and concurrent deferred inserts or later/same-transaction bypasses remain possible. See ADR 0041.

## 2026-11-22 — bounded identity component and ingredient locks

**Changes:** Selected identity dependent-creation, package-review and correction services now lock and re-read bounded existing component and ingredient rows after their applicable parent locks. Missing rows fail closed. Synthetic tests exercise both update directions across six writer paths, shared ingredients, outer transactions, bounded SQL and a deferred concurrent insertion.

**Limits:** New rows and later or same-transaction bypass mutations can still stale observations; locks are not gap locks or evidence of authenticity. Waiting/deadlocks remain possible without retry. See ADR 0040.

## 2026-11-22 — identity package formulation lock

**Changes:** Package review and correction now re-read and lock the product's formulation after the package/product locks. Missing formulations conflict. Synthetic tests cover selected contention in both directions, cached rows, missing FKs, outer transactions and still-unlocked component/ingredient changes; interface text describes the limits.

**Limits:** Ingredient/component rows and account identities remain outside this explicit lock, the reads are not a full snapshot, and a same-transaction bypass can add components. More locks can wait or deadlock; no retries or production/clinical guarantee. See ADR 0039.

## 2026-11-22 — identity package immediate-product lock

**Changes:** Package review and correction lock the package then re-read and lock its immediate product before evaluating the graph. Missing products conflict, and direct non-string review decisions now conflict rather than raising an unhashable-input type error. Synthetic PostgreSQL tests exercise both lock directions, cached reads, outer transactions, missing products, validation and an unlocked formulation mutation; Chromium checks the new scope notice.

**Limits:** This is not whole-graph isolation: formulation, ingredients, components and exclusive account locks are outside this change. More locks can wait or deadlock; no retries, clinical approval or production guarantee. See ADR 0038.

## 2026-11-22 — identity graph creator presence in writes

**Changes:** Selected identity dependent creation, package review and correction writers now reject a missing current creator anywhere in their validated current graph, with one bounded bulk account read per check. Tests cover every graph position with temporary deferred-FK account deletion, independent permissions and self-review, conflicts and rollback, inactive accounts, maximum graph size and selected unlocked/bypass behavior.

**Limits:** Structural views and lineage remain account-independent; creator accounts are not locked or authenticated, correction ancestor/link actors are not checked, and graph reads are not a snapshot. See ADR 0037.

## 2026-11-22 — identity package review account display

**Changes:** Identity package history and correction pages retain reviews but suppress details when the current reviewer account is missing, using a bounded page-local lookup. Cursor positions and real latest-review versions remain intact; missing prior accounts alone do not block later review or correction. Identity workspace and lineage pages explicitly warn that graph/link creator existence is not checked. Synthetic tests cover permissions, missing reviewers, pagination, fresh/stale submissions, account/graph boundaries and stale reads.

**Limits:** Separate reads are not a snapshot and an existing account does not establish historical identity, reviewer qualification or graph validity. Graph creator existence is still not enforced; see ADR 0036.

## 2026-11-22 — missing receipt actor accounts

**Changes:** Permission-scoped receipt lists and details retain receipts with a missing current actor and show a notice, with one page-local account lookup rather than an inner join. Related-receipt and manifest-inspection pages state that they do not check receipt actors. Synthetic tests cover orphaned product/price receipts, privacy and domain permissions, legacy data, pagination/query counts and stale reads; Chromium exercises ordinary pages at four widths.

**Limits:** An account name is not historical identity or authorization, and separate reads are not a snapshot. Receipt actor changes, other relationships, authenticity and production use are not guaranteed; see ADR 0035.

## 2026-11-22 — missing product and price stager accounts

**Changes:** Product and price review now conflict if the current stager account is missing. Orphaned products remain visible, both details show a notice and disable review, and nullable price stagers retain their separate handling. Comparisons and receipt inspections explicitly describe their narrower checks. Synthetic tests exercise service and HTTP paths, all decisions, nullable and inactive accounts, diagnostic boundaries and selected bypass/race limitations.

**Limits:** Existence is not attribution or authorization and accounts are not locked; receipt actors and other relationships are outside this change. See ADR 0034.

## 2026-11-22 — missing source and clinical creator accounts

**Changes:** Source review and the three clinical writers now reject a missing current creator account. Source and clinical queues/details retain orphaned rows; clinical text/actions are hidden and source review is disabled. The clinical queue uses a page-local author lookup. Synthetic tests cover deferred-FK corruption, direct/HTTP writes, ordinary and inactive accounts, ancestor and diagnostic boundaries, nonparticipating mutations and selected account-update races; scan pages explain that they do not check creator accounts.

**Limits:** Existence is neither historical identity nor qualification, accounts are not locked, and parent authors or other domains are not covered. Nonparticipating changes can occur after the check. Synthetic only; see ADR 0033.

## 2026-11-22 — reviewer lookup in intake histories

**Changes:** Source, product and price detail retain recent review rows even if their reviewer account is missing, show an unknown-details notice and keep the real latest review ID in the form. The bounded reviewer lookup is shared with clinical detail. Synthetic tests cover missing latest and older reviewers, stale and fresh submissions, permissions, 25-row/query bounds and non-snapshot lookup; Chromium checks normal histories at four widths.

**Limits:** A fresh review remains permitted when a previous reviewer is absent. Lookup is not a historical identity check, audit or review-snapshot validation. Missing parent authors, direct database writes and later changes remain out of scope; see ADR 0032.

## 2026-11-22 — clinical review detail comparison boundaries

**Changes:** The private detail distinguishes the reviewed draft/author comparison from the reference-set comparison, uses the existing technical classifier before displaying historical assertions, and treats missing evidence without claiming age. Invalid record decisions and reasons are suppressed, and a missing reviewer no longer hides the row or resets the expected-review ID. Tests cover corruption, contributor conflicts, separate-read and ABA behavior, the 25-row cap, query counts and synthetic Chromium at four widths.

**Limits:** Readings are non-snapshot; a match does not prove absence of intervening changes, actor qualifications, source rights or clinical correctness. A corrupted missing draft author can still hide the draft in the existing detail join. No historic data is rewritten or authenticated; see ADR 0031.

## 2026-11-22 — immediate-parent locks for clinical writes

**Changes:** Review, supplementary reference addition and revision creation now lock and re-read the immediate parent of the already locked draft before their local consistency check. Selected PostgreSQL tests cover both directions of parent updates, stale preloaded objects, sibling contention, rollback, missing parents and outer transaction lifetime.

**Limits:** Only one parent is checked; a grandparent can change during review. Later bypass writes and deferred reference inserts can still stale observations. More locks can increase waits or deadlocks and no retry is provided. This is not provenance, clinical approval, whole-lineage validation or production hardening. See ADR 0030.

## 2026-11-22 — limited clinical reference row locking

**Changes:** Review and reference addition lock the bounded existing assertion rows after the draft lock, before validation, while read-only inspection stays non-locking. PostgreSQL tests exercise waiting updates, stale conflicts, rollback, outer transaction lifetime and the 11-row sentinel. The specific concurrent existing-reference update from ADR 0028 is blocked while the write transaction holds the lock.

**Limits:** Later updates and pending new inserts can stale snapshots; a separate test demonstrates an unprotected concurrent parent update. There is no predicate or parent lock, retry, audit or clinical guarantee, and locks can wait or deadlock. See ADR 0029.

## 2026-11-22 — source and clinical triage boundaries

**Changes:** Source review rejects malformed/out-of-range IDs, boolean IDs and non-string decisions; clinical review applies the same expectation bounds and decision type check. Both hidden fields reject out-of-range values and offer a private, explicit detail-page restart. Tests exercise direct services, permissions, HTTP errors, synthetic Chromium recovery and selected PostgreSQL review races. Clinical detail warns about stale reference snapshots.

**Limits:** A controlled bypass writer can change an existing clinical reference during review despite the parent lock, leaving a coherent but already stale review snapshot. This limitation is demonstrated, not fixed. Results are not a production concurrency, source-rights, audit or clinical guarantee. See ADR 0028.

## 2026-11-22 — focusable skip target and failure categories

**Changes:** The shared main landmark is focusable by native fragment navigation but not in normal Tab order. Browser checks wait for actual landmark focus before Tab, verify a missing target tabindex fails, and report only a fixed active-element region on selected failures. This follows CI run 45137885675, which failed the login skip next-focus check at 1440 pixels.

**Limits:** The active element in that historical run was not recorded; the failure's cause remains unknown, as does the older home failure's. This change is not a demonstrated root-cause fix or screen-reader and cross-browser certification. See ADR 0027.

## 2026-11-22 — skip navigation and contrast checks

**Changes:** The staff login form no longer forces focus to username. Real-keyboard browser coverage now checks skip navigation on home, about and login, invalid-login recovery and selected forced-color states, with negative mutation tests and bounded diagnostic annotations. The test waits for the fragment before Tab and keeps axe outside the keyboard sequence. Darkened a home eyebrow and decorative captions after axe reported low contrast; selected opaque-background contrast checks were added.

**Limits:** CI run 45135591434 failed on the old home skip assertion; its full log was unavailable and rerun failed. The cause and width remain unknown, and later passes do not prove the historical failure fixed. Some axe results remain inconclusive; manual contrast, screen-reader, other-browser and device review remain necessary. See ADR 0027.

## 2026-11-22 — receipt validation reuse and product triage checks

**Changes:** Receipt detail and inspection reuse pure candidate integrity results within a single joined page/batch while checking each manifest row independently; tests cover duplicate and distinct candidates, corruption, page boundaries, operation and query counts, and a duplicate receipt in Chromium. Product review IDs are bounded in the form and direct service; PostgreSQL tests exercise selected simultaneous reviewers and candidate updates.

**Limits:** This is not an optimization of staging writes, a benchmark, a database snapshot or proof of provenance/identity. Privileged writers can bypass review protocols; no retry, audit or production guarantee is added. See ADR 0026.

## 2026-11-22 — bounded receipt-row consistency inspection

**Changes:** Added a private, permission-scoped, read-only inspection of one receipt at a time, scanning up to 50 current candidate comparisons plus lookahead and filtering only within that batch. Shared the structural and per-row checks with receipt detail. Tests cover both domains, legacy and corrupt manifests, permissions, private errors, query counts, selected non-snapshot behavior and synthetic Chromium access at four widths.

**Limits:** Technical consistency is not file provenance, source authorization, identity or clinical approval. Aggregate and row reads can observe different times; no snapshot or complete-history claim is made. Recorded price matching is not recomputed. Synthetic data only; database work and bytes are not bounded by the output cap. See ADR 0025.

**Browser-test correction:** A later recurrence of the 320px upload-result failure showed `staff.css` had not yet applied (`display: block`, no input max width) when layout was measured. The POST test now waits for page load, explicitly asserts the stylesheet's grid is applied, and exercises an intentionally delayed stylesheet; it still fails on real overflow. Earlier CSS width constraints remain, but the prior change alone did not establish the cause of every occurrence.

## 2026-11-22 — explicit synthetic projection repair

**Changes:** Added a DEBUG-only local command to preview a single presentation's projection drift and explicitly repair only derived fields after a signed, short-lived state/database recheck under a row lock and a synthetic-data attestation. Tests cover stale/deleted records, malformed inputs, time precision, failure rollback, private output, CLI flags, matching/search effects and selected PostgreSQL concurrency.

**Limits:** Repair can alter search and matching of already-published records without changing publication flags. It does not verify identity, rights or clinical content; DEBUG and attestation do not make real data safe. There is no batch operation, audited user attribution, automatic retry or production authorization. See ADR 0024. During validation, Chromium intermittently reported horizontal overflow in the 320px price preview; geometry identified the file input extending beyond the viewport. The form grid and file input now have bounded widths, and the browser smoke checks a long selected filename. Overflow failures report bounded geometry without form values; broader browser/device coverage remains incomplete.

## 2026-11-22 — presentation partial-save projection consistency

**Changes:** Nonempty partial model saves lock and read the presentation row inside a transaction before recomputing the search and IRC projections. Deprecated Django 5.2 positional save parameters are parsed before projection handling; empty updates remain no-ops. The quality inspector shares the projection field list. Synthetic PostgreSQL tests exercise overlapping partial saves, lock waits, errors, rollback, stale instances, positional calls and pricing lookup.

**Limits:** This adds locking and possible waits/deadlocks without retries. Bulk/SQL writes, historical models and stale full saves are not covered; existing inconsistencies are not automatically repaired. It does not prevent concurrent duplicate matching rows or provide source or clinical verification. See ADR 0023.

## 2026-11-22 — price review concurrency limits and validation

**Changes:** Added separate-connection PostgreSQL tests for simultaneous reviewers, locked product updates, concurrent duplicate inserts and a staging cache observed across a committed product change. The price detail page now warns that acceptance does not guarantee uniqueness. Review service and form reject out-of-range IDs, with direct service calls rejecting boolean IDs and malformed decisions.

**Limits:** One test deliberately reproduces a duplicate inserted between the fresh locked match and acceptance; it is not fixed by this change. Row locks do not protect absent matches or future writes. Tests cover selected interleavings with synthetic data, not production behavior or an approval, provenance or audit system. See ADR 0022.

## 2026-11-22 — bounded per-IRC price matching reuse

**Changes:** Added a per-invocation, eight-group LRU of bounded candidate indexes, so distinct price identities sharing an IRC can reuse one catalog query. Fresh matching and accept-review use the same matching logic, retaining conservative over-limit ambiguity and row locking. Tests compare the previous algorithm, exercise stale indexes, duplicate matches, the 100/101 boundary, eviction and changing catalog data; Chromium covers a synthetic multi-identity preview.

**Limits:** Cached IRC groups can miss catalog changes across distinct identities; eviction can mix observations from different times with older per-identity results. This is not a snapshot, validation of product or source, or production benchmark. Cache group/row limits do not bound byte size, database work or time.

## 2026-11-22 — request-local price matching reuse

**Changes:** Price CSV preview and staging now reuse one matching observation per normalized identity within each invocation, preserving per-row counts, receipts, source/payload deduplication and fresh detail and accept-suggestion review matching. The web form and CLI explain the reuse. Tests cover 5,000 repeated and distinct keys, all identity fields, ambiguous sets, replay, receipt outcomes, rollback and catalog changes between rows; synthetic Chromium exercises price preview at four widths.

**Limits:** Repeated rows may reuse a stale first observation if the catalog changes during the call; different identities can reflect different times. This is not a snapshot, production benchmark, source authorization or approval. Up to 5,000 distinct identities can still cause 5,000 matching queries; byte size, database work and time are not bounded by the cache.

## 2026-11-22 — synthetic clinical review snapshot inspection

**Changes:** Added a private read-only, per-draft, 50-review scan with page-local status filters and non-reflecting error recovery. It validates supported historical draft and supplementary-evidence snapshot structures, reports missing or invalid images and compares the snapshot draft hash/author ID to a technically consistent current version. It shows IDs and fixed statuses only. PostgreSQL tests and synthetic Chromium exercise access, tampering, pagination and selected accessibility checks.

**Limits:** Missing evidence is not proof of age. Actor existence/qualifications, current evidence, provenance, source rights and clinical correctness are not established. The scan is non-snapshot, JSON bytes and database work are not bounded, and this is not an audit or production feature. Axe contrast inconclusives require manual review.

## 2026-11-22 — synthetic clinical parent-path inspection

**Changes:** Added a private, permission-checked, read-only inspector for up to 20 immediate-parent links per section, including restartable, signed, time-limited continuation and a generic non-reflecting cursor error. It checks observed payloads and seams, stops on inconsistencies and shows IDs only. PostgreSQL and synthetic Chromium tests cover paths, boundaries, stale/malformed cursors, permissions, concurrent-change seams and selected accessibility checks.

**Limits:** The path is not a snapshot or complete history; earlier links, reviews, authors and references are not revalidated on continuation. Hash consistency is not authenticity, source rights or clinical approval. Tokens can appear in logs; this remains development-only and axe contrast inconclusives require manual review.

## 2026-11-22 — batch clinical technical inspection queries

**Changes:** Replaced per-draft reference and recorder lookups in the clinical scan with a per-draft PostgreSQL window and bulk recorder lookup, retaining the existing shared reference/cap checks and over-limit precedence. The diagnostic now runs at most three SELECTs for 50 drafts and fetches at most 11 assertions per valid draft; the write/review workflow retains its individual state and snapshots. Added boundary, reused-instance, missing-recorder and equivalence tests.

**Limits:** This is not a consistent snapshot, and fewer returned rows/queries do not bound database work or establish clinical, source or audit validity. PostgreSQL query performance on production data is unmeasured; this remains a synthetic development diagnostic.

## 2026-11-22 — synthetic clinical technical inspection

**Changes:** Added a private, view-permission-only, forward-only inspection of up to 50 draft versions per section with page-local status filtering. Reuses current draft/immediate-parent and bounded supplementary-reference checks, shows only IDs and fixed statuses, and offers non-reflecting invalid-input recovery. PostgreSQL and synthetic Chromium tests cover validation, permissions, bounded queries, paging, privacy and selected accessibility checks.

**Limits:** Not a snapshot or full lineage/review audit; no check proves authenticity, evidence quality, source rights, clinical validity or publication readiness. Query count is bounded, not database work or response size/time; this remains development-only. Axe contrast inconclusives require manual review.

## 2026-11-22 — private scan error recovery

**Changes:** Authorized staff now receive a generic Persian HTTP 400 page for invalid catalog-quality or source-date scan parameters, with a fixed local restart link and no reflected input. Restart clears position and filter. Existing authorization, validation, privacy headers and scan limits remain unchanged. Server and synthetic browser tests cover error handling, access checks and recovery.

**Limits:** Invalid URLs can still be logged; the page is not a production security or accessibility review. Automated axe checks have inconclusive contrast results requiring manual review.

## 2026-11-22 — localized staff inspection IDs

**Changes:** The source-date and catalog-quality starting-ID forms now accept Persian, Arabic-Indic and ASCII digits, including mixed scripts. A shared bounded parser maps only these digits before integer conversion; the unchanged upper limit and permissions still apply. Unit, PostgreSQL and synthetic Chromium tests cover localized values, equivalence, exact boundaries and invalid formats.

**Limits:** Other numeral sets, signs, separators and exponent notation are rejected. HTML validates syntax only; the server checks the exact maximum. Device keyboards, screen readers and all browser engines remain untested; this does not change source rights or clinical validity.

## 2026-11-22 — staff inspection ID entry

**Changes:** Replaced the two starting-ID number controls with required numeric-mode text controls and an ASCII digit syntax constraint, plus visible accessible guidance. This preserves large integer text exactly and prevents empty or exponent-form submissions that the server rejected. Existing server limits, query behavior, permissions and data remain unchanged. Synthetic Chromium checks syntax and invalid submission at four widths; PostgreSQL tests cover the boundaries.

**Limits:** HTML validates syntax, not the exact upper numeric bound; 19-digit values above the maximum still get HTTP 400 from the server. Browser keyboards and native validation messages vary; real-device and screen-reader validation remains necessary. Axe contrast inconclusives still need manual review.

## 2026-11-22 — focus failure diagnostics

**Changes:** Browser failure annotations can now identify focus checks by an exact, fixed allowlist of control labels, viewport widths and failure reasons. Tests reject unrecognized and injected messages; no arbitrary assertion text is copied. The focus criterion, application CSS and failure behavior are unchanged.

**Limits:** Five consecutive local synthetic Chromium runs passed; the previous CI focus failure was not reproduced or explained. The annotation is heuristic, covers selected checks only, and does not replace logs or a manual accessibility review.

## 2026-11-22 — browser failure call-site diagnostics

**Changes:** Include up to two additional JavaScript call-site line numbers in browser-failure annotations, without copying arbitrary stack text or paths. A synthetic multi-frame test checks both the bound and redaction.

**Limits:** CI for the public-read header change failed at a focus-outline assertion; the failing control and root cause could not be determined from the available annotation, and the full job log was inaccessible. The additional lines can help diagnose a future failure but do not fix or explain this one.

## 2026-11-22 — public-read error privacy headers

**Changes:** A narrowly scoped response middleware applies `no-store`, `no-referrer` and `noindex` to resolved search, presentation detail and OpenAPI views, including Django's 405 and CSRF 403 responses. Existing view-level headers and allowed methods remain unchanged. PostgreSQL-backed tests cover GET/HEAD, selected 400/404/500 errors, unsafe methods with and without CSRF, method `Allow`, and unrelated staff/public policy isolation.

**Limits:** The policy does not cover unresolved requests, redirects before URL resolution or upstream responses; URLs can still appear in access logs. Debug error pages can expose request data. No rate limiting, logging redaction or production security review is added.

## 2026-11-22 — synthetic browser CI diagnostics

**Changes:** Failed isolated Chromium subprocesses in GitHub Actions now add a compact error annotation with an exit outcome, fixed heuristic category and optional smoke-test source line; timeouts are also noted. Offline tests check the summary and exclusion of arbitrary sample error text. Existing failure output and failure status are unchanged; no automatic retry is added.

**Limits:** The annotation does not explain every failure or replace full logs, and ordinary test logs can still contain synthetic values. A previous browser CI failure remained unexplained because its job log was inaccessible and rerun permission was denied; this diagnostic is for future failures, not a claim about that cause.

## 2026-11-22 — public-search cursor recovery coverage

**Changes:** Added server and synthetic Chromium regression tests for the existing invalid-cursor recovery: valid query retained, invalid cursor not echoed or resubmitted, and restart by Enter. Tests cover selected malformed Unicode, NUL and overlong cursors, GET/HEAD and privacy headers, plus layout at four widths and axe at 390. No search behavior or medical data changed.

**Limits:** The checks are not exhaustive input, accessibility, privacy or security reviews; access logs can still contain search URLs, and pagination is not a snapshot. Axe's inconclusive contrast results require manual review.

## 2026-11-22 — invalid public-search query handling

**Changes:** A NUL in a public search previously caused a PostgreSQL text error. Search now rejects NUL or surrogate code points in the retained query prefix before a database query, returning HTTP 400 with a blank recovery form or an `invalid_query` API error; the invalid input is not echoed. Existing 120-character truncation and other search normalization remain unchanged. Added PostgreSQL, API contract and synthetic browser regression tests.

**Limits:** This narrow check is not general input sanitization, logging protection, rate limiting, clinical verification or production hardening. Search URLs can still appear in access logs; never enter personal data.

## 2026-11-22 — internal inspection keyboard and contrast checks

**Changes:** Styled numeric inspection filters consistently with the existing controls. Expanded synthetic Chromium coverage for keyboard focus and Enter submission on source-date and catalog-quality inspections, including forced-colors emulation for the source-date form. Added computed text contrast checks for selected workspace, source summary and scan elements; deliberate low-contrast, background-image and missing-focus mutations are rejected.

**Limits:** These checks cover selected text and controls on known opaque surfaces, not all pixels, pages, assistive technologies or devices. Axe still reports inconclusive contrast items needing manual review. The changes do not alter application data or authorization.

## 2026-11-22 — bounded source claim date inspection

**Changes:** Added a private read-only date inspection for source viewers: a 50-claim ascending-ID scan with an optional batch-local category filter and continuation even through empty batches. It shows IDs and date categories, not source names or URLs, and does not modify data. Synthetic tests cover bounded traversal, permissions, invalid inputs, live changes and browser navigation.

**Limits:** This is neither a fixed snapshot nor proof of source rights, coverage or authorization; dates and assertions are unverified. It is not an alert, a scheduler, or a production-scale monitoring system. See the [development guide](DEVELOPMENT_GUIDE.md#development-only-source-rights-assertions).

## 2026-11-22 — page-local source claim date summary

**Changes:** Added a read-only date-category summary for the currently displayed, review-filtered page of source claims, using one local date for all rows. Tests cover boundaries, invalid claims, permissions, pagination, no writes and synthetic Chromium layout/accessibility checks.

**Limits:** Counts are page-local, not a global inventory or a consistent snapshot. Dates and claims are unverified; the summary does not establish source rights or authorize use, and does not alert or calculate upcoming expiry. Database filtering/counting work is not bounded by the page size.

## 2026-11-22 — workspace landing and unreviewed queue shortcuts

**Changes:** Active staff now land on the permission-scoped workspace by default after login; Django's explicit safe `next` destination still takes precedence and its own permissions remain enforced. Added shortcuts to the existing unreviewed filters for product, price, source and clinical queues. They add no counts, data writes, new review states or permissions.

**Limits:** Unreviewed means no recorded review event, not all outstanding work or eligibility for this reviewer. Existing reviewed/deferred records are excluded. The portal remains development-only, synthetic-data-only and not a production dashboard.

## 2026-11-22 — permission-scoped staff workspace navigation

**Changes:** Added a private, read-only `/staff/` navigation page and return link from private staff pages. Active staff see only links corresponding to existing view permissions; the page does not show counts, records or operational status. Login landing behavior and destination authorization are unchanged. Synthetic role, permission revocation, privacy, CSRF logout and Chromium/axe checks cover the new page.

**Limits:** This is navigation, not a production dashboard or an authorization boundary; each destination independently enforces its permissions. No metrics, scheduler, approval, publication, audit, MFA or production security capability is added. The portal remains development-only and synthetic-data-only.

## 2026-11-22 — read-only lock metadata comparison

**Changes:** Added an optional standard-library tool to compare both checked-in Python hash locks with current PyPI release metadata, plus offline tests for mismatches, invalid input and registry failures. It does not change lock files, application logic or data. See the [maintenance procedure](DEVELOPMENT_GUIDE.md#maintaining-python-dependency-locks).

**Limits:** This compares metadata hash sets rather than downloading artifacts or independently authenticating them. Registry changes and intentional artifact subsets can cause mismatches; a match is not a safety or reproducibility guarantee.

## 2026-11-22 — Python artifact hash locks

**Changes:** Added a runtime artifact lock with transitive pins and SHA-256 hashes, a direct-pin consistency check, and a separate hash lock for the development image's pip/setuptools upgrade. CI and Docker require hash verification; direct runtime versions and application/database behavior remain unchanged. See the [maintenance procedure](DEVELOPMENT_GUIDE.md#maintaining-python-dependency-locks).

**Limits:** Hashes verify selected bytes against checked-in values, not publisher authenticity or package safety; image tags, initial image tooling and audit-tool dependencies remain outside these locks. This is not a fully reproducible or production-hardened build.

## 2026-11-22 — dependency advisory checks

**Changes:** Added isolated `pip-audit` checks for resolved Python requirements and Python packages in the development image, plus an npm audit for browser dependencies. The local requirements and npm audits found no known advisories at the time of review. Older pip/setuptools in the ignored local development venv were updated after retaining the old wheels and package list under ignored `.cache/`. The development image now installs pinned newer pip/setuptools before the unchanged application requirements; no database or business logic changed.

**Limits:** Advisory databases change; checks require external registries and do not scan operating-system packages, Chromium, bundled native libraries or the auditor's own dependencies. Version pins are not package hashes, image tags remain mutable and this is not a production security assessment. See [Testing strategy](TESTING_STRATEGY.md#known-dependency-vulnerability-checks).

## 2026-11-22 — CI action runtime and pin review

**Changes:** Updated official checkout, setup-python and setup-node actions to version-specific v7 commit SHAs using the Node 24 Actions runtime, and disabled checkout credential persistence. Preserved the Python 3.11 and browser Node 22 environments and the PostgreSQL, browser and Compose checks.

**Limits:** SHA pins need regular review and do not verify upstream code, package downloads or mutable container images. This is not a complete supply-chain or production security assessment. See [Deployment](DEPLOYMENT.md#development-ci-and-proposed-cicd).

## 2026-11-22 — development build-context and PostgreSQL readiness review

**Changes:** Excluded local environment variants and JavaScript dependencies from Git/build context while preserving `.env.example` templates; hardened Docker exclusion ordering for backups and local dependency/cache directories. Added synthetic CI probes for root/nested excluded files and template exceptions, real PostgreSQL readiness and nonexistent-database checks; no schema or data migration changed.

**Limits:** Ignore rules do not remove already tracked secrets or old image layers and are not comprehensive secret scanning. CI uses a disposable Compose volume; this is not production hardening or disaster recovery. See [Testing strategy](TESTING_STRATEGY.md#development-image-build-context-checks).

## 2026-11-22 — keyboard focus regression review

**Changes:** Removed a CSS reset that suppressed the search input's keyboard-focus outline. Extended isolated Chromium tests to check selected focus outlines and their computed contrast, submit search and staff login with Enter, and exercise search, login and a private synthetic form under emulated forced colors and reduced motion. Missing and low-contrast outline regressions were observed to fail. No business logic, data or layout changes.

**Limits:** These checks cover selected controls and computed container colors only; emulation is not an OS/device, screen-reader or complete accessibility assessment. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — browser startup investigation and contrast review

**Changes:** Investigated intermittent local headless Chromium startup failures. The isolated SSR smoke test now uses software rendering without the bundled GPU/SwiftShader flags, retaining normal web security. A local about:blank launch experiment recorded 4/30 failures with previous flags and 0/130 with GPU disabled; no automatic retry was added. Added computed-color contrast checks for selected home-page text and placeholder against the gradient endpoints and input background; a deliberately low-contrast mutation failed as expected. No product data or public layout were changed.

**Limits:** This local experiment does not prove the crash's root cause or guarantee other environments; GPU/WebGL rendering is untested. Axe continues to report other inconclusive contrast items; manual, screen-reader and device evaluation remains necessary. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — focused accessibility and CSRF regression review

**Changes:** Expanded the isolated synthetic Chromium workflow to public product detail, logout, invalid-form error associations, missing-token rejection and keyboard skip navigation. Added automated axe WCAG-tagged checks on ten representative page states, corrected three reported contrast issues and the home-link accessible name, and added same-origin, hostile/null Origin and HTTPS Referer CSRF regression cases with valid tokens. No clinical or published data were added.

**Limits:** Axe reports inconclusive contrast items for manual review. The local headless Chromium process intermittently crashed at startup on this lean container; no automatic retries hide the failure. No complete WCAG, screen-reader, device or security assessment is claimed. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — isolated Chromium checks and staff CSRF fix

**Changes:** Added opt-in, isolated synthetic PostgreSQL/Chromium smoke checks in CI. Chromium revealed that the staff `no-referrer` policy generated `Origin: null` on form submission and caused Django's CSRF protection to reject real logins. Staff responses now use `same-origin`: form requests retain a valid Origin while cross-origin requests omit referrers. Existing private cache and indexing headers are unchanged.

**Limits:** Same-origin requests and logs can contain staff URLs; never use sensitive data. The browser runs without an OS sandbox in trusted test environments. A few viewports and keyboard assertions are not full accessibility, device, security or clinical validation. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — synthetic correction ancestry inspection

**Changes:** Added permission-scoped, read-only, bounded parent-path inspection for the four private identity draft types, with signed, graph-bound continuation cursors. Invalid graphs/links stop inspection without rendering their details. Added synthetic pagination, corruption, stale/expired cursor, role, privacy, bounded-query and data-isolation tests. No schema, review or public behavior changed.

**Limits:** The path is not a snapshot, completeness or authenticity proof; earlier pages are not rechecked and parallel branches are not traversed. Hashes can be recomputed and direct writers can race. No browser/accessibility, clinical, legal or production security validation. See [ADR 0015](ARCHITECTURE_DECISIONS/0015-synthetic-lineage-inspection.md).

## 2026-11-22 — synthetic ingredient, formulation and product corrections

**Changes:** Added typed private immediate-parent correction links and forms for synthetic ingredients, formulations and products, with branch support, graph preconditions, transactional creation, scoped link navigation and validation. Existing dependants and package reviews are not rewired or transferred. Added populated migration, rollback, permission/CSRF, corruption, pagination and concurrent PostgreSQL tests.

**Limits:** Links are unverified assertions, not equivalence, whole-ancestry validation, clinical approval or audit. Formulation corrections preserve ordered ingredients; product corrections preserve formulation. Bulk/SQL and non-cooperative writers bypass guards and locks; hashes are not signatures. No real data, public changes, browser/accessibility, clinical or production assessment. See [ADR 0014](ARCHITECTURE_DECISIONS/0014-synthetic-component-revisions.md).

## 2026-11-22 — synthetic package correction branches

**Changes:** Added an additive PostgreSQL migration for private immediate-parent package correction links, fixed-product child creation, separate reason and graph hashes, latest-review and graph stale checks, atomic creation, and independent branch support. Staff can create corrections and browse validated links in bounded pages; old records and reviews remain unchanged. Synthetic migration, rollback, malformed data, permissions, CSRF, conflict and two-connection race tests included.

**Limits:** These are asserted links, not equivalence, authenticity, ancestry-wide checks or approval. Reviews cover the new graph only, not revision provenance or the parent, and do not transfer. No ingredient/formulation/product corrections, public changes or source verification. Bulk/SQL bypass guards; hashes are not signatures. No browser, clinical, legal or production security validation. See [ADR 0013](ARCHITECTURE_DECISIONS/0013-synthetic-package-revisions.md).

## 2026-11-22 — formulation formset validation

**Changes:** Ensure even an empty or malformed formulation component formset is validated and its errors rendered. The create-only form requires its fixed five management slots with no initial forms, rejects duplicate ingredient IDs before the service, and offers a fresh-form link if no component forms were rendered. The service retains its own bounds and uniqueness checks; no schema or public behavior changed.

**Limits:** The form structure check is not an authenticity or source validation mechanism. Only synthetic input is allowed. No browser/accessibility, clinical or production assessment was performed. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — identity graph read and migration checks

**Changes:** Reconstruct each formulation and its ingredient snapshots from one joined component read, reusing the result throughout the graph rather than repeatedly reading it; staff package/product queries join their direct dependencies. Payload hashes and stored graph format are unchanged. Added synthetic compatibility, query-count, PostgreSQL constraint and populated 0004-to-0005 catalog migration tests.

**Limits:** One component statement is not an isolated graph snapshot, a lock against uncooperative writers, or a production performance benchmark. Migration tests do not replace backups or restore drills. No database schema or publication behavior changed. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — identity review history navigation

**Changes:** Replaced the 25-review history cutoff with bounded descending-ID pages scoped to the selected package. The review form appears only on the newest page and uses the latest review actually shown as its optimistic precondition. A stale submission requires a reload and reassessment. Existing permissions, privacy, snapshot checks and public isolation remain in place; no schema change.

**Limits:** Pages are not a database snapshot or tamper-proof audit. Uncooperative writes and out-of-order IDs can change results; query plans and large datasets were not benchmarked. Historical content remains synthetic and unverified. No browser/accessibility or production validation. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — identity review history interpretation

**Changes:** Made the private identity graph human-readable with explicit source/actor fields and links; validate stored review graph shape, links, hashes, quantities and reviewer separation before display. Consistent reviews are labeled current or historical, with an expandable historical snapshot; invalid current graphs suppress history rather than claiming none exists. No schema or public changes.

**Limits:** Coherent snapshots can be fabricated by a database writer, and reason, decision and time are not integrity-protected. Historical comparison does not prove a real change. Bulk/SQL bypass guards; reads are not snapshots. No browser/accessibility, medical or production validation. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — private synthetic identity drafts

**Changes:** Added a private, permission-scoped draft chain from ingredients through ordered formulation components and products to packages, with asserted sources and preliminary independent package review. Bounded staff pages, conflict checks, PostgreSQL migration and synthetic tests are included. Public catalog records and eligibility are unchanged.

**Limits:** A development prototype, not a comprehensive identity model, verified source, clinical approval, equivalence or publication workflow. Hashes are not signatures; bulk ORM/SQL bypass guards, direct writes can race, and only cooperative reviews are serialized. No real patient or proprietary data, browser/accessibility, medical or production validation. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — cross-batch indexed IRC clues

**Changes:** Added a private, permission-scoped indexed IRC inspection page and local command anchored on a presentation ID. Forward signed cursors paginate bounded indexed clues across the catalog; inconsistent indexes are flagged, anchor drift or cursor tampering stops inspection, and raw names/URLs/codes are not deliberately output.

**Limits:** This is not a complete catalog-wide duplicate audit: stale indexes can hide rows and concurrent changes make pages non-snapshot. Codes and cursors are not proof of identity, rights or confidentiality; no repair or publication occurs. No browser accessibility, medical or production validation was performed.

## 2026-11-22 — PostgreSQL staging concurrency

**Changes:** Product and price committed CSV stages now take a transaction-level advisory lock for the exact source URL and domain, including direct services, CLI and web receipts. Added PostgreSQL two-connection tests for reversed import order, lock waiting, rollback, preview, receipt integrity and concurrent clinical evidence/triage. No schema or publication behavior changed.

**Limits:** The lock is cooperative, may wait without an application timeout and can be bypassed by other writers. Different URL spellings are distinct; collisions can serialize unrelated imports. It does not protect catalog matching from concurrent insertion or establish exactly-once receipts, source rights, complete concurrency safety or production readiness.

## 2026-11-22 — PostgreSQL-only database

**Changes:** Configured Django and psycopg for PostgreSQL exclusively, introduced environment-based connection settings, PostgreSQL-backed CI and a development Compose stack with persistent volume and readiness checks. Existing Django migrations and models remain in place. Replaced former database-specific backup tooling with PostgreSQL-native dump/restore guidance. Added PostgreSQL integration and concurrent stale-review tests.

**Limits:** Development Compose is not production deployment; no production backup retention, independent security or load review exists. Database locks protect selected rows only; concurrency is not universally proven. Hosted CI and Docker availability depend on the environment.

## 2026-11-22 — read-only catalog quality inspection

**Changes:** Added a permission-scoped debug staff page and local JSON command for bounded ID-ordered product-presentation inspection. Reports flag projection drift, stricter source URL warnings, published rows rejected by technical filters, invalid text and page-local IRC duplicates; no field values, automatic repairs or publication changes. Added synthetic permission, drift, pagination, corruption and read-only tests.

**Limits:** Duplicate checks only cover one batch, and scans are not snapshots. Passing checks is not clinical, identity, rights or publication approval; stricter URL hygiene is advisory and does not change existing public eligibility. CLI and service are outside the web gate; no production monitoring, browser, security, source or clinical validation was performed.

## 2026-11-22 — development CI

Basic GitHub Actions checks were added; the current workflow uses a PostgreSQL service. The former database-specific local snapshot utility has been retired; PostgreSQL-native backup and restore guidance supersedes it.

## 2026-11-22 — supplementary clinical reference assertions

**Changes:** Added up to ten unverified supplementary reference assertions per draft version, explicit asserted relationship labels, deduplication, separate-recorder review separation, sequential evidence-set stale checks and bounded review snapshots. Staff can inspect historical snapshot metadata and see whether its fingerprint differs from the current set; old reviews are explicitly marked without a snapshot. Added synthetic tests for role separation, caps, corruption, migration and public exclusion.

**Limits:** Claimed relationships, citations, dates, licences and reviewer qualifications are not verified; no clinical approval or publication occurs. The set fingerprint includes recorder IDs but omits timestamps, and hashes are not signatures. The limit and stale checks are not concurrency or audit guarantees; bulk ORM/SQL bypass guards. No real evidence, browser accessibility, medical, legal or production validation was performed.

## 2026-11-22 — private synthetic clinical statement drafts

**Changes:** Added a development-only clinical draft domain with separate view/add/review permissions, a Persian RTL queue, asserted citation metadata, branched parent-linked versions and independent preliminary triage snapshots. Integrated separately permissioned exact-URL source-claim hints and clinical-only login navigation. Added synthetic role, CSRF, input, version, stale and corruption tests; there is no approval or publication action.

**Limits:** Drafts, references, dates and reviewer qualifications are unverified; the text field cannot enforce one statement and is not linked to a real drug. Immediate-parent checks do not certify full ancestry. No seed clinical content, licensed evidence, clinical approval or public presentation was added. Hashes omit actor/time and are not signatures; bulk ORM/SQL bypass guards, concurrent behavior and production security remain unproven. No browser, medical, legal or production validation was performed.

## 2026-11-22 — intake row outcomes and receipt navigation

**Changes:** New receipt-backed product and price imports atomically record bounded per-data-row outcomes linking to candidates, including duplicates, content fingerprints and request-time price suggestions. Receipt details validate structure and candidate consistency, paginate rows and hide inconsistent links. Candidate pages show capped, domain-scoped recent receipt clues. Existing receipts are explicitly marked as lacking row details; no backfill is invented. Added synthetic rollback, permissions, corruption, replay, constraints and migration tests.

**Limits:** No raw file or file-level hash is kept; this cannot prove original contents, source permission or immutable audit. Hashes are not signatures and price payload hashes omit source URLs. CLI/direct imports, preview, failures and older receipts remain outside row manifests. FKs protect ordinary deletion, but bulk ORM/SQL bypass guards; retention and production concurrency/crash behavior are unresolved. No source, clinical, browser or production validation was performed.

## 2026-11-22 — web intake receipts

**Changes:** Added minimal successful-web-stage receipts for product/price CSV imports, written transactionally with candidates, plus permission-filtered Persian list/detail pages and links from uploads and queues. Stored counts distinguish created and duplicate rows; price match counts include duplicates and reflect that request's catalog. Added count constraints and synthetic rollback, permission, replay, CSRF and pagination tests.

**Limits:** Receipts are not source-rights proof, verified data, complete logs, batch manifests or immutable audit. No raw file, filename, file hash or row membership is retained; previews, failures, older imports and CLI/direct imports are absent. Replays create new receipts, without request idempotency. Model guards can be bypassed with bulk ORM/SQL, and concurrency/crash behavior and production security are unproven. No source, clinical, browser or production validation was performed.

## 2026-11-22 — offline ingestion-window inspection and input hardening

**Changes:** Added a pure offline current/next window calculator with configurable per-call IANA timezone and local HH:MM boundaries, default Tehran 23:00–01:00, a JSON management command and a permission-gated Persian debug-only staff view. Rejects ambiguous/nonexistent local boundaries and converts to UTC using timezone rules. Shared validators now reject unsafe source URL edge cases and invalid review text across product, price and source workflows. Added synthetic timezone, permission and validation tests.

**Limits:** No persisted schedule, scheduler, worker, rights check, network collection or publication. Clock and IANA data must be maintained; an open interval is not authorization or evidence of a run. Existing candidate records with newly invalid URLs fail review and require investigation, not silent rewriting. No concurrency, browser accessibility, penetration, source-rights or production testing.

## 2026-11-22 — source assertions and independent preliminary triage

**Changes:** Added a development-only internal ledger of source-rights assertions with explicit scopes, owner, evidence URL, claimed dates, recorder, duplicate detection and a separate preliminary reviewer. Added a paginated/filterable Persian staff queue and exact-URL, permission-gated, capped links from product and price candidate details. Validation and synthetic tests cover access boundaries, CSRF, sequential conflicts and integrity, date labels and no public writes.

**Limits:** Claims, evidence, dates and triage are unverified and do not authorize or gate intake, source use, crawling or publication. Source hints are not part of candidate review snapshots. Fingerprints omit actor/time and are not signatures; bulk ORM/SQL can bypass model guards; concurrency is unproven. Only synthetic local testing, not legal/source verification, browser accessibility, penetration or production testing.

## 2026-11-22 — price revision triage and safer suggestions

**Changes:** Added a staff price-queue filter for the latest preliminary review, combinable with the original match-status filter. Detail pages show up to 10 same-source/ID revisions and a conditional exact whole-Rial difference only when source name, unit/category and nonempty normalized identity fields match. Dates and original currencies remain explicit; no price or trend is approved/published. Hardened matching against invalid/normalization-empty identifiers and conservatively marks more than 100 same-IRC indexed presentations ambiguous. Malformed Unicode in stored JSON is not rendered as valid staff data. All 99 Django tests, system/migration checks, pip check and a synthetic price CSV dry run passed.

**Limits:** Comparisons are advisory and not captured/rechecked on review; normalized identity does not prove equivalence or rights, and the source URL is outside the existing price payload hash. Existing invalid rows fail current validation, but are not automatically corrected. DB work, stale indexes, concurrency, immutability and production security remain unresolved. No clinical/source verification, real data, browser/accessibility, penetration or production testing. Previous entries are historical snapshots.

## 2026-11-22 — advisory product comparisons

**Changes:** Added normalized candidate IRC index with historical backfill and controlled staging population; inconsistent indexes fail closed for preliminary review. Staff product details now show bounded source-record revision differences and normalized IRC comparison clues for other private candidates and eligible public presentations. The view explicitly excludes catalog drafts and warns about truncation, normalization uncertainty and absent IRC. No automatic match, merge or publication is performed. The full 85-test Django suite, historical migration test, local migration, system/migration checks and pip check passed.

**Limits:** Clues can be incomplete or stale, are neither identity nor rights verification, and are not snapshotted or rechecked on review. Bulk ORM/direct SQL can bypass index maintenance; production concurrency remains untested. Application row caps do not bound DB scan/sort costs. No real source data, clinical validation, browser/accessibility, penetration or production testing. Previous entries are historical snapshots.

## 2026-11-22 — private product candidate intake and triage

**Changes:** Added a separate development-only product candidate model, CSV preview/staging with explicit internal-storage attestation, submitter provenance and revision deduplication. Added Persian RTL queue, latest-review filtering, independent preliminary review and snapshot history with separate permissions. Product candidates never create or publish a catalog product. Added a fully synthetic CSV example and workflow/security tests. Local migrations, all 78 Django tests, system/migration checks and pip check passed.

**Limits:** Source rights and identity are not verified; reviews are triage only and no final approval, matching, clinical content or publication is implemented. Hashes are not signatures; bulk ORM/SQL can alter snapshots and row locking alone cannot guarantee all concurrent workflow correctness. Debug/preview, upload buffering and incomplete production controls make this suitable only for synthetic development data. No browser, penetration, concurrency or production test was performed. Previous entries are historical snapshots.

## 2026-11-22 — forward search pagination and API contract

**Changes:** Search and API now use query-bound, signed, expiring forward cursors, with a 30-result page limit and up to 150 validated candidates per request plus one lookahead. Empty pages can continue past ineligible rows. Persian UI includes continuation, clear empty and stale-cursor states. Added a bundled OpenAPI 3.0.3 document for actual public endpoints at `/api/v1/openapi.json` and automated response-shape checks. All 63 Django tests, checks, dependency checks and OpenAPI validator 0.7.2 passed; local HTTP smoke checks also passed.

**Limits:** Pagination is not snapshot-consistent; changes can skip/duplicate results or invalidate the anchor. Cursor signatures do not encrypt IDs and do not replace authorization; queries and tokens can appear in logs. the database may scan/sort more rows than the application validation limit; no public rate limiting or production load/security assessment. Source rights, clinical/price approval and real data remain absent. No browser or accessibility-device test was performed. Previous entries are historical snapshots.

## 2026-11-22 — presentation details and safer public reads

**Changes:** Added Persian RTL `/products/<id>/` and read-only `/api/v1/products/<id>/` with source, recorded review time, exact presentation fields and explicit clinical/price limitations. Search links to details; both surfaces share bounded eligibility checks, avoid invalid source URLs with embedded credentials, and omit drafts. Search inspects at most 150 candidates and returns at most 30; it cannot claim completeness. Missing, unpublished and invalid items produce the same generic 404; detail responses are noindex/no-store and excluded from the sitemap. Removed unsupported confirmation wording from the home page. Synthetic tests cover the contract and defensive cases. The full 51-test Django suite, system check, migration drift check and pip check passed; local HTTP smoke checks returned the expected search and missing-item responses.

**Limits:** Product flags and timestamps are not clinical approval or source-rights evidence; bulk database writes may bypass validation and make indexes stale. No real product data, browser/device accessibility test, security assessment or production deployment performed. Previous entries are historical snapshots.

## 2026-11-22 — development-only price staging and preliminary review

**Changes:** Added permission-gated CSV upload with preview or attested staging, authenticated submitter provenance, and a separate preliminary review permission. A different reviewer can record reasoned acceptance of a current unique match, rejection, or deferral. Records include a source snapshot and product fingerprint; sequential stale forms and inconsistent payloads fail closed. Existing/CLI candidates without a submitter cannot be reviewed here. No review publishes or approves prices. Added migrations, Persian UI and synthetic workflow tests. The full 45-test Django suite, local migration/check, migration drift check and pip check passed.

**Limits:** Source permission is only asserted; no real sources or prices were loaded. Review history is not database-immutable; direct SQL/bulk ORM bypass model guards, and the hash is not a signature. Matching can race with catalog changes without a stronger concurrency design. The staff portal remains debug-only and is not production-ready. No browser, penetration, concurrency or clinical validation was performed. Previous entries are historical snapshots.

## 2026-11-22 — development-only read-only staff queue

**Previous state:** staged price candidates were inspectable only by a local CLI; there was no session-based web access.

**Changes:** enabled Django auth and sessions; added a Persian RTL login and read-only candidate queue/detail views with scoped `pricing.view_pricecandidate` checks, status filtering, pagination and current match recalculation. Added private/no-store/noindex response headers, CSRF-protected POST logout and a hard feature gate disabling all `/staff/` endpoints outside debug mode. No accounts or passwords are seeded. Files: `daroobank/settings.py`, `daroobank/middleware.py`, `daroobank/urls.py`, `pricing/staff_views.py`, `templates/staff/`, `static/css/staff.css`, `pricing/test_staff.py` and documentation.

**Verification:** 23 existing tests passed before changes; 32 total tests passed after changes, including access control, CSRF, open redirect, escaped data, no-store, pagination and disabled-mode checks. Local Django auth/session migrations and HTTP checks were run. No external or production systems were tested. Browser/responsive accessibility tests and a penetration test were not performed.

**Limitations:** development-only; no MFA, login throttling, audited identity management, review decisions, protected approval/publishing, clinical validation or production deployment. No real source data was loaded. Debug mode and public preview URLs are unsuitable for real or sensitive data. All previous changelog entries are historical snapshots.

## 2026-11-22 — review-only price candidate staging

**Previous state:** the development application had no price ingestion or staging. It had an IRC search projection that could become inconsistent on partial model saves.

**Changes:** added an independent `pricing` Django app and migration; bounded, full-file-validated local CSV staging with explicit currency and exact Rial conversion; provenance and deduplicated candidate revisions; strict, review-only package suggestions; dry-run-by-default CLI and bounded, read-only local candidate listing. Improved and backfilled the normalized IRC index and synchronized derived search fields on partial saves. Files: `pricing/`, `catalog/models.py`, `catalog/migrations/0002_productpresentation_irc_normalized.py`, `examples/price_candidates.synthetic.csv`, settings and documentation.

**Verification:** the original 12 tests passed before changes; after changes 23 tests passed, including synthetic imports, mismatch/ambiguity, idempotency, exact conversion, rejected files and no public prices. Local migrations and a synthetic dry run were executed successfully. The example produced two unmatched records and stored none. Django system and migration checks are run separately in the final verification. No real data, source permission, clinical validation, network crawling, publication or production deployment was involved.

**Limitations:** candidates, permissions and matches are not independently verified; no authenticated admin, audit, approval, immutable database enforcement, scheduler, production data or public price/history exists. CSV storage is allowed only with appropriate rights. The initial suggestion may become stale; the listing recalculates a current suggestion but never approves it.

## 2026-11-22 — first development vertical slice

**Previous state:** repository contained architecture and research documentation only; no application, tests, database or UI existed. The prior documentation was preserved.

**Changes:**
- Added a Django 5.2 development application with migrations, `ProductPresentation`, bounded server-side Persian/Arabic/English/digit-normalized search, publication/source/date filtering, and a read-only `/api/v1/search/`. Files: `daroobank/`, `catalog/`, `manage.py`, `requirements.txt`.
- Added shared Persian RTL pages, local licensed font, responsive design tokens, honest empty/coming-soon states, no invented prices or clinical claims. Files: `templates/`, `static/`, [design system](DESIGN_SYSTEM.md).
- Added per-page metadata, home/about canonical URLs, sitemap, robots and noindex search/price pages. Website JSON-LD is descriptive, not a ranking guarantee. Files: `catalog/views.py`, `templates/base.html`.
- Added query bounding, HTML escaping, safe HTTPS source validation, GET-only views, no-store/no-referrer search responses, and a development-versus-production host/secret distinction. `ProductPresentation` does not implement reviewer approvals, audit, database-level tamper prevention or a full source-rights system; direct ORM/bulk writes can bypass model validation. Do not expose write access or treat the published flag as a governance workflow.
- Documented source usage and remaining gaps in [resource review](RESOURCE_REVIEW.md), [architecture](SYSTEM_ARCHITECTURE.md), [API](API_DESIGN.md), [security](SECURITY.md) and other existing docs.

**Verification:** `manage.py test` (12 tests), `manage.py check`, `manage.py makemigrations --check --dry-run` and local HTTP requests were run successfully. One initially incorrect test asserted that the echoed query was absent rather than inspecting results; corrected and rerun. `pip check` found no broken requirements. A 50-request single-client local empty-database development-server search smoke test measured median 8.70 ms and p95 10.52 ms; this is not representative of production or a browser performance benchmark. Django deployment checks initially found missing HSTS, HTTPS redirect and secure CSRF settings; redirect and secure cookies were added for non-debug mode, while HSTS remains deliberately unset pending a TLS/deployment policy. A browser test was attempted using temporary Playwright/Chromium, but Chromium could not start because `libnspr4.so` was unavailable; no browser, responsive-device or screen-reader test was completed. No representative load, vulnerability scanner, crawler or production tests were run. No external sites were security tested.

**Limits:** No production configuration or security sign-off; no user accounts, administration, pricing, provenance/review workflow, full relational drug model, interactions, crawler, consultation or AI. At that stage search used substring matching with a 30-result cap and no pagination, inappropriate for a large production catalog. Source records and verification flags require a future properly authorized workflow. Product identity and price publication are deliberately not automated. GET search terms can appear in server/access logs; avoid entering personal health details and implement log redaction before production.
