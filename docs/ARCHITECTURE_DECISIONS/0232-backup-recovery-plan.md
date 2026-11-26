# 0232 — the backup and recovery plan, and what a restore in this repository proves

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_backup_recovery_plan.py` (24 tests, ~0.6 s, of which 1 is an opt-in replay on
a synthetic database and takes ~5 s more)

## Context

Five documents ask for backup and recovery and the repository answers with one drill that restores an
archive into a database that did not exist before.
[DEVELOPMENT_GUIDE.md](../DEVELOPMENT_GUIDE.md) carries the whole procedure: *"PostgreSQL's `pg_dump`
and `pg_restore` are external client utilities, not an application backup service"*, dumps *"contain
all user data, password hashes, sessions and other private information, are unencrypted by default and
are not committed"*, and *"A volume alone is not a backup."*
[OPERATIONS_RUNBOOK.md](../OPERATIONS_RUNBOOK.md) asks an operator to *"define ownership, encrypted
backup cadence, off-host retention, RPO/RTO and recovery environment"*, says *"no values have been
approved"*, asks them to *"Record actual restore duration and recovery point"*, and then forbids the
one thing an incident would require: *"never restore into the running database"*.
[PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) carries the subject as an open gate:
*"encrypted off-site backups, independent key custody, access control, retention, integrity and
anti-replay/freshness policy, recovery objectives, scheduled isolated restore drills and documented
owner."* [SECURITY.md](../SECURITY.md) assigns *"Operate backups and database"* to a database
administrator role that does not exist here, and
[ADR 0225](0225-populated-rollback-drill.md) ends with the one consequence anyone had measured:
*"Identity sequences are part of any restore."*

So the drill exists, is exercised twice in CI under opt-in switches, and answers a narrower question
than the gate asks. It proves that an archive this process just wrote can be read back into a fresh
database. It does not prove that the archive is the right one, that anyone outside the process can
open it, that privileges come back with the data, or that there is any shape at all for recovering the
database the application actually uses.

The document meant to close the gap, [BACKUP_RECOVERY_PLAN.md](../BACKUP_RECOVERY_PLAN.md), followed
the form [ADR 0227](0227-read-audit-plan.md), [ADR 0229](0229-attribution-gap-plan.md),
[ADR 0230](0230-mfa-implementation-plan.md) and [ADR 0231](0231-secret-rotation-plan.md) established:
an unowned proposal, priced options, numbered decisions, no implementation. Unlike those, the central
claim here could be measured rather than argued — a stale archive needs no new code, only a second
dump — so the replay was performed on synthetic data in throwaway databases and every number in the
plan is its result.

## Decision

Measure the documented restore path, perform one replay of a stale archive and record what passed,
rewrite the plan so that every option carries a counted price, and implement no backup control.

1. **The plan now states measurements instead of adjectives.** A `## What is true today, measured`
   section in four subsections — the documented restore path, the replay, the envelope and custody,
   and what the repository already says — a `## Candidate approach and decisions required` section of
   eight numbered decisions, an `## Options and what each costs` table of seven options, a
   `## Required behavior before any restore` list of seven items and a
   `## Verification before any enablement` list of six.
2. **The seven options are A leave the restore path as documented, B read the archive's own header
   before restoring, C record every dump and restore in the database, D put the envelope keys in a
   custodian outside the repository, E document and drill the live-database shape, F verify
   completeness against a manifest instead of a self-written fixture, and G declare backup and
   recovery out of Phase 1 scope.** Each carries a price counted from this tree and a sentence saying
   what it still does not answer.
3. **`daroobank/test_backup_recovery_plan.py` pins both halves.** Twenty-three tests are database-free
   and pin the plan's structure, the guide's six-step trace, the drill's unread listing, the envelope
   drill's self-minted keys, the workflow's absent secrets and the schema pins a record would move;
   one is an opt-in replay under `DAROOBANK_RESTORE_TESTS` that re-performs the measurement, so an
   archive that is missing a later fact still has to pass every existing verification for this record
   to stay true.
