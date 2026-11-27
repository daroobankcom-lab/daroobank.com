# The backup and recovery plan, and what a restore in this repository actually proves

`docs/DEVELOPMENT_GUIDE.md` says *"PostgreSQL's `pg_dump` and `pg_restore` are external client
utilities, not an application backup service"*, that dumps *"contain all user data, password hashes,
sessions and other private information, are unencrypted by default and are not committed"*, and ends
with *"A volume alone is not a backup."* `docs/OPERATIONS_RUNBOOK.md` has a `## Restore and recovery`
section that asks an operator to *"define ownership, encrypted backup cadence, off-host retention,
RPO/RTO and recovery environment"*, says *"no values have been approved"*, asks them to *"Record
actual restore duration and recovery point"*, and a `## Local synthetic restore drill` section whose
central rule is *"never restore into the running database"*.
`docs/PHASE1_RELEASE_EVIDENCE.md` carries the whole subject as an open gate: *"encrypted off-site
backups, independent key custody, access control, retention, integrity and anti-replay/freshness
policy, recovery objectives, scheduled isolated restore drills and documented owner."*
`docs/SECURITY.md` assigns *"Operate backups and database"* to a database administrator role that
does not exist here, and [ADR 0225](ARCHITECTURE_DECISIONS/0225-populated-rollback-drill.md) ends
with *"Identity sequences are part of any restore."*

So the repository has a documented drill, two opt-in CI drills and an explicit prohibition — and no
answer to the three questions a restore actually raises: **is this the right archive, whose keys open
it, and which database does it go into?**
[ADR 0232](ARCHITECTURE_DECISIONS/0232-backup-recovery-plan.md) records what this document says and
what it measures. It is not a backup service, not a recovery objective, not a custody arrangement and
not an approved procedure.

This document is a **proposal**. It has no owner and no approval, so it must not be read as a
decision, and it must not treat a synthetic drill that restores into a fresh database as a recovery
capability. Its prices are counted from the pins and files below, not prototyped: no backup control
was implemented and reverted, so no cascade of pin failures was run — but the replay experiment
**was** performed, on synthetic data in throwaway databases, and every number below is the result of
that run.

**Nothing is implemented.** No backup record, no manifest, no custodian, no schedule, no `--clean` in
any documented sequence, no new command and no new dependency exists in this tree because of this
file. The replay was performed with the client tools the drills already use, on databases that no
longer exist.

## What is true today, measured

Counted on this tree by reading the documents, the workflow and the two drill suites, and by running
the replay experiment against the synthetic PostgreSQL 16.2 server with the `pg_dump`, `pg_restore`
and `createdb` clients the `pgserver` wheel bundles. They are pinned by
`daroobank/test_backup_recovery_plan.py`.

### The documented restore path

* **Six steps, and the second one throws away the only metadata the archive carries.** The guide's
  script is pinned step by step by `daroobank/test_backup_guide.py` (7 tests, fake binaries, no
  database) as `dump, list, createdb, restore, migrate, check`. Its listing step is
  `pg_restore --list --no-password -- "$SYNTHETIC_DUMP_FILE" > /dev/null`, so the header that names
  the archive's creation time and its source database is discarded.
* **The drill captures that header and never reads it.** `daroobank/test_synthetic_restore.py` runs
  the same listing and asserts exactly one thing about it —
  `self.assertEqual(listed.returncode, 0, 'Synthetic archive listing failed')`. The string
  `listed.stdout` appears nowhere in the file.
* **The target is always a database that does not exist yet.** The guide runs
  `createdb --no-password daroobank_restore_drill` and then retargets `POSTGRES_DB` to that literal
  name twice, for `manage.py migrate --check` and `manage.py check`. The drill's class docstring says
  *"Source and target are new, dedicated databases, never an existing database"*, it only ever drops
  the database it created, and `test_target_name_collision_is_not_dropped` pins that an existing
  target is refused rather than replaced. The runbook states the rule as *"never restore into the
  running database"*.
* **No live-database recovery shape is written down anywhere.** The guide's script contains no
  `--clean`, no `--if-exists`, no `--create`, no `dropdb` and no `DROP DATABASE`, and of the 264
  markdown documents in `docs/` the only two that name any of them are this plan and
  [its decision record](ARCHITECTURE_DECISIONS/0232-backup-recovery-plan.md).
