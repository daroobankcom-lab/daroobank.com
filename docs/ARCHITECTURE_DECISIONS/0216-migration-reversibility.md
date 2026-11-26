# 0216 — migration reversibility and rollback round trips on throwaway databases

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_migration_reversibility.py` (7 tests, ~5.7 s)

## Context

The Phase 1 gate for the data model asks for a *"staging upgrade and rollback plan against
a representative schema, migration compatibility, tested recovery"*. CI already runs three
related steps against the development database: `manage.py migrate --noinput`,
`manage.py makemigrations --check --dry-run` and `manage.py inspect_postgresql_schema`, and
`daroobank/postgresql_inspection.py` compares that database against expectations derived
from the models. Individual data migrations have their own suites.

What nothing measured was the direction the gate actually names:

* whether the migrations can be rolled back at all;
* what rolling one app back does to the apps that depend on it;
* whether the schema after a rollback and a reapply is the same schema as before;
* whether data migrations declare a reverse, and what that reverse actually does.

## Decision

`daroobank/test_migration_reversibility.py` measures those four things on **throwaway
PostgreSQL databases** it creates and drops itself, on the same synthetic server the suite
runs against. Each test gets its own database named `daroobank_migration_probe_<12 hex>`;
nothing is written into the suite's own database, and no rows of any kind are inserted —
these are empty databases, so the exercise is about schema, not data.

Three implementation choices matter:

- **The probe connection is registered dynamically, not declared in `DATABASES`.** A test
  case may only reach the aliases it declares, and Django deliberately allows connections
  created at runtime; adding an alias to the settings instead makes every migration call
  fail with `DatabaseOperationForbidden`. The alias is deleted and the database dropped in
  a `finally`, and one test asserts no probe database is left behind.
- **The model-derived inspection is reused rather than reimplemented.**
  `postgresql_inspection.inspect_schema` reads the module-level `connection`, so the suite
  patches that attribute to the probe connection and gets the same expectations CI applies
  to the development database — a freshly migrated probe database must report
  `no_selected_issues`, and a rolled-back one must report `attention` with unresolved
  tables.
- **The rollback cascade is derived from the migration graph, not hardcoded.** Nothing
  depends on catalog's leaf migration, so `backwards_plan` of the leaf alone is empty; the
  expected set is the union of `backwards_plan` over *every* catalog migration, which is
  then compared with the migrations Django actually unapplied.

## Measured behavior

| Measurement | Result |
|---|---|
| Migration inventory | 16 migrations over 6 apps: catalog 8, clinical 2, ingestion 2, pricing 2, sources 1, staff_security 1; each app is one linear chain from its `0001_initial`, each migration depending on exactly its predecessor |
| Data operations | exactly 2, both `RunPython`, both declaring `migrations.RunPython.noop` as their reverse (catalog 0002 and 0004) — a no-op reverse means Django will not raise, and will not undo the backfill either |
| Freshly migrated probe database | 32 tables (23 of them project tables: catalog 13, clinical 3, ingestion 2, pricing 2, sources 2, staff_security 1), 276 columns, 108 indexes, 136 constraints, 50 foreign keys, 31 applied migrations, inspection status `no_selected_issues` |
| `migrate catalog zero` | unapplies exactly the 11 migrations the graph says depend on it — catalog's own 8 plus pricing 2 and ingestion 1 — leaving 16 tables, 17 foreign keys, no foreign key without its target table, and inspection status `attention` |
| Full rollback of all six apps | only Django's own tables remain (`auth_*`, `django_content_type`, `django_session`, `django_migrations`); no project app is recorded as applied |
| Reapply after a full rollback | the column, index and constraint inventory is **identical** to the first migration, and the inspection returns to `no_selected_issues` |
| `makemigrations --check --dry-run` inside the suite | detects nothing, mirroring the CI step so a local run catches a missing migration too |

## Red checks

1. Adding `probe_red_check = models.CharField(...)` to `StaffLoginWindow` with no migration
   fails **3** tests: the drift check reports `makemigrations --check exited 1`, and both
   the fresh-database and round-trip tests fail because the model-derived inspection now
   expects a column the migrations never create.
2. Removing the `migrations.RunPython.noop` reverse from catalog 0002 fails the
   reversibility test with `catalog.0002_productpresentation_irc_normalized has a RunPython
   with no reverse`, and both rollback tests **error** with
   `django.db.migrations.exceptions.IrreversibleError` — an irreversible data migration
   cannot be rolled back at all.
3. Adding an empty `catalog/migrations/0009_probe_red_check.py` fails **4** tests: the
   chain count (`9 != 8`), the applied-migration count (`32 != 31`) and both
   database-exercising tests.

All three were reverted from backups; `git status --short` showed only the new suite.

## Limitations

- **These are empty databases.** Nothing here measures a rollback with data in it. Rolling
  back a migration in production drops tables and columns, and Django does not preserve
  their contents; a real rollback plan needs a backup and restore step that this suite does
  not exercise (the synthetic dump/restore drill is separate and opt-in).
- The two data migrations reverse to a no-op, so a rollback of catalog 0002 or 0004 leaves
  whatever the backfill wrote behind in any column that survives. The suite names that set;
  it does not fix it.
- PostgreSQL only, on one server, with one role that can create databases. A staging
  environment, its role permissions, its extensions and its tablespaces are not involved.
- No timing, locking or concurrency is measured. Migrations here run against an idle
  database in about a second; a populated staging database is a different exercise, and
  `ALTER TABLE` lock behavior is not tested.
- The suite rolls back the six project apps in reverse order and leaves Django's own apps
  applied. Rolling back `auth`, `contenttypes` or `sessions` is not measured.
- The schema comparison covers columns, indexes and constraints in the `public` schema.
  Sequences, ownership, grants, extensions, views and trigger bodies are not compared
  beyond what `inspect_schema` already reports.
- **The gate is still open.** This is the measurable part of "migration compatibility and a
  rollback plan". The plan itself — staging environment, who runs it, in what order, with
  which backup, and who authorizes a destructive operation — needs an owner and is not
  written here.
