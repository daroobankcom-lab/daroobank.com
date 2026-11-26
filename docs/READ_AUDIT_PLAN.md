# Proposed read-audit logging and the decisions it requires

This document is a **proposal**, not an implemented or approved control. Nothing in this
application records that a read happened: [ADR 0221](ARCHITECTURE_DECISIONS/0221-no-read-audit.md)
measured that from four directions — `LOGGING` is `{}`, no project module imports `logging`, the
twelve middleware entries set headers and delete sessions but write no record, the 32 tables
include no access-like table, and sweeping all 43 staff routes and all 12 public routes changes no
row count. The staff portal stays debug-only, all data stays synthetic, and an operator must not
treat this plan, the existing write-side history or the login window as an audit log. Owners still
have to decide scope, identity, retention, tamper-resistance and enablement, and to record those
decisions in an accepted ADR before any implementation.

## What a read audit has to satisfy here

`docs/SECURITY.md` states the requirement this plan is written against: audit records carry
*"actor, role, target, before/after versions or hashes, decision, time and request correlation,
without PHI in general logs"*, must be protected *"from modification by application roles"*, and
must be monitored; its privacy section adds data minimization, purpose limitation and a recorded
legal basis, retention and deletion policy *"with legal review"*. `daroobank/settings.py` opens
with the reason the staff portal is development-only: *"until MFA, throttling and audit exist"*.
`docs/OPERATIONS_RUNBOOK.md` tells an incident responder to review access and audit logs after a
restore — an instruction that, as ADR 0221 records, cannot be followed inside this application.

Two properties of the existing code are precedents rather than solutions: every append-only model
refuses `save()` on an existing primary key and refuses `delete()`, and
`staff_security/throttle.py` already turns a client address into a keyed digest
(`salted_hmac('staff_security.login.client.v1', …)`) instead of storing it, with the model comment
*"HMAC of normalized REMOTE_ADDR, not a raw IP or account identifier"*.

## Decisions required before implementation

1. **Scope.** Which reads are recorded: every public presentation read, only object-level detail
   reads, only staff-portal reads, or only reads of unpublished or restricted content? The choice
   decides row volume, and volume decides whether the table can live beside the application data at
   all. Recording every public read on a catalog meant to be read by patients multiplies writes
   against a database that today writes nothing on a read.
2. **Identity and privacy.** What identifies the reader: the authenticated account, a keyed digest
   of the client address following the existing precedent, a per-session correlation identifier, or
   a combination. Raw addresses, forwarded headers, user agents, full paths, query strings and
   search terms must never be stored — a path or a query can itself carry PHI or reveal a
   consultation. The legal basis and the data-minimization argument for whichever identifier is
   chosen need legal review before enablement, not after.
3. **Retention.** How long entries are kept, who may delete them, and how deletion is authorized
   when every other model in this schema is append-only and refuses deletion. A prune procedure
   needs a documented retention period, a dry-run mode, an actor recorded for the prune itself, and
   an answer to what happens to entries referenced by an incident investigation.
4. **Tamper-resistance.** An in-database table with `save()` and `delete()` guards stops the
   application's own code, not a role with write or DDL grants on the database.
   `docs/SECURITY.md` asks for protection *"from modification by application roles"*, which needs a
   decision between a separate database role or schema with no write grant for the application,
   hash-chaining entries, shipping to a write-once store, or relying on PostgreSQL's write-ahead
   log and its off-host retention. None of these exists today, and the choice constrains the
   backup and restore drills that are already measured.
5. **Where it lives.** A dedicated application or a model inside an existing one. The measured
   cascade below uses an existing app; a dedicated app additionally changes the installed-app
   inventory (11 today) and the project-app tuple that the migration and rollback suites iterate.
6. **Enablement.** Default off behind a setting, following the login throttle's opt-in pattern, and
   enabled only in an environment whose retention and tamper-resistance decisions are recorded.
   Turning it on changes measured behavior: reads start writing rows, so three accepted records
   (0221, 0223 and 0225) describe a system that no longer exists and have to be superseded, not
   quietly edited.

## Measured cost of the in-application option