* **The dump is taken with `--no-owner --no-acl`.** The archive's header counts `TOC Entries: 291`
  and its listing prints 287 selected entries — 33 `TABLE`, 33 `TABLE DATA`, 60 `INDEX`,
  30 `SEQUENCE` and 30 `SEQUENCE SET`, 51 `CONSTRAINT` and 50 `FK CONSTRAINT` — and among them
  **zero** carry an ACL, an OWNER or a GRANT: a restore brings back 33 tables and no privileges, and
  nothing in the guide, the runbook or the drill says who re-grants them. The 50 foreign-key
  constraints match the 50 foreign keys `manage.py inspect_postgresql_schema` counts.
* **A dump is a credential store.** Four of those 33 `TABLE DATA` entries are `auth_user`,
  `auth_user_groups`, `auth_user_user_permissions` and `django_session`, so one 136,001-byte file
  holds every password hash and every live session row. The guide's protections are `umask 077`, an
  absolute-path requirement and `set -C`, which refuses to overwrite an existing archive; the drill's
  measured file mode is `0600` inside a `0700` directory.

### The replay, measured on synthetic databases

One synthetic identity fixture (2 accounts, 1 package, 1 review, a cross-domain fixture across the
24 project models) was dumped, one later business fact was written, the database was dumped again,
and the **older** archive was restored into a fresh database. Then every check the drill runs was run
against it.

* **The two archives are distinguishable only by their bytes.** The stale one is 136,001 bytes and
  the fresh one 136,541, and they are not byte-identical — but both listings print
  `; Archive created at 2026-11-26 23:37:44 UTC`, because the stamp has one-second resolution and the
  two dumps took 0.071 s and 0.053 s. Nothing else in the header differs, since both name the same
  source `dbname`.
* **The stale archive restores silently and completely.** `pg_restore --no-password --exit-on-error
  --single-transaction --no-owner --no-acl --dbname <target> -- <archive>` exited 0 in 0.163 s and
  printed **0 bytes** on stdout and stderr. The target held 33 public tables, 32 applied migrations,
  2 accounts, 0 sessions, 1 package and 1 review — the later fact (package 2, review 2) was simply
  absent, while the source still had 2 and 2.
* **Every existing verification passed on the stale archive.** `manage.py check` (0.433 s),
  `manage.py migrate --check` (0.436 s), `manage.py inspect_postgresql_schema` (0.481 s) and the
  drill's ORM verification — `verify_identity_fixture`, `verify_cross_domain_fixture` and
  `verify_post_restore_writes` — all exited 0 (0.372 s, 0.390 s, 0.388 s and 0.522 s, 1.673 s in
  total) with empty stderr. They verify a fixture the same process wrote before the dump, so an
  archive missing everything written afterwards is indistinguishable from a current one.
* **Restoring over a populated database is not a supported shape, and the alternative is
  undocumented.** A second `pg_restore` of the same archive into the already-restored target exited 1
  in 0.006 s with `ERROR:  relation "auth_group" already exists` on the very first `CREATE TABLE`.
  Adding `--clean --if-exists` made the same command exit 0 in 0.209 s with empty stderr, left 33
  tables, 1 package, 1 review, 2 accounts and 32 applied migrations, and `manage.py check` (0.337 s)
  and `manage.py migrate --check` (0.370 s) both passed — so the mechanical shape of a
  live-database recovery works and is named in no document.
* **These are the only restore durations the repository has.** For a 33-table, 32-migration,
  two-account synthetic fixture: dump 0.071 s, listing 0.003 s, restore 0.163 s, and 1.673 s for the
  four verification commands. The runbook asks for *"actual restore duration and recovery point"*;
  no other number exists, and a fixture is not a volume.

### The envelope, the clients and the custody

* **The encrypted drill mints its own keys and destroys them.**
  `daroobank/test_synthetic_encrypted_restore.py` runs
  `openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=synthetic-only` for two recipient
  key/certificate pairs, `openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048` for a signing
  key and `openssl pkey -pubout` for its public half, encrypts with
  `openssl cms -encrypt -binary -aes-256-gcm -outform DER`, signs and verifies with
  `openssl dgst -sha256 -sign`/`-verify`, and decrypts with `openssl cms -decrypt`. Every file is
  created `O_WRONLY|O_CREAT|O_EXCL` with mode `0600` inside a `tempfile.TemporaryDirectory` of mode
  `0700`, and the directory is destroyed at the end of the test.
