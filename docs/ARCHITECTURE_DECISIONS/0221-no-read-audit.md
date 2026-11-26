# 0221 — nothing records that a read happened

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_no_read_audit.py` (8 tests, ~0.9 s)

## Context

[ADR 0220](0220-actor-attribution-inventory.md) measured the write side of attribution: 19 of
the 23 project models name the account that appended them. The other half of an audit question
— "who looked at this?" — has no answer in this system, and nothing said so.

That matters for three concrete reasons here. [SECURITY.md](../SECURITY.md) lists audit among
the controls this product is supposed to have and asks that audit records carry actor, role,
target, decision, time and request correlation. `daroobank/settings.py` opens with the comment
that the staff portal is restricted to development *until MFA, throttling and audit exist*. And
[the operations runbook](../OPERATIONS_RUNBOOK.md) tells an incident responder to "review
access/audit logs after restoration" — an instruction that cannot be followed inside this
application, because there is no such log to review.

An absence nobody wrote down is indistinguishable from an absence nobody noticed, and this one
is the kind that gets discovered during an incident.

## Decision

Record the absence, pin it, and correct the one operational instruction that assumed otherwise.
No logging was added: adding an access log is a design decision with retention, PHI and
tamper-resistance consequences that this project has not made (and that
[ADR 0218](0218-no-django-admin.md) already noted when it observed that no `django_admin_log`
table exists either).

`daroobank/test_no_read_audit.py` pins the absence from four directions — configuration, code,
schema and behavior — so that introducing read recording is a deliberate act with its own
decision record rather than a side effect of adding a middleware.

## Measured behavior

| Measurement | Result |
|---|---|
| `settings.LOGGING` | `{}`: Django's default, no handler, no logger, no file, no syslog |
| Project modules importing `logging` | none, across the seven project packages excluding tests and migrations, checked by parsing the AST; as a positive control the same scan does find `catalog/intake.py` importing `json` |
| `settings.MIDDLEWARE` | exactly twelve entries in a pinned order; seven are project middleware (CSP, health-probe privacy headers, early-redirect privacy headers, trusted-proxy scheme, public-read privacy headers, staff privacy headers, staff session guard) and none has a record-like name. The only one that acts on a request beyond setting headers is the session guard, and it *deletes* sessions |
| Schema | exactly the 32 tables ADRs 0216 and 0218 pin, by name; no `django_admin_log`; no project model whose name contains an `access`, `audit`, `event`, `log`, `track` or `visit` token — matched on camel-case words, so `StaffLoginWindow` does not match on "log" |
| Tables that do record change | `catalog_formulationrevision`, `catalog_identitypackagerevision`, `catalog_ingredientrevision` and `catalog_productrevision` each carry `recorded_by_id` and `created_at`: the schema records writes and reads have no counterpart |
| Staff read sweep | a fully permitted account GETs all 43 staff routes with a missing primary key (`999999999`, `kind=ingredient`): 19×200, 18×404, 6×405, **0×403**; all 23 project table counts unchanged, and the `django_session` count unchanged by the sweep while the login that precedes it adds exactly one row |
| Public read sweep | an anonymous caller GETs all 12 public routes: 8×200, 4×404, 0×403; counts unchanged and **no session row created** |
| Positive control | the same counter used by both sweeps sees an ORM insert (+1, then back to baseline), so "unchanged" is a measurement and not a stuck gauge |

## Red check

| Regression | Failures |
|---|---|
| `import logging` plus a module logger appended to `catalog/services.py` | the import pin named the module |
| A `LOGGING` dictionary added to `daroobank/settings.py` | the configuration pin failed |
| An `AccessLog` model in `ingestion` with its migration **and** an `AccessLogMiddleware` appended to `MIDDLEWARE` that writes one row per response | four tests failed: the middleware pin, the 32-table inventory (33), and both sweeps, which counted 43 rows after the staff sweep and 12 after the public one |
| The same `AccessLog` model with **no** migration | the model-name pin failed and the three database tests errored on the missing table — a model without a migration is its own failure |

All four were reverted from `/tmp` backups; `git status --short` afterwards showed only the new
suite, `makemigrations --check --dry-run` detected nothing, and the suite passed again.

## Limits

- This pins an absence **inside the process**. A reverse-proxy access log, PostgreSQL's
  `log_statement`, a host audit daemon or an APM agent would all be invisible to it. Whether
  one of those exists is a deployment question this suite cannot answer, and
  [DEPLOYMENT.md](../DEPLOYMENT.md) does not arrange one.
- The status distribution of both sweeps is pinned, so a route that starts answering 200 where
  it answered 404 fails this suite for a reason that has nothing to do with auditing. The sweep
  uses missing primary keys precisely to stay stable, but it is still a shape pin.
- Only HTTP routes are swept. Reads performed by a management command (`list_staff_sessions`,
  the `inspect_*` family) or by direct SQL are outside it.
- Row *counts* are compared, not contents, so a read that deleted one row and inserted another
  would net out. Nothing here would notice a read that wrote to a file, a cache or an external
  service.
- The suite does not judge whether read logging is required. For a catalog adjacent to clinical
  data, "who looked at this" may be a legal or clinical question; that decision belongs to the
  governance gate and stays open. What is now recorded is that the precondition `settings.py`
  names is unmet, and that the runbook's instruction to review access logs cannot be followed
  inside this application.
