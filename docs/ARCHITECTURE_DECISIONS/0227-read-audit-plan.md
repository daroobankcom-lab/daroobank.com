# 0227 — the read-audit decision, and the measured price of making it in the application

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_read_audit_plan.py` (6 tests, ~0.005 s, no database)

## Context

[ADR 0221](0221-no-read-audit.md) measured that nothing in this application records that a read
happened — `LOGGING` is `{}`, no project module imports `logging`, no middleware records a request,
no table can hold an access record, and sweeping all 43 staff routes and all 12 public routes
changes no row count — and then declined to add logging, because *"adding an access log is a design
decision with retention, PHI and tamper-resistance consequences that this project has not made"*.

The requirement behind that decision is written down elsewhere and is not optional:
[SECURITY.md](../SECURITY.md) asks that audit records carry *"actor, role, target, before/after
versions or hashes, decision, time and request correlation, without PHI in general logs"* and be
protected *"from modification by application roles"*, its privacy section requires a recorded legal
basis, retention and deletion policy *"with legal review"*, `daroobank/settings.py` keeps the staff
portal development-only *"until MFA, throttling and audit exist"*, and the operations runbook tells
an incident responder to review access and audit logs after a restore.

So what was missing was not code but a decision — and a decision made without a price tag is a
guess. [docs/MFA_IMPLEMENTATION_PLAN.md](../MFA_IMPLEMENTATION_PLAN.md) is the form this repository
already uses for that situation: a proposal, explicitly not an approved control, naming the
decisions owners still have to make.

## Decision

Write the read-audit decision down in the same form, measure what the in-application option
actually costs, and implement nothing.

1. **[`docs/READ_AUDIT_PLAN.md`](../READ_AUDIT_PLAN.md)** states the requirement, the two existing precedents (append-only
   models that refuse `save()` and `delete()`, and the keyed digest in `staff_security/throttle.py`
   that stores an HMAC of a normalized address instead of the address), the six decisions that block
   implementation, the measured cost of one design point, the two alternatives, and what has to be
   verified before any enablement.
2. **The cost was measured, not estimated.** A prototype was built in a scratch copy of the tree —
   one append-only `ReadAuditEntry` model in `staff_security` (keyed client key, nullable protected
   actor, route name, status code, authenticated flag, timestamp), its migration, one middleware
   writing a row per GET behind a new `DAROOBANK_READ_AUDIT` setting — nine pin-holding suites were
   run against it, and the prototype was then discarded. It is not in the repository: the working
   tree holds no model, no migration, no middleware and no setting.
3. **`daroobank/test_read_audit_plan.py` pins the plan**: that it is a proposal, that its six
   decisions and five sections are all present, that it still quotes the requirements it answers,
   that every suite and record its cascade table names exists, that the failure counts add to 20,
   that the prototype's schema numbers are the measured ones, that the seven records it would
   supersede are named, and that nothing is implemented while the plan says nothing is.

## Measured behavior

Running nine suites that pin schema, configuration or read behavior against the prototype — 138
tests — produced **20 failures across 7 of them**:

| Suite | Failures | What moves |
|---|---|---|
| `daroobank/test_no_read_audit.py` (ADR 0221) | 5 | the twelve-entry middleware tuple gains a thirteenth; the 32-table inventory becomes 33; the model-name scan matches `ReadAuditEntry`; the staff sweep writes 43 rows and the public sweep 12 |
| `daroobank/test_populated_rollback_drill.py` (ADR 0225) | 5 | the 23-table fixture becomes 24, and every rollback measurement shifts: 32 tables instead of 31 after a full rollback's reapply, 32 applied migrations instead of 31, and the blocked plan leaves 31 applied rather than 30 |
| `daroobank/test_migration_reversibility.py` (ADR 0216) | 4 | `staff_security` holds 2 migrations instead of 1, 17 instead of 16 in total, and both per-app table counts and the cascade counts change |
| `daroobank/test_no_abuse_protection.py` (ADR 0223) | 3 | 48 repeated public reads write 48 rows instead of none, the login limiter is no longer the only middleware that acts on a request, and the module scan names `daroobank/read_audit.py` |
| `daroobank/test_actor_attribution_inventory.py` (ADR 0220) | 1 | the project model count becomes 24, and the new actor reference makes it a twentieth |
| `daroobank/test_environment_documentation.py` (ADR 0222) | 1 | the environment inventory gains `DAROOBANK_READ_AUDIT`, which the deployment configuration reference must then document |
| `daroobank/test_deployment_readiness.py` (ADR 0217) | 1 | the pending-migration finding counts 32 unapplied migrations instead of 31 |

| Measurement | Result |
|---|---|
| Prototype schema, freshly migrated throwaway database | 33 tables, 283 columns, 113 indexes, 139 constraints, 51 foreign keys, 32 applied migrations — against today's 32, 276, 108, 136, 50 and 31 |
| `inspect_postgresql_schema` under the prototype | still `no_selected_issues`: its expectations are derived from the models, so the inspection itself needs no change |
| Suites that passed unchanged | `daroobank/test_postgresql_inspection.py` and `staff_security/test_migration.py` |
| Rows a read would write | one per GET: 43 for the staff sweep, 12 for the public sweep, 48 for the abuse-protection read loop — all in a table that today does not exist |

## Why a plan and not a feature

Six decisions have to be made before an implementation is defensible, and each one changes what the
code must do:

* **Scope** — every public read, only detail reads, only staff reads, or only reads of restricted
  content. This decides row volume on a catalog meant to be read by patients.
* **Identity and privacy** — account, keyed address digest, session correlation, or a combination;
  never a raw address, forwarded header, user agent, path, query string or search term, because a
  path or query can itself carry PHI. The legal basis needs review before enablement.
* **Retention** — a period, a prune procedure with a dry run and a recorded actor, and an answer to
  how deletion is authorized when every other model in this schema refuses it.
* **Tamper-resistance** — `save()` and `delete()` guards stop the application's own code, not a role
  with write or DDL grants; SECURITY.md asks for protection from application roles, which needs a
  separate role or schema, hash-chaining, a write-once store, or reliance on the write-ahead log.
* **Placement** — an existing app or a dedicated one; a dedicated app also moves the installed-app
  inventory and the project-app tuple the migration and rollback suites iterate.
* **Enablement** — default off behind a setting, following the login throttle's opt-in pattern,
  because turning it on makes three accepted records (0221, 0223, 0225) describe a system that no
  longer exists.

## Red checks

Seven, each applied alone and reverted from a backup:

1. Deleting the retention decision from the plan fails 1 test.
2. Understating one cascade row (5 failures as 4) fails 1.
3. Changing the prototype's measured column count (283 as 284) fails 1.
4. Dropping one record from the supersede list fails 1.
5. Creating `daroobank/read_audit.py` fails 1 — an implementation cannot appear while the plan says
   nothing is implemented.
6. Naming a suite that does not exist in the cascade table fails 1.
7. Paraphrasing a quoted SECURITY.md requirement instead of quoting it fails 1.

## Consequences

- The decision now has a home and a price tag. Whoever makes it writes an accepted record that
  supersedes the seven this plan names, with their pins recomputed in the same change.
- Implementing read auditing quietly is no longer possible: a module, a middleware entry, a setting
  or a model named like an access record fails this suite and ADR 0221's.
- The prototype is discarded, so nothing about the application's behavior changed. Reads still
  write nothing, and the runbook's instruction still cannot be followed inside this application.

## Limitations

- **The cascade is a lower bound.** Nine suites were sampled, not the full 1632-test suite, so the
  true total of pins an implementation moves is at least 20 and was not measured completely.
- One design point was prototyped: an existing app, a row per GET, no batching, no sampling, no
  asynchronous write. A dedicated app, a buffered writer or a sampled audit moves different pins
  and was not measured.
- No performance property was measured: write amplification, latency added to a public read, table
  growth, `VACUUM` behavior, index cost or the runtime of a prune over a large table are all
  unmeasured, and the plan does not estimate them.
- The tamper-resistance options are named, not evaluated; none was prototyped, and no separate
  database role, schema, hash chain or write-once store exists in this repository.
- The suite pins a document. It cannot tell whether the plan's options are the right ones, whether
  a retention period is lawful, or whether an owner will ever choose; those are the decisions the
  plan exists to force.