4. **Nothing was implemented.** No backup record, no manifest, no custodian, no `--clean` in any
   documented sequence, no new command, no new dependency and no change to the restore target policy.
   The suite's `NothingImplementedTests` pins each absence, including the 17 project migration
   modules and the 24 project models.

## Measured behavior

All of it from the suite and from the replay run against the synthetic PostgreSQL 16.2 server with the
`pg_dump`, `pg_restore` and `createdb` clients the `pgserver` wheel bundles, on synthetic accounts in
throwaway databases.

- **The documented sequence is six steps and the second one discards its own output.**
  `daroobank/test_backup_guide.py` pins the trace as `['dump', 'list', 'createdb', 'restore',
  'migrate', 'check']` with fake binaries, and the guide's listing step is
  `pg_restore --list --no-password -- "$SYNTHETIC_DUMP_FILE" > /dev/null`. The drill captures the same
  listing and asserts exactly one thing about it —
  `self.assertEqual(listed.returncode, 0, 'Synthetic archive listing failed')` — and `listed.stdout`
  appears nowhere in its 315 lines.
- **The target is always new.** The guide runs `createdb --no-password daroobank_restore_drill` and
  retargets `POSTGRES_DB` to that literal name twice; the drill's docstring says *"Source and target
  are new, dedicated databases, never an existing database"* and it refuses a colliding target rather
  than replacing it. Of the 262 markdown documents in `docs/`, the only two that name `--clean`,
  `--if-exists` or `dropdb` are this record and the plan.
- **An archive carries no privileges and every credential.** Its header counts `TOC Entries: 291` and
  the listing prints 287 selected entries — 33 `TABLE`, 33 `TABLE DATA`, 60 `INDEX`, 30 `SEQUENCE`
  and 30 `SEQUENCE SET`, 51 `CONSTRAINT` and 50 `FK CONSTRAINT` — of which **zero** carry an ACL, an
  OWNER or a GRANT, because the dump is taken with `--no-owner --no-acl`. The 50 foreign-key
  constraints match the 50 foreign keys `manage.py inspect_postgresql_schema` counts, and four of the
  33 `TABLE DATA` entries are `auth_user`, `auth_user_groups`,
  `auth_user_user_permissions` and `django_session`.
- **Two dumps of one database in one second are indistinguishable by metadata.** The stale archive is
  136,001 bytes and the fresh one 136,541, so the bytes differ; both listings print
  `; Archive created at 2026-11-26 23:37:44 UTC`, because the dumps took 0.071 s and 0.053 s and the
  stamp has one-second resolution, and both name the same source `dbname`.
- **The stale archive restores silently, and every existing check passes on it.** `pg_restore` exited 0
  in 0.163 s and printed **0 bytes** on stdout and stderr; the target held 33 public tables, 32 applied
  migrations, 2 accounts, 0 sessions, 1 package and 1 review, while the source still held 2 and 2.
  `manage.py check` (0.372 s), `manage.py migrate --check` (0.390 s),
  `manage.py inspect_postgresql_schema` (0.388 s) and the drill's ORM verification (0.522 s) all exited
  0 with empty stderr — 1.673 s of verification that cannot tell a stale archive from a current one,
  because the fixture it verifies was written by the process that dumped it.
- **The live-database shape fails, and its fix is undocumented.** A second `pg_restore` of the same
  archive into the already-restored target exited 1 in 0.006 s with
  `ERROR:  relation "auth_group" already exists` on the first `CREATE TABLE`. Adding
  `--clean --if-exists` made it exit 0 in 0.209 s with empty stderr and left 33 tables, 1 package,
  1 review, 2 accounts and 32 applied migrations, with `manage.py check` and `migrate --check` passing.
- **These are the only restore durations the repository has.** Dump 0.071 s, listing 0.003 s, restore
  0.163 s, verification 1.673 s, for a 33-table two-account fixture. The runbook asks for *"actual
  restore duration and recovery point"*; a fixture is not a volume.
