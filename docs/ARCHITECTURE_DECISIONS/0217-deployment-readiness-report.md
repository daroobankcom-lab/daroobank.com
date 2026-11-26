# 0217 — one readiness report for the settings a deployment has to get right

Date: 2026-11-26
Status: accepted
Code: `daroobank/management/commands/check_deployment_readiness.py`
Suite: `daroobank/test_deployment_readiness.py` (10 tests, ~2.5 s)

## Context

The Phase 1 gate for monitoring and response lists *"production-specific readiness
checks"* among its open items. What existed was narrow:

* `health/ready/` answers one question — can this process run a `SELECT 1` inside a
  one-second statement timeout — and is off unless `DAROOBANK_HEALTH_PROBES_ENABLED=1`;
* `daroobank/configuration.py` refuses to boot a non-debug process with a bad secret or
  host shape, which is fail-closed but says nothing once the process is up;
* `manage.py inspect_postgresql_schema` compares the database against model-derived
  expectations, and `manage.py check` runs Django's own system checks.

Nothing collected the rest of the conditions a deployment has to get right — DEBUG, the
staff portal, cookie flags, HTTPS redirection, pending migrations, an applied migration
with no file in this release — and nothing reported them in a form an operator or a release
gate can read and diff.

## Decision

`check_deployment_readiness` reads settings and the migration table, writes nothing, and
prints one JSON report. It runs in debug and non-debug alike, and in a development
environment it is *expected* to report "not ready" and to say why.

Two lists, because a broken setting and an undecided question are different things:

* **`required`** — ten checks, each with an id, a boolean and a detail line: `debug_disabled`,
  `staff_portal_disabled`, `secret_key_shape`, `allowed_hosts_explicit`, `cookies_secure`,
  `session_flags`, `ssl_redirect_enabled`, `migrations_applied`,
  `migration_history_consistent`, `database_reachable`. `ready` is true only when all ten
  pass. Exit status is 0 when ready, 1 when not.
* **`review`** — conditions that are not failures of this configuration but that a
  deployment still has to decide about, each with a reason: HSTS off, HTTPS redirection
  with no trusted proxy header, development hostnames in `ALLOWED_HOSTS`, health probes
  answering, the synthetic login limiter, `XFrameOptionsMiddleware` absent. `--strict`
  additionally fails when this list is not empty.

The shape checks reuse `configuration.require_nondebug_secret` and
`require_nondebug_hosts` rather than restating them; the session flags are the ones ADR
0208 pins; the reachability check is `health.database_ready()`.

A consequence worth recording: `daroobank` had to be added to `INSTALLED_APPS` for a
command in `daroobank/management/commands/` to be discoverable at all. It declares no
models, so it adds no tables, no migrations and no content types — the schema inventory
ADR 0216 pins is unchanged (32 tables, 276 columns, 108 indexes, 136 constraints, 50
foreign keys, 31 applied migrations), and 96 tests across the schema-sensitive suites
still pass.

## Measured behavior

| Situation | Report |
|---|---|
| The synthetic test environment | `ready: false`, failing `staff_portal_disabled`, `secret_key_shape`, `cookies_secure`, `ssl_redirect_enabled`; review lists `hsts_disabled`, `development_hosts`, `clickjacking_middleware_absent`. Django's test runner forces `DEBUG=False` for the whole suite, so `debug_disabled` passes inside tests and is covered by the per-check test instead |
| A hardened fixture (debug off, portal off, valid secret shape, one explicit host, secure cookies, HTTPS redirection with a trusted proxy header, HSTS one year, probes and limiter off, clickjacking middleware installed) | `ready: true`, `failed: []`, `review: []`, exit 0 — and with `--strict` also exit 0 |
| Each of the seven settings-driven required checks broken alone | exactly that one check fails and the exit status is 1 |
| An unmigrated throwaway database | `migrations_applied` fails alone, naming 31 pending migrations |
| A throwaway database with an applied row for `catalog.0099_never_written` | `migration_history_consistent` fails alone, naming it |
| The command run inside an open transaction | `database_reachable` fails alone, because `database_ready()` answers false in an atomic block — the caveat is in the detail line, not hidden |
| Hardened fixture with HSTS back to 0 and `--strict` | exit 1 while `ready` stays true: a review item is not a failed required check, and without `--strict` the same configuration exits 0 |
| Any of the six review conditions introduced alone | exactly that review item appears, with a reason and no other keys |
| Two runs of an unchanged configuration | byte-identical JSON; keys are exactly `failed`, `ready`, `required`, `review`, `scope`, and the required ids appear in declaration order |
| Secret handling | neither the secret value nor its first 24 characters appears anywhere in the output |
| Writes | none: the 14 counted domain models and the `django_migrations` row count are unchanged, and no throwaway probe database is left behind |
| Discoverability | the command is named in `docs/DEPLOYMENT.md` (probes section and release gates) and in `docs/OPERATIONS_RUNBOOK.md`, which also gained a deployment-readiness section and, in the security/privacy incident section, the containment steps that use `list_staff_sessions` and `revoke_staff_sessions`. One test fails if either document stops naming the command and its ADR |

## Red checks

1. Making `debug_disabled` return `True` unconditionally — a check that can no longer fail
   — fails `test_every_required_check_fails_on_its_own` on that check.
2. Echoing `settings.SECRET_KEY` into the secret check's detail line fails
   `test_a_hardened_configuration_reports_ready`, which asserts the value and its first 24
   characters are absent from the output.

Both were reverted from a backup and the restored file compared byte for byte with it.

## A documentation defect found on the way

Documenting this work destroyed two `## ` entry headings in `docs/CHANGELOG.md`: a patch
script replaced a heading instead of inserting above it, and nothing in the repository
noticed — the entry bodies were still there, untitled and undated. Both were restored.
`daroobank/test_release_notes_structure.py` (2 tests, no database) now fails on that defect
rather than on the prose: headings must be unique, the four legacy undated headings are
pinned so a new entry cannot join them, dated entries must stay newest-first, and every
`**Changes:**` paragraph must sit under its own heading with one body per heading. Deleting
an entry heading fails it. This checks structure only; it cannot tell whether an entry is
accurate or honest about its limits.

## Limitations

- **A zero exit status is not a deployment authorization.** The report describes the shape
  of one process's settings and one database connection. It is not monitoring, alerting,
  MFA, TLS issuance, backup verification, network isolation, a penetration test or an
  independent security assessment, and the suite says so in assertions on the scope line.
- The hardened fixture is a **test fixture**, not a recommended production profile. It
  exists to prove the checks discriminate; choosing real values is an owner decision that
  depends on TLS topology, proxy configuration and hostnames that do not exist yet.
- The report is only as complete as its ten checks. Nothing verifies static files were
  collected, logging is routed, clocks are synchronized, connection pooling is sized,
  replicas are healthy, the process can actually serve a request, or that any external
  dependency is reachable. No request is made.
- `database_reachable` is a single `SELECT 1` with a one-second statement timeout, and it
  answers false inside an open transaction, so it must be run outside one. It proves
  neither migration state nor recovery.
- Review items are prompts for a decision, not decisions. HSTS and the trusted proxy
  header in particular depend on a TLS policy and a proxy topology that ADRs 0184–0185
  leave to an operator, and this command cannot choose them.
- `migration_history_consistent` detects an applied migration with no file in *this*
  release. It cannot detect a release that is older than the database in any other way, a
  squashed history, or a migration applied out of order.
- The command reports the configuration of the process that runs it. A deployment with
  several processes, roles or environments needs one report per process, and nothing here
  aggregates or stores them; there is no history, no alerting and no dashboard.