* **No custodian exists anywhere.** `.github/workflows/checks.yml` references **zero** `secrets.*`
  expressions, no key file is committed, no passphrase variable is read by `daroobank/settings.py`,
  and the recipient certificate is self-signed and valid for one day. The drill therefore proves that
  an authenticated envelope can be opened by a holder of the key and not by another holder — and
  proves nothing about who holds a real one. That is the *"independent key custody"* the release
  evidence lists as open, and it is the same question
  [the secret-rotation plan](SECRET_ROTATION_PLAN.md) leaves open for `DAROOBANK_SECRET_KEY`.
* **The client tools are not part of the repository.** No `pg_dump` is installed on this machine
  outside the virtual environment: the only one is the `pgserver` wheel's bundled 16.2 binary at
  `.venv/lib/python3.11/site-packages/pgserver/pginstall/bin/pg_dump`, which matches the synthetic
  server's 16.2. CI does not install a client either — it writes two wrapper scripts that run
  `docker run --rm --network host … postgres:16 … pg_dump`, and that tag is one of the four mutable
  base-image references [ADR 0226](ARCHITECTURE_DECISIONS/0226-ci-artifact-gate.md) measured, so the
  client version a drill uses can change without a commit. `postgres:16` is referenced three times —
  the workflow's service image, the client shim and compose — and `python:3.11-slim` once, which is
  the four mutable references ADR 0226 counted.
* **The drills do not run by default.** Four suites are gated on opt-in environment switches —
  `DAROOBANK_RESTORE_TESTS` (5 tests), `DAROOBANK_ENCRYPTED_RESTORE_TESTS` (2),
  `DAROOBANK_BROWSER_TESTS` (1) and `DAROOBANK_SEARCH_BENCHMARK` (1) — which is 9 of the 10 skips an
  ordinary run reports; the tenth is the replay test in this plan's own suite, gated on the same
  switch as the drill and on a `pg_dump` being on `PATH`. Put the bundled clients on `PATH` and set the two restore switches, and all 16 of
  those tests pass locally in 23.8 s against the synthetic server and leave no database behind.
* **Nothing records a dump or a restore.** `LOGGING` is `{}`, no application module imports
  `logging` — the only importer in the tree is `daroobank/test_secret_rotation_plan.py`, which
  measures the absence of handlers — no
  model among the 24 is named like a backup, dump, archive, restore or recovery record, `pg_restore`
  printed 0 bytes, and the runbook's instruction is that a human *"Record the outcome without
  sensitive details"*. [ADR 0221](ARCHITECTURE_DECISIONS/0221-no-read-audit.md) measured the same
  absence for reads.

### What the repository already says about it

* `docs/DEVELOPMENT_GUIDE.md`: *"Use a client version at least as new as the server; access must be
  restricted and authorized"* and *"Choose a trusted private location, encrypt and retain according
  to policy, and test restoration separately."*
* `docs/OPERATIONS_RUNBOOK.md`: *"Test restoring database and authorized objects together,
  permissions, audit integrity, point-in-time consistency and application compatibility"* — the
  "authorized objects" and "permissions" halves are exactly what `--no-owner --no-acl` drops.
* `docs/OPERATIONS_RUNBOOK.md`: *"These steps are not a production restore exercise; no cadence,
  encryption, off-host retention, recovery objectives, alerting, external asset recovery or
  production access controls are implemented."*
* `docs/PHASE1_RELEASE_EVIDENCE.md`: *"The synthetic test is not an operating backup service."*

## Candidate approach and decisions required

The measured starting point is a six-step drill into a fresh database, an archive that names its own
creation time and source in a header both the guide and the drill discard, 287 table-of-contents
entries with no privilege among them, an envelope whose keys are minted and destroyed by the test
that uses them, client tools that come from a mutable image tag, and no record of any of it.
Everything below is contingent on the decisions it names, and none of them is answered here.

1. **What are the recovery objectives, and who approves them?** The runbook asks for RPO and RTO and
   says *"no values have been approved"*. The only durations in the repository are 0.071 s to dump and
   0.163 s to restore a two-account fixture.
2. **How is the right archive chosen?** The archive's own stamp has one-second resolution, is
   discarded by the guide and is unread by the drill, so two dumps of the same database in the same
   second are indistinguishable by anything except their bytes.
3. **Who holds the envelope key and the signing key, and how is that separate from whoever runs the
   restore?** Today both are generated by the test, live for one day in a temporary directory and are
   destroyed with it, and the workflow holds no secret at all.
