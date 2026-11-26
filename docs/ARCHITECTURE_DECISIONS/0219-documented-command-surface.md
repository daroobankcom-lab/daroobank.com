# 0219 — every management command is documented where an operator looks

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_command_documentation.py` (7 tests, ~0.01 s, no database)

## Context

ADR 0218 keeps `django.contrib.admin` out of the project, which means the administrative
surface is the hand-built staff portal plus the management commands. There is no other place
an operator goes: twelve commands across five apps are how this project inspects a catalog
batch, stages a price CSV, previews a projection repair, checks deployment readiness,
inventories staff sessions, revokes them, and cleans up login-throttle rows.

A command nobody can find is a command nobody runs. An inventory taken against the three
operator documents — the development guide, the operations runbook and the deployment guide —
showed the documentation had drifted from the registry in three directions:

| Gap found | Effect |
|---|---|
| `cleanup_staff_login_windows` appeared in no operator document, only inside ADR 0181 and ADR 0218 | the only way to keep `staff_security_staffloginwindow` from growing without bound was recorded where a reader goes to understand a decision, not to learn what to type |
| `revoke_staff_sessions --all` was mentioned nowhere; the runbook showed only `--username` | the documented way to clear the whole portal after, say, a secret rotation did not exist in the runbook |
| the development guide's staff paragraph listed "login throttling" among the capabilities that "remain missing" | a limiter does exist behind `DAROOBANK_STAFF_LOGIN_THROTTLE=1` (ADR 0181); the sentence was true of production-grade abuse protection and false of the code |

None of these is a bug. All of them are the ordinary way an operational tool becomes
undiscoverable: the command is written, tested, recorded in a decision record, and the runbook
is updated for the commands someone happened to think about.

## Decision

Bring the three documents in line with the registry, and hold them there with
`daroobank/test_command_documentation.py`:

- the development guide gains a section on the opt-in staff login throttle and on
  `cleanup_staff_login_windows`, with both forms, the JSON each prints, and the bounds the
  command imposes on itself (debug-only, PostgreSQL in autocommit, a one-second lock timeout
  and a two-second statement timeout, at most 500 rows per run, oldest first, age rechecked
  after any lock wait);
- the "missing capabilities" sentence now says *production-grade login abuse protection*, and
  names the development limiter as not being one;
- the runbook documents `revoke_staff_sessions --all --apply` alongside `--username`, and says
  both forms are read-only without `--apply`, delete at most one bounded batch and print one
  JSON object;
- the suite checks, in order: a pinned inventory of the twelve commands and the app that owns
  each; that a command file on disk and a registered command name are the same set; that every
  command is named in at least one operator document; that every option a command accepts
  beyond Django's nine base options is mentioned in the documents that name it; that a
  write-capable command — four of them, flagged `--apply` or `--commit` — is documented as
  read-only without that flag and documents the flag itself; that every `manage.py <name>`
  mentioned in the README or the three operator documents exists; and that the operator
  documents are not empty, so emptying one cannot make the other checks pass trivially.

## Measured behavior

| Measurement | Result |
|---|---|
| Project commands | 12, across 5 apps: `check_deployment_readiness` (daroobank); `cleanup_staff_login_windows`, `list_staff_sessions`, `revoke_staff_sessions` (staff_security); `inspect_catalog_irc`, `inspect_catalog_quality`, `inspect_postgresql_access`, `inspect_postgresql_schema`, `repair_catalog_projection` (catalog); `inspect_ingestion_window` (ingestion); `list_price_candidates`, `stage_price_csv` (pricing) |
| Project-specific options | 24 beyond the 9 Django base options; before this ADR, 2 were mentioned in no document that named their command |
| Commands named in an operator document | 12 of 12 (was 11 of 12) |
| Write-capable commands | 4: `cleanup_staff_login_windows --apply`, `revoke_staff_sessions --apply`, `repair_catalog_projection --commit`, `stage_price_csv --commit`; each is now documented as read-only without its flag |
| Options read from | the live parser each command builds (`load_command_class(...).create_parser(...)`), not a hand-kept list, so a new option is a documentation event |
| Suite cost | 7 tests in ~0.011 s, `SimpleTestCase`, no database, no filesystem writes |

## Red check

Three regressions were applied at once — the new development-guide section deleted, `--all`
removed from the runbook sentence, and an undocumented `inspect_catalog_probe` command added
under `catalog/management/commands/` — producing 6 failures across 5 tests: the inventory pin
and the file/registry set both caught the new command; "named where an operator looks", the
option check and the read-only-without-flag check all caught the deleted section; and the
option check separately caught the missing `--all`. All three were reverted (backups in
`/tmp/guide.rc.bak` and `/tmp/runbook2.rc.bak`, probe file removed) and the suite passed again.

A second check replaced `docs/DEPLOYMENT.md` with a 13-character stub: the emptiness guard
failed, and restoring the file passed.

## Limits

- This checks that a command is *named* and that its options are *mentioned*. It cannot check
  that the surrounding prose is correct, complete, current, safe to follow, or consistent with
  the other documents. A document may describe `--apply` as read-only and every test here
  still passes.
- Matching is by substring. A command name appearing inside an unrelated sentence, or an
  option string appearing in another command's block of the same document, satisfies the check.
- The pinned inventory fails on any legitimate addition, including a command that ships fully
  documented. That is deliberate friction: the new command's documentation decision should be
  recorded here.
- "Where an operator looks" is these three documents. A command documented only in some other
  page is treated as undocumented, and the `manage.py <name>` existence check scans only the
  README plus those three.
- The emptiness guard is a length threshold, not a content judgment; a document padded past it
  would pass.
- Django's own commands (`migrate`, `createsuperuser`, `collectstatic`, `test`) and any
  third-party command are out of scope by design: the project does not own their interface.