- **The envelope drill mints and destroys its own keys.**
  `daroobank/test_synthetic_encrypted_restore.py` runs `openssl req -x509 -newkey rsa:2048 -nodes
  -days 1 -subj /CN=synthetic-only`, `openssl genpkey`, `openssl pkey -pubout`,
  `openssl cms -encrypt -binary -aes-256-gcm -outform DER` and `openssl dgst -sha256 -sign`/`-verify`,
  every file `O_WRONLY|O_CREAT|O_EXCL` at mode `0600` inside a `0700` temporary directory that the
  test destroys. `.github/workflows/checks.yml` references **zero** `secrets.*` expressions and no key
  file is committed, so the *"independent key custody"* the release gate lists as open is the same
  unanswered question [ADR 0231](0231-secret-rotation-plan.md) left for `DAROOBANK_SECRET_KEY`.
- **The client tools are not in the repository and not pinned by it.** No `pg_dump` exists on this
  machine outside the virtual environment, and CI does not install one: it writes two wrapper scripts
  that run `docker run --rm --network host … postgres:16 … pg_dump`, one of the four mutable base-image
  references [ADR 0226](0226-ci-artifact-gate.md) counted, so the client version a drill uses can
  change without a commit.
- **Nothing records a dump or a restore.** `LOGGING` is `{}`, the only module in the tree that imports
  `logging` is a test measuring the absence of handlers, `pg_restore` printed 0 bytes, none of the 24
  project models is named like a backup, dump, archive, restore or recovery record, and the runbook's
  instruction is that a human *"Record the outcome without sensitive details"*.

## Red checks

Twenty mutations were applied to a byte-identical backup of the tree, one at a time, and the
suite was run after each with `DAROOBANK_RESTORE_TESTS=1` and the bundled clients on `PATH`,
so the replay ran too. Every file was restored and re-hashed afterwards, the two mutations
that create a file left nothing behind, and the final run was green.

| Mutation | Result |
| --- | --- |
| the plan drops its proposal disclaimer | exit 1, 1 of 24 tests fail |
| the plan drops its `Nothing is implemented` sentence | exit 1, 2 of 24 tests fail |
| the plan drops the measured archive stamp | exit 1, 2 of 24 tests fail |
| the plan drops a measured archive size | exit 1, 2 of 24 tests fail |
| the plan drops a numbered decision | exit 1, 2 of 24 tests fail |
| the plan drops an option row | exit 1, 1 of 24 tests fail |
| the plan stops quoting the release-evidence gate | exit 1, 3 of 24 tests fail |
| the plan drops the measured TOC composition | exit 1, 1 of 24 tests fail |
| `docs/DEVELOPMENT_GUIDE.md` stops discarding the archive listing | exit 1, 1 of 24 tests fail |
| `daroobank/test_synthetic_restore.py` starts reading the listing it captures | exit 1, 2 of 24 tests fail |
| `docs/OPERATIONS_RUNBOOK.md` names a live-database restore | exit 1, 1 of 24 tests fail |
| `.github/workflows/checks.yml` starts holding a secret | exit 1, 3 of 24 tests fail |
| `daroobank/settings.py` configures a logging handler | exit 1, 1 of 24 tests fail |
| the envelope drill mints a one-year certificate | exit 1, 2 of 24 tests fail |
| this record loses a limitation | exit 1, 1 of 24 tests fail |
| the decision index stops summarizing this record | exit 1, 1 of 24 tests fail |
| a key file appears in the repository | exit 1, 1 of 24 tests fail |
| a module named like a backup control appears | exit 1, 1 of 24 tests fail |
| `daroobank/restore_test_settings.py` renames the isolated database | exit 1 before any test runs |
| `daroobank/synthetic_restore_fixture.py` loses the post-restore write verifier | exit 1, 1 of 24 tests fail |