4. **What is a restore of the database the application uses?** The only documented shape creates a
   new database; the runbook forbids restoring into the running one; restoring over a populated
   database fails on the first existing relation unless `--clean --if-exists` is added, which no
   document names.
5. **Who re-grants privileges after a `--no-owner --no-acl` restore, and how is that verified?** Zero
   of the 287 TOC entries carry an ACL, an owner or a grant, and the drill's post-restore checks are
   `manage.py check`, `migrate --check`, a schema inspection and an ORM fixture verification — none of
   which tests a privilege.
6. **What is recorded about a dump and a restore?** The application records nothing, the restore
   prints nothing, and no artifact survives except the archive itself.
7. **How are dumps retained, moved off-host and protected?** One file, mode `0600`, in a directory of
   mode `0700`, holding every password hash and session row, with `set -C` as the only overwrite
   protection and no checksum, no retention and no off-host step.
8. **What makes a restore complete rather than consistent?** The drill verifies a fixture written by
   the same process that dumped it, so an archive that is missing every later fact passes all four
   verifications — measured, not argued.

## Options and what each costs

Prices are counted from the pins and files above, not prototyped.

| Option | What changes | Price, counted | What it still does not answer |
| --- | --- | --- | --- |
| **A. Leave the restore path as documented** | nothing | 0 code files, 0 commands, 0 settings, 0 schema pins and 0 lock lines move; the guide's six-step trace, the runbook's *"never restore into the running database"* and the drill's new-database policy stay as they are | whether a drill that cannot detect a stale archive, a missing privilege or a lost later fact is the recovery evidence the open gate asks for |
| **B. Read the archive's own header before restoring** | the guide's script keeps the `pg_restore --list` output instead of discarding it, and compares its `Archive created at` stamp and `dbname` line with a value the operator states | `daroobank/test_backup_guide.py`'s pinned trace `['dump', 'list', 'createdb', 'restore', 'migrate', 'check']` and its fake-binary harness (7 tests) move, the drill starts reading `listed.stdout` (0 readers today), and the guide's `> /dev/null` — which this plan quotes — disappears | decisions 1 and 2: what stamp is acceptable, and what to do when two archives share one |
| **C. Record every dump and restore in the database** | one append-only model, its migration, and a row written by the drill and by any real procedure | project migration modules 17 → 18, applied migrations 32 → 33 and schema tables 33 → 34, against the pinned 279 columns, 111 indexes, 138 constraints and 50 foreign keys of today — the read-audit prototype of ADR 0221 reached 283 columns and 113 indexes without adding a table — and the pinned inventories in `daroobank/test_no_read_audit.py` (its exact 33-name `SCHEMA_TABLES` tuple), `daroobank/test_actor_attribution_inventory.py` (19 attributed of 24 models, 5 named unattributed), `daroobank/test_mfa_implementation_plan.py` and `daroobank/test_read_audit_plan.py` (both `CURRENT_SCHEMA`), `daroobank/test_populated_rollback_drill.py` (31 rows across 24 tables), the restore drill's relation counts and the schema sentence in `docs/PHASE1_RELEASE_EVIDENCE.md` all move | decision 6's harder half: a record inside the database is replaced by the restore it describes, and who may write it |
| **D. Put the envelope keys in a custodian outside the repository** | the recipient certificate and the signing key come from a secret store or KMS instead of `openssl req` inside the test | the workflow's first `secrets.*` reference (0 today) against the shape `daroobank/test_ci_artifact_gate.py` pins (2 jobs, 22 steps, 17 `run:` steps, 5 action references pinned to 40-character SHAs, `contents: read`), `daroobank/test_synthetic_encrypted_restore.py` (225 lines) stops minting its own keys, `daroobank/test_synthetic_restore_guard.py` (9 tests) gains a custody guard, a key-rotation decision from [the secret-rotation plan](SECRET_ROTATION_PLAN.md), and a failure mode for an unreachable custodian that nothing in the tree has | who holds the custodian's own credentials, and decisions 1, 2 and 6 unchanged |
| **E. Document and drill the live-database shape** | the recovery path for the database the application actually uses is written down — `--clean --if-exists`, or drop and recreate — and drilled | the runbook's *"never restore into the running database"*, the drill's *"never an existing database"* policy and `test_target_name_collision_is_not_dropped` are contradicted and must be rewritten, the guide's `set -C` noclobber step and its six-step trace change, a drill that may destroy a database needs a new isolation argument in `daroobank/isolated_test_runner.py` and `restore_test_settings.py`, and `daroobank/test_backup_guide.py` re-pins the whole sequence | decisions 1, 4 and 5: authorization, downtime, and who re-grants the privileges `--no-acl` dropped |
| **F. Verify completeness against a manifest instead of a self-written fixture** | the dump step writes a manifest — table list, row counts, a checksum of the archive — and the restore step compares the restored database with it | a second artifact with its own custody beside the archive, `daroobank/synthetic_restore_fixture.py` (230 lines) and its three verifiers gain a manifest argument, `daroobank/test_synthetic_restore.py` (315 lines, 5 tests) and `daroobank/test_synthetic_restore_guard.py` (9 tests) move, the guide's script grows a step, and the workflow's ten fixed `::error::` annotations — six of them in the restore step alone — may need an eleventh category | a manifest written at the same moment as a stale dump certifies the stale dump, so decisions 1 and 2 stay open |
| **G. Declare backup and recovery out of Phase 1 scope** | `docs/SECURITY.md`, `docs/DEVELOPMENT_GUIDE.md`, both `docs/OPERATIONS_RUNBOOK.md` restore sections and `docs/PHASE1_RELEASE_EVIDENCE.md` stop asking for a recovery capability and say what is accepted instead | 4 documents reworded, the guide's script and its 7-test harness stay but lose their claim to be a drill, `daroobank/test_backup_guide.py` and `daroobank/test_ci_artifact_gate.py` re-pin the wording they quote, and ADR 0225's consequence that *"Identity sequences are part of any restore"* becomes the whole statement | whether an operator told to *"Test restoring database and authorized objects together"* may do it at all, which is a decision for an owner and not for this file |

