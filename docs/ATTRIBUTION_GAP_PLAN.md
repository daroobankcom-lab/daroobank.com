# Proposed attribution for the two write paths that name nobody, and the decisions they require

This document is a **proposal**, not an implemented or approved control, and it has no owner.
[ADR 0220](ARCHITECTURE_DECISIONS/0220-actor-attribution-inventory.md) measured that 19 of the 24
project models name the account that appended them behind a protected foreign key and a creation
timestamp, and that two places do not: the published catalog record, and price staging from the
command line. Both were recorded as measurements and neither was decided. This document writes the
decision down in the form [READ_AUDIT_PLAN.md](READ_AUDIT_PLAN.md) and
[MFA_IMPLEMENTATION_PLAN.md](MFA_IMPLEMENTATION_PLAN.md) already use — what is true today, what the
options cost, and what owners have to choose before any code changes. All data stays synthetic, the
staff portal stays debug-only, and nothing here authorizes importing real price data or publishing
a real catalog row.

## Gap one: the published catalog names nobody, and nothing publishes it

`catalog.ProductPresentation` is the row the public reads. It has no actor column and no creation
timestamp, so the schema cannot say who put a published product there or when. Three measurements
make the gap sharper than "a column is missing":

* **There is no publication step to attribute.** An AST scan of every non-test, non-migration
  project module finds no `create`, `get_or_create`, `bulk_create` or instantiation of the model —
  ADR 0220 pinned the absence of a create call site — and `published=True` appears in project code
  exactly once, as a **read filter** in `catalog/services.py`. `verified_at` is never assigned
  anywhere either: a query filter and a publication check in `catalog/services.py` read it, two
  templates and one serialization render it, and `clean()` plus the database constraint require it
  on a published row. So no code path publishes a presentation or sets its verification date; rows
  can only arrive by migration, by shell, or by restore.
* **The one write that does exist records nothing.** `catalog/projection_repair.py` updates at most
  the two derived columns `search_text` and `irc_normalized`, under a signed short-lived token,
  `--confirm-synthetic` and a debug-only guard, and ADR 0220 measured that it creates no row in any
  project table: no receipt, no revision, no actor.
* **The constraint that does exist pins a date nobody sets.** `catalog_published_requires_verified`
  requires `verified_at` to be set on a published row, and `clean()` repeats it, so a published row
  always claims a verification date — while nothing in the application is able to write one.

What this means for a reviewer: "who approved this product for publication, and when" has no answer
inside the database, for any row, however it arrived.

## Gap two: command-line price staging names nobody and writes no receipt

