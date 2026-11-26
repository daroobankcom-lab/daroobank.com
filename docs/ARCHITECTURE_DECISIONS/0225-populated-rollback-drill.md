# 0225 — what a migration rollback does to a database that has data in it

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_populated_rollback_drill.py` (7 tests, ~19.9 s)

## Context

[ADR 0216](0216-migration-reversibility.md) measured the rollback direction: which migrations
unapply, how far a single-app rollback cascades, and that a full rollback followed by a reapply
reproduces an identical column, index and constraint inventory. It also recorded two limits in
plain words — *"These are empty databases"* and *"No timing, locking or concurrency is
measured"* — and `docs/PHASE1_RELEASE_EVIDENCE.md` still carries both as open: nothing showed a
rollback with data in it, and nothing showed what happens when the database is busy while one is
attempted.

Those are the two questions an operator has to answer before authorizing a destructive step, and
neither is answerable from a schema exercise. Rolling back drops tables and columns; whether the
rows in them matter, which rows die with which migration, what is left inconsistent afterwards,
and what brings them back are properties of a *populated* database.

## Decision

`daroobank/test_populated_rollback_drill.py` runs the drill ADR 0216 left open. Each test creates
its own throwaway PostgreSQL database on the synthetic server (the same `throwaway_database()`
helper, the same dynamically registered `migration_probe` alias), migrates it, **populates every
one of the 23 project tables** with synthetic rows plus one staff account that wrote them, and
then rolls back — measuring rows, not only schema.

The fixture is pinned rather than incidental: `POPULATED` names the exact row count of all 23
tables (30 rows in total, 2 product presentations of which one is published, 2 price candidates, 1 import receipt with 2
items, 1 clinical draft with 1 review and 1 reference assertion, 1 login window, and one row in
each of the identity and revision tables), the first test asserts the database matches it, and
the populated schema must still report `no_selected_issues` under the same model-derived
inspection CI applies to the development database. A fixture that quietly stops filling a table
would otherwise turn every later measurement into a measurement of an empty table.

Two choices matter:

- **Rows are created through the models, not through raw SQL**, so the fixture has to satisfy
  every check constraint the schema enforces (`source_claim_scope_present`, the receipt
  consistency constraints, `receipt_item_single_domain`, the parent-before-child revision
  constraints, `candidate_suggestion_consistent`). What the drill measures is therefore what a
  real populated database looks like, including one price candidate whose `staged_by` is null —
  the attribution hole [ADR 0220](0220-actor-attribution-inventory.md) measured.
- **The busy case uses a second PostgreSQL session**, not a mock: an independent `psycopg`
  connection holds `SELECT … FOR UPDATE` on one product row while `migrate catalog zero` runs
  with `lock_timeout = 2s`, so the block is a real lock wait observed by the server.

## Measured behavior

| Measurement | Result |
|---|---|
| Populated throwaway database | 23 project tables, 30 rows, counts equal to the pinned fixture, plus 1 `auth_user` row; 32 tables, 31 applied migrations, inspection `no_selected_issues` |
| `migrate catalog zero` | destroys **23 of the 30 rows** — everything in catalog's 13 tables, pricing's 2 and `ingestion_importreceiptitem` — and leaves 7 rows in tables the cascade does not reach; 16 tables and 17 foreign keys remain, inspection reports `attention` |
| The receipt that survives it | `ingestion_importreceipt` still holds one row claiming `rows=2, created=2, duplicates=0` while `ingestion_importreceiptitem` no longer exists: the history is not merely shorter, it is internally inconsistent |
| Full rollback of all six apps | every project row is destroyed (30 → 0, `row_counts` empty) while the account that wrote them survives: `auth_user` keeps its 1 row and `django_session` remains, because no project migration touches Django's own apps |
| Reapply after a full rollback | inventory identical to the first migration and inspection clean, and **all 23 tables come back empty**: nothing in Django's rollback preserves contents |
| A copy taken beforehand | dumping all columns of 3 tables (4 rows) before the rollback and replaying them in foreign-key order after a reapply reproduces the rows exactly — the actor foreign keys still resolve because `auth_user` survived — and the restored rows are readable through the ORM |
| …and what the copy does not do | the next insert into a restored table fails with a duplicate-key `DatabaseError`, because the identity sequences still point at the ids the copy reused; `setval(pg_get_serial_sequence(…), max(id))` is part of the procedure, not an optional extra |
| A rollback while one row is locked | fails after `lock_timeout` with `OperationalError: canceling statement due to lock timeout` — and **leaves the database half undone**: 30 of 31 migrations still applied, 31 tables, 47 foreign keys, 28 of 30 rows, inspection `attention` |
| Why it stops where it stops | the plan for `catalog zero` is 11 migrations and is *not* ordered by app: `ingestion 0002` runs first, then `pricing 0002`, `pricing 0001`, then catalog 0008 down to 0001. Each migration commits on its own, so step 1 stayed undone — `ingestion_importreceiptitem` dropped, its 2 rows destroyed — while step 2 died on `DROP TABLE "pricing_pricecandidatereview" CASCADE` waiting for an `AccessExclusiveLock` on `catalog_productpresentation`, because dropping a child table has to take the foreign key off its parent |
| Repairing the half-rolled-back database | `migrate` forward restores the exact inventory (31 applied migrations, inspection clean) but the destroyed rows stay destroyed: `ingestion_importreceiptitem` returns with **0 rows** while the receipt above it still counts 2 |
| The same rollback once nothing holds a lock | completes: 20 applied migrations, 16 tables — the cascade ADR 0216 measured, now with the row loss quantified |

## Red checks

Seven, each reverted from a backup:

1. Pinning `catalog_productpresentation` at 3 rows instead of 2 fails the fixture test — the
   drill would otherwise measure a database it did not build.
2. Asserting the staff account is destroyed by a full rollback fails: `auth_user` keeps its row.
3. Asserting that reapplying migrations restores the 30 rows fails: the count is 0.
4. Asserting that a one-app rollback destroys no rows fails: 23 rows are gone.
5. Asserting that a blocked rollback leaves all 31 migrations applied fails: `ingestion 0002` is
   already unrecorded and its table is already dropped.
6. Asserting that a restored table accepts a new row without advancing its sequence **errors**
   with a duplicate-key violation.
7. Asserting that migrating forward brings the 2 dropped receipt items back fails: the table
   returns with 0 rows.

## Consequences

- A rollback plan for this schema cannot be "run `migrate <app> zero`". It has to say, in order:
  take a copy of the tables the cascade will drop, stop the writers, verify nothing holds a lock
  on any table the plan touches, set `lock_timeout` so a block fails fast instead of queueing
  behind it, run the rollback, and if it fails treat the database as half undone — re-migrate
  forward to a consistent schema and restore from the copy, because the rows the completed steps
  destroyed are gone.
- Identity sequences are part of any restore. Restoring rows without `setval` leaves the next
  insert failing, which is a second incident on top of the first.
- The receipt inconsistency is a property of the schema, not of the drill: import receipts count
  their items, and the items live in a table the catalog cascade drops while the receipt's own
  table survives. Any rollback of catalog leaves receipts that contradict the database.
- Nothing here is a backup, a recovery objective or a staging plan. The synthetic dump/restore
  drill remains separate and opt-in, and the *plan* — environment, owner, authorization for a
  destructive operation — still has no owner.

## Limitations

- **30 rows is a fixture, not a representative volume.** The drill measures what a rollback does
  to data, not how long it takes at production scale; duration, `VACUUM`, WAL volume and the
  behaviour of a long-running `ALTER TABLE` under real load are not measured.
- The busy case locks one row of one table with `SELECT … FOR UPDATE`. Other shapes of
  concurrency — an open transaction that wrote rows, a `CREATE INDEX CONCURRENTLY`, a running
  management command, a replicated standby — are not exercised.
- The copy round-trip covers 3 of 23 tables and uses raw `INSERT`s in foreign-key order. It shows
  what a restore has to contain; it is not a restore tool, and the append-only models that refuse
  `save()` and `delete()` on an existing primary key are deliberately bypassed by it.
- Only the six project apps are rolled back. Rolling back `auth`, `contenttypes` or `sessions` —
  which would destroy the accounts this drill relies on — is not measured.
- PostgreSQL only, on one synthetic server, with one role that can create databases and open a
  second session. Grants, ownership, extensions, tablespaces and a read-only runtime role are not
  involved.