A prototype was built and reverted: one append-only `ReadAuditEntry` model in `staff_security`
(client key, nullable protected actor, route name, status code, authenticated flag, timestamp), its
migration, one middleware writing a row per GET when a new `DAROOBANK_READ_AUDIT` setting is `1`,
and that setting. Running nine of the suites that pin schema, configuration or read behavior — 138
tests — produced **20 failures across 7 of them**:

| Suite | Failures | What moves |
|---|---|---|
| `daroobank/test_no_read_audit.py` (ADR 0221) | 5 | the twelve-entry middleware tuple gains a thirteenth; the 32-table inventory becomes 33; the model-name scan matches `ReadAuditEntry`; the staff sweep writes 43 rows and the public sweep 12 |
| `daroobank/test_populated_rollback_drill.py` (ADR 0225) | 5 | the 23-table fixture becomes 24, and every rollback measurement shifts: 32 tables, 31 applied, and the blocked-rollback plan leaves 31 rather than 30 applied |
| `daroobank/test_migration_reversibility.py` (ADR 0216) | 4 | `staff_security` holds 2 migrations instead of 1 and 17 instead of 16 in total; the per-app table counts and the cascade counts change |
| `daroobank/test_no_abuse_protection.py` (ADR 0223) | 3 | repeated public reads stop writing nothing (48 rows), the login limiter is no longer the only middleware that acts on a request, and the module scan names `daroobank/read_audit.py` |
| `daroobank/test_actor_attribution_inventory.py` (ADR 0220) | 1 | the project model count becomes 24 and the new model adds a twentieth actor reference |
| `daroobank/test_environment_documentation.py` (ADR 0222) | 1 | the environment inventory gains `DAROOBANK_READ_AUDIT`, which the deployment reference must document |
| `daroobank/test_deployment_readiness.py` (ADR 0217) | 1 | the pending-migration message counts 32 unapplied migrations instead of 31 |

On a freshly migrated throwaway database the prototype schema measured **33 tables, 283 columns,
113 indexes, 139 constraints, 51 foreign keys and 32 applied migrations**, against today's 32, 276,
108, 136, 50 and 31 — and `manage.py inspect_postgresql_schema` still reported
`no_selected_issues`, because its expectations are derived from the models rather than pinned.
`daroobank/test_postgresql_inspection.py` and `staff_security/test_migration.py` passed unchanged.

So the price of the mechanism is not the model; it is that five accepted records measured a system
in which reads write nothing, and each of them has to be superseded deliberately.

## Alternatives

- **Edge or host access logging.** A reverse proxy or the database host can record every request
  without an application change, and `docs/DEPLOYMENT.md` already assigns abuse protection to the
  edge. It carries no actor, no route semantics and no target identity, it is invisible to this
  repository's tests, and no such log is arranged today.
- **Keep the absence documented.** ADR 0221 already pins it and the runbook no longer promises a
  log that does not exist. This costs nothing and answers no incident question.

## Verification before any enablement

- Synthetic tests cover default-off behavior (no row, no setting, no middleware effect), the exact
  fields written, and the absence of raw addresses, forwarded headers, user agents, paths, query
  strings and search terms from every stored value.
- Append-only behavior is proven against the ORM and against raw SQL, and the prune procedure is
  tested for retention boundaries, dry-run mode, recorded actor and refusal to delete entries
  outside the window.
- The write path is measured under concurrency and under database timeouts: a read audit must not
  turn a public read into a failure, and a blocked audit write must not block the response.
- The backup, restore and rollback drills are re-run with the table populated, since ADR 0225
  measures row loss for every project table and a new one changes those numbers.
- The tamper-resistance choice is exercised, not asserted: an application role is shown to be
  unable to update or delete an entry, and the mechanism that prevents it is named.
- Superseding entries are written for ADRs 0216, 0217, 0220, 0221, 0222, 0223 and 0225 with their
  pins recomputed, and `docs/SECURITY.md`, `docs/DEPLOYMENT.md`, `docs/OPERATIONS_RUNBOOK.md` and
  `docs/PHASE1_RELEASE_EVIDENCE.md` are updated in the same change.
- Named owners record operational, security, legal/privacy and release approval. Implementing these
  tests does not by itself enable read auditing, authorize retention of reader identifiers, or
  complete any Phase 1 gate.
