# 0229 — the two write paths that name nobody, and the decision written down for them

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_attribution_gap_plan.py` (12 tests, ~0.5 s)

## Context

[ADR 0220](0220-actor-attribution-inventory.md) measured attribution instead of assuming it: 19 of
the 24 project models name the account that appended them behind a protected foreign key and a
creation timestamp, no model records modification, and two places do not name anybody. The first is
`catalog.ProductPresentation`, the row the public reads. The second is price staging from
`manage.py stage_price_csv`, which writes a candidate with `staged_by_id IS NULL` that the portal
then refuses to let anybody review — and, because rows are reused on an identical payload, can never
acquire an actor later.

Both were recorded as measurements, and neither was decided. Meanwhile the requirements are written
down and are not optional: [SECURITY.md](../SECURITY.md) asks that audits record *"actor, role,
target, before/after versions or hashes, decision, time and request correlation"*, and
[PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) carries *"qualified legal/privacy and
clinical governance, source rights, retention, protected audit and explicit publication approval"*
as open. A reviewer who asks "who is accountable for this row?" gets a NULL and a document.

[ADR 0227](0227-read-audit-plan.md) settled the form for that situation: a decision without a price
tag is a guess, so the price gets measured and the decision gets written down for owners rather than
implemented by whoever happened to be editing the code.

## Decision

Write the decision down as [docs/ATTRIBUTION_GAP_PLAN.md](../ATTRIBUTION_GAP_PLAN.md) — a proposal,
explicitly not an approved control and explicitly without an owner — and measure three things ADR
0220 did not, so that the options are priced against what the code actually does:

1. **There is no publication step to attribute.** No non-test, non-migration module creates a
   presentation; `published=True` appears in project code exactly once, as a read filter; and
   `verified_at` is never assigned by anything, although a database constraint and `clean()` both
   require it on a published row. The catalog's rows can only arrive by migration, by shell or by
   restore, so option E is not "add a column" but "build a feature".
2. **A command-line import bypasses the whole receipt layer.** The staff route stages through
   `ingestion.receipts.stage_price_with_receipt`, which refuses a missing actor, rechecks it, and
   writes one `ImportReceipt` — whose `actor` is a **required** `PROTECT` foreign key — plus one
   item per row. The command writes no receipt and no items, so a command-line staging appears in no
   import inventory, has no manifest and no per-row outcome record.
3. **The command is the only write path that is not debug-gated.** Neither the command module nor
   `pricing/importer.py` mentions `DEBUG`, and staging succeeds with debug off, while the projection
   repair, the staff portal and the login throttle all refuse to operate outside a debug
   environment.

The plan then names six options with a counted price each, seven decisions owners have to make, and
what has to be verified before any implementation. Nothing is implemented.

## Measured behavior

| Measurement | Result |
|---|---|
| Published catalog write paths | exactly one: `catalog/projection_repair.py`'s `.update(...)`, limited to the derived columns `search_text` and `irc_normalized`; no create call site anywhere in project code |
| Publication fields | `published=True` occurs once in project code, inside the read filter `published=True, verified_at__isnull=False` in `catalog/services.py`; no module naming `ProductPresentation` assigns `.published` or `.verified_at`, or passes either to an ORM write; `verified_at` is nullable and has no default |
| The command's surface | four options — `--source-name`, `--source-url`, `--commit`, `--attest-authorized` — and no `--staged-by`; 12 project commands and 24 options in total |
| A command-line staging | one `PriceCandidate` with `staged_by_id IS NULL` and `source_rights_attested=True`, **zero** `ImportReceipt` rows and **zero** items |
| The same CSV through the route | one receipt with `kind='price'`, `actor_id` the stager and one item pointing at the candidate, which is staged with `staged_by_id` set; `ImportReceipt.actor` is `null=False` and `PROTECT` |
| Debug gating | neither `stage_price_csv.py` nor `pricing/importer.py` contains `DEBUG`, and a staging with `override_settings(DEBUG=False)` still writes the candidate and still writes no receipt; as a positive control `catalog/projection_repair.py` does contain `DEBUG` and `settings.py` computes `STAFF_PORTAL_ENABLED = DEBUG` |
| The command's test surface | 8 test modules name it, in 16 mentions, and 8 of those calls stage with `commit=True`; one of the three operator documents names it |
| The plan's shape | six options in order A–F, each with a price and a limit; seven numbered decisions in order; two requirements quoted verbatim from the documents that state them; every module, decision record and document it names exists |
| Implementation | none: no `--staged-by` option, no `published_by`, `published_at`, `actor` or `created_at` field on the catalog record, and `stage_csv`'s `staged_by` still defaults to `None` |

## Red checks

Eight regressions, each applied alone to one file and reverted afterwards:

| Regression | Result |
|---|---|
| Decision 7 loses its number in the plan | 1 failure: the seven decisions in order |
| A quoted requirement is paraphrased (`before/after versions or hashes`) | 1 failure: the plan quotes the requirements it answers |
| The plan claims an owner | 1 failure: the proposal wording |
| The plan names `daroobank/test_command_inventory.py`, which does not exist | 1 failure: every named module exists |
| Option F is renamed in the options table | 1 failure: every option names a price and a limit |
| `--staged-by` is added to the command's parser | 2 failures: the counted command surface, and "the plan implements nothing" |
| `published_by` is added to `ProductPresentation` | 1 failure: "the plan implements nothing" |
| A `DEBUG` comment is added to `pricing/importer.py` | 1 failure: the command stages with debug off and no module gates it |

Each patch was asserted to apply before the run and each revert was compared byte for byte with
`filecmp` against a copy taken beforehand, so a red check that silently did not apply cannot pass.

## Consequences

* The two gaps now have a costed proposal and a suite that re-measures them, so choosing an option
  is a documented event rather than an edit: option B moves two pins in this suite and the option
  count ADR 0219 records, option E moves one pin here plus the schema, migration, drill and actor
  pins of ADRs 0216, 0220 and 0225, and option C moves the command surface, its 8 test modules and
  one operator document.
* `docs/PHASE1_RELEASE_EVIDENCE.md` links the plan from the governance row, `docs/SECURITY.md` and
  `docs/DEVELOPMENT_GUIDE.md` state what a command-line staging does and does not record, and
  ADR 0220's limits point here.
* Nothing is attributed. No row gained an actor, no command-line import gained a receipt, no
  publication path exists, and the rows already staged from a shell are still unreviewable.

## Limitations

* The prices are **counted, not prototyped**. No option was built and reverted, so no cascade was
  run and no schema was measured after a change; a count of the pins that move is a lower bound on
  the work, which is why the plan says so in its own words.
* The scans are literal and AST based. A write through `setattr`, a raw SQL statement, a bulk update
  on a queryset held in a variable, or a signal would not be seen. The publication-field scan reads
  only modules that name `ProductPresentation`, and only attribute assignments and ORM write
  keywords, because `published` is also a local variable in the price importer where it holds a
  parsed source date.
* The receipt measurement is one CSV of one row through two paths. It does not measure a large
  import, a refused one, a conflicting one, or the rendering of the import inventory route, which
  ADR 0206 covers.
* `override_settings(DEBUG=False)` changes the setting at runtime, not in a fresh process, so values
  computed at import time — `STAFF_PORTAL_ENABLED` among them — stay as they were. The check proves
  that the command does not consult `DEBUG`; it does not prove that a non-debug deployment behaves
  identically, which is what `daroobank/test_nondebug_configuration.py` uses fresh processes for.
* The plan decides nothing and has no owner. Six options and seven decisions stay open, and decision
  5 — what happens to the rows that already exist — has to be answered before any of the others can
  be implemented without leaving dead rows behind.