All twenty were caught. The widest catches were the plan no longer quoting the release-evidence
gate and the workflow growing a secret, which each broke three tests: the quotation pin, the
custody pin and the pin on what the plan says about the tree. Renaming the isolated test
database is caught before the suite starts, by `daroobank/isolated_postgresql`, which raises
*"Invalid isolated synthetic test database name."* rather than create a database it does not
recognize. After every file was restored from its backup and re-hashed, the suite ran green
again (24 tests, exit 0), no file differed by a byte and no database was left behind.


## Consequences

- `docs/BACKUP_RECOVERY_PLAN.md` is the answer to the *Backups and recovery* row of
  `docs/PHASE1_RELEASE_EVIDENCE.md`, and the row now says so. The row stays **Open**: a plan is not an
  operating backup service, an owner, a recovery objective or a custody arrangement.
- `docs/DEVELOPMENT_GUIDE.md`, `docs/OPERATIONS_RUNBOOK.md`, `docs/SECURITY.md`,
  `docs/DEPLOYMENT.md`, `docs/TESTING_STRATEGY.md` and `docs/CHANGELOG.md` each gained a sentence that
  names what the drill does not prove and links this record. The guide's script, the runbook's
  prohibition and the drill's target policy are unchanged, because changing them is option E and no
  option was chosen.
- The restore drills still pass unchanged: `DAROOBANK_RESTORE_TESTS=1
  DAROOBANK_ENCRYPTED_RESTORE_TESTS=1` with the bundled clients on `PATH` runs the 16 tests of
  `daroobank/test_synthetic_restore.py`, `daroobank/test_synthetic_encrypted_restore.py` and
  `daroobank/test_synthetic_restore_guard.py` in 23.8 s against the synthetic server and leaves no
  database behind.
- The new suite is the fifth opt-in one: its replay test is skipped unless `DAROOBANK_RESTORE_TESTS` is
  set and a `pg_dump` is on `PATH`, which an ordinary run reports as one more skip. No CI step runs it,
  because the workflow's restore steps name `daroobank.test_synthetic_restore` and
  `daroobank.test_synthetic_encrypted_restore` explicitly.
- The pins that count the tree moved with it: `daroobank/test_document_links.py` now counts 263
  documents, 232 records, 1037 links, 31 external links, 29 anchors and 22 `Suite:` lines, and the two
  suites that count test modules now count 238.
- A reader can now see, without running anything, that the drill's listing step throws away the only
  metadata the archive carries, that the archive it produces holds every password hash and no
  privilege, that a stale copy of it passes every check the repository has, and that the shape of a
  recovery into the database in use is written down nowhere.

## Limitations

- **The replay was performed once, on a fixture, in throwaway databases.** Two accounts, one package,
  one review and a cross-domain fixture across the 24 project models. It says nothing about the
  duration of restoring a real volume, the behaviour of `--clean --if-exists` against a large or
  concurrently used database, or what an operator sees while it happens.
- **No option was evaluated for security or lawfulness.** Whether a pharmacy staff portal may restore
  a database over itself, who may hold an envelope key, how long a dump of every password hash may be
  retained and what a recovery objective should be are questions for an owner and a reviewer, not for
  this record.
- **The prices are counted, not run.** No backup control was prototyped, so no cascade of pin failures
  was measured the way [ADR 0227](0227-read-audit-plan.md) measured 20 failures across 7 suites. The
  counts in options B to G are an inventory of what moves, and the real total is unknown until an
  implementation exists.
- **Custody was not measured because there is none to measure.** No secret store, KMS, key file or
  passphrase variable exists in this tree and the workflow holds no secret, so nothing here says where
  a real envelope key should live; decisions 1, 3 and 6 stay open.
- **The live-database shape was exercised mechanically and proves nothing operational.**
  `--clean --if-exists` succeeded on a throwaway target that no process was using, with no
  authorization step, no downtime argument, no privilege re-grant and no verification beyond
  `manage.py check` and `migrate --check`. Recording that it worked is not a recommendation to do it.
- **The suite pins documents, counts and one measured replay.** It cannot tell whether the eight
  decisions will ever be answered, whether the answers will be adequate, or whether a restore performed
  under them would recover the business; forcing the questions is all this record does.