## Required behavior before any restore

1. **Establish recency out of band.** The archive's own stamp is one-second resolution, is discarded
   by the documented sequence and is unread by the drill, and two dumps taken 0.07 s apart carried the
   same stamp in the measured run.
2. **Read the listing instead of throwing it away.** It is the only place the archive states when it
   was taken, from which database, in which format, with which client and server versions — a
   fifteen-line comment header whose ten field lines cost 0.003 s to print and whose stamp has
   one-second resolution.
3. **Expect no privileges to come back.** `--no-owner --no-acl` leaves 0 ACL, OWNER or GRANT entries
   among 287, so name who re-grants access to the restored database and how that is checked; the
   runbook already asks for *"authorized objects together, permissions"* and nothing tests either.
4. **Treat the archive as a credential store.** It holds `auth_user` and `django_session` table data —
   every password hash and every live session row — in one file whose only measured protections are
   mode `0600`, a `0700` directory and `set -C`.
5. **Decide the target shape before the incident.** A new database is the only documented and drilled
   shape; restoring over a populated one fails on the first existing relation, and the flag pair that
   makes it succeed appears in no document except this plan and its decision record.
6. **Record the dump and the restore somewhere that survives them.** The application records nothing,
   `pg_restore` printed 0 bytes, and the only surviving artifact is the archive itself.
7. **Verify completeness, not consistency.** A fixture written by the process that dumped it cannot
   detect a missing later fact: the measured stale restore passed all four verifications while one
   package and one review were absent.

## Verification before any enablement

- Repeat the replay experiment on synthetic data in throwaway databases and re-measure every number
  in this document: both archives' sizes and stamps, the TOC entry and kind counts, the absence of
  ACL entries, the stale restore's exit status, duration and empty output, the restored target's
  table, migration, account, package and review counts, the four verification exit statuses, the
  second restore's failure and the `--clean --if-exists` restore's success.
- Confirm that the drill's verifications pass on an archive that is missing a fact written after it,
  and that nothing else in the tree notices.
- Confirm that the envelope drill still mints and destroys its own keys, that the workflow still
  references no secret, and that no key file is committed.
- Confirm that the client tools still come from outside the repository, and record which version
  produced any archive that is kept.
- Verify that no model, command, setting, document or workflow step this plan names as absent has
  appeared, and that the counts in `daroobank/test_backup_recovery_plan.py` are recomputed rather than
  deleted if a chosen option lands.
- Record named owners and evidence for operational, security and release approval. No production
  enablement, no recovery objective, no claim of Phase 1 completion and no backup certification
  follows from implementing these tests.