`manage.py stage_price_csv <path> --source-name … --source-url … --commit --attest-authorized` calls
`pricing.importer.stage_csv` without `staged_by`, so the candidate it writes has
`staged_by_id IS NULL` (ADR 0220 measured the row and the portal's response to it). Four further
measurements:

* **The receipt layer is bypassed entirely.** The staff route stages through
  `ingestion.receipts.stage_price_with_receipt`, which refuses a missing actor with
  `PermissionDenied`, rechecks it through `daroobank.actor_recheck.recheck_actor`, and writes one
  `ImportReceipt` — whose `actor` is a **required** `PROTECT` foreign key — plus one
  `ImportReceiptItem` per row. The command writes **no receipt and no items**, so a command-line
  import has no manifest, no per-row outcome record and no entry in the import inventory a reviewer
  reads at `/staff/operations/imports/`.
* **The command is not gated on debug.** Neither `pricing/management/commands/stage_price_csv.py`
  nor `pricing/importer.py` reads `settings.DEBUG`, while the staff portal, the projection repair
  and the login throttle all refuse to operate outside a debug environment. The one write path with
  no actor and no receipt is the one that works in a non-debug deployment.
* **The attestation has no name on it.** `--attest-authorized` is required to commit and is stored
  on the row as `source_rights_attested=True`, which is the project's record that collection and
  internal storage are permitted. Through the route that claim is bound to an account; from the
  command line it is bound to nobody, and the row still looks attested.
* **The result is permanent.** Rows are reused on an identical payload (`get_or_create` on source
  URL, record id and payload digest), so replaying the same CSV through the route reuses the row and
  leaves `staged_by` NULL: a candidate first staged from the command line never acquires an actor.
  The portal is honest about it — the queue lists the row, the detail page shows the stager as
  «نامشخص» and states that review through this path is not possible, `can_review` is `False` and no
  review form is rendered — and offers no way out. Nothing in the project deletes, adopts or
  re-attributes such a row, so it can never become a reviewed price.

## Why this is a decision rather than a bug fix

Every option below changes who is accountable for a row, whether a self-declared name counts as
attribution, and what happens to rows that already exist. Those are governance questions:
`docs/SECURITY.md` asks that audits record *"actor, role, target, before/after versions or hashes,
decision, time and request correlation"*, `docs/PHASE1_RELEASE_EVIDENCE.md` carries *"qualified
legal/privacy and clinical governance, source rights, retention, protected audit and explicit
publication approval"* as open, and the source-rights attestation exists because permission has to
be claimed before data is stored. A test can measure that a column is NULL; it cannot decide whether
a shell operator's word is an acceptable substitute for an account.

## Options and what each costs

The prices below are counted, not prototyped: they name the pins and documents that move, measured
by scanning the suites and files that hold them. No option was implemented and reverted, so no
cascade was run, and a count of pins is a lower bound on the work.

| Option | What changes | Price, counted | What it still does not answer |
|---|---|---|---|
| **A. Leave both gaps as measured** | nothing | ADR 0220 and this document are the record; the pins already hold | Who approved a published product, and who claimed source rights for a CLI-staged price |
| **B. `--staged-by <username>` on the command** | the command resolves a username to an account, checks it is authenticated, active, staff and holds both pricing permissions, and passes it to `stage_csv` | no schema change and no migration; one new option, which `daroobank/test_command_documentation.py` requires to be documented in the operator documents that name the command (`docs/DEVELOPMENT_GUIDE.md` is the only one); three tests in `daroobank/test_actor_attribution_inventory.py` assert `staged_by_id IS NULL` and would be rewritten; ADR 0219's option count moves from 24 to 25; ADR 0220's measured table moves | The name is self-declared — no credential, no session, no proof — and the portal forbids self-review, so an operator who names themselves creates a row only somebody else can review |
| **C. Command staging requires an authenticated session** | the command's `--commit` mode is removed; all staging goes through the staff route | the gap closes completely and receipts become unavoidable; but `--commit` is one of the two write flags `test_command_documentation.py` counts, and the command is named by 8 test modules — 16 mentions, 8 of them calls that stage with `commit=True` — and by one of the three operator documents, all of which move; ADRs 0219 and 0220 are superseded | Bulk staging from a shell becomes impossible, which is a workflow decision for whoever operates imports, and the debug-only portal becomes the only staging path |
| **D. Keep the command, make its rows explicitly terminal** | actor-less rows get a state the queue names, plus a documented procedure for deleting or re-staging them | one column or one derived status, a queue and detail template change, and the row-reuse rule has to decide whether a re-staged payload may adopt an actor; ADR 0220's replay measurement moves | Nobody is named, so the source-rights attestation is still unattributed; and a procedure with no owner is a document, not a control |
| **E. `published_by` and `published_at` on the catalog record** | an actor foreign key (`PROTECT`) plus a timestamp, and a publication service that sets them | two columns on a 33-table, 279-column schema, one more catalog migration (8 → 9 for the app, and 17 → 18 project migrations in total), the attributed-model count moves 19 → 20 and the unattributed set shrinks, the rollback drill's fixture gains values for both, and a backfill decision is required for every row that already exists; the migration and reversibility pins of ADR 0216 and ADR 0225 move | There is no publication step to attach them to, so this option builds a feature — a route, a permission, a review — rather than adding a column, and rows loaded by shell or restore still have no publisher |
| **F. Declare the catalog seed data loaded outside the application** | a document that says published rows arrive from outside, who loads them, how `verified_at` is set, and how a load is authorized | no code; `docs/DATA_SOURCES.md`, `docs/OPERATIONS_RUNBOOK.md` and this plan's gap one are rewritten, and the absence of a publication path is pinned rather than fixed | The database still cannot answer who published a row, and the answer lives in a procedure nobody has approved |

## Decisions required before implementation

1. **Is a self-declared name attribution?** Option B records a username typed into a shell. Decide
   whether that is admissible as `staged_by`, admissible only with a second control (a logged
   operator, a signed command, a two-person rule), or inadmissible — in which case only C or D
   remain, and the workflow cost of C has to be accepted by whoever runs imports.
2. **May a write path exist outside debug at all?** The command is the only project write path that
   is not debug-gated. Decide whether that is intended for operations, or whether every write path
   carries the same guard as the portal, the projection repair and the login throttle.
3. **Does an import without a receipt count as an import?** `ImportReceipt.actor` is required, so a
   receipt forces decision 1 first. If the command keeps staging without an actor it cannot write a
   receipt, and the receipts inventory is incomplete by design; that has to be written into the
   deployment guide rather than discovered by a reviewer.
4. **What is an unattributed rights attestation worth?** Decide whether
   `source_rights_attested=True` with no actor is admissible, and who is accountable for the
   source-rights claim on rows already staged from a shell.
5. **What happens to the rows that already exist?** Every option leaves actor-less rows
   unreviewable. Deleting them is destructive with no owner and no backup (ADR 0225 measures what a
   rollback destroys, and nothing measures a targeted delete); adopting them manufactures
   attribution retroactively; leaving them means the queue lists rows nobody can ever act on.
6. **Does the published catalog need a publisher, or a statement that it has none?** Decide between
   E and F. E is a feature with a backfill; F is a document with an owner. Until one is chosen, the
   schema requires a verification date no code can write, and the public reads rows whose origin the
   database cannot state.
7. **Where the record of a command invocation lives.** A command is not a request: no session, no
   request correlation, and — per [READ_AUDIT_PLAN.md](READ_AUDIT_PLAN.md) — no read audit and no
   process log, because `LOGGING` is `{}`. Attributing a command therefore means writing a row or
   shipping a log outside the application, and the second is the same undecided question that plan
   records.

## Verification before any implementation

- Synthetic tests cover the chosen path end to end: the command or service, the row it writes, the
  receipt and its items, the actor recorded, and the portal's ability to review the result.
- A self-declared actor, if one is accepted, is proven to be rechecked against the account's current
  flags and permissions at write time, following `daroobank/actor_recheck.py`, and is proven **not**
  to be trusted when the account no longer exists or has lost a permission.
- The receipts inventory is shown to list every import the chosen path can produce, and to refuse to
  show an import it has no receipt for.
- The debug gate, if one is added, is measured in both states, in a fresh process, the way
  `daroobank/test_nondebug_configuration.py` measures the other guards.
- Any schema change is run through the rollback drill and the migration-reversibility suites, with
  their pins recomputed rather than deleted, and with the backfill's effect on existing rows
  measured on a populated throwaway database.
- Superseding entries are written for ADRs 0219 and 0220 with their pins recomputed, and
  `docs/SECURITY.md`, `docs/DEVELOPMENT_GUIDE.md`, `docs/PRICE_DATA_MODEL.md`,
  `docs/PHASE1_RELEASE_EVIDENCE.md` and this plan are updated in the same change.
- Named owners record operational, security, legal/privacy and data-governance approval.
  Implementing these tests does not by itself attribute a row, authorize an import, approve a
  publication path or close any Phase 1 gate.
