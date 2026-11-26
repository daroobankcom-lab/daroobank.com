# 0220 — actor attribution is a schema property, and the published catalog has none

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_actor_attribution_inventory.py` (10 tests, ~0.8 s)

## Context

"Who did this, and when?" is the first question an audit asks, and [ADR 0218](0218-no-django-admin.md)
removed the one Django component that would have kept a `django_admin_log` row for
administrative changes. What this project has instead is a schema in which every staff write
appends a row — a draft, a review, a revision, a receipt — carrying a foreign key to the
account responsible and a creation timestamp. Nothing is updated in place, so there is no
modification timestamp anywhere and none is needed.

That property was never written down or pinned, and two places where it does not hold are
exactly the places a reviewer will ask about:

- `catalog.ProductPresentation` — the published catalog record the public reads — has no actor
  column and no creation timestamp, and no code path in the project creates one. Rows arrive
  from outside the application.
- `pricing.PriceCandidate.staged_by` is the one actor column that may be empty. Staging through
  the staff import route names the session account; staging through `manage.py stage_price_csv`
  names nobody. [ADR 0195](0195-shared-write-actor-recheck.md) records that actor-less CLI
  staging is deliberate, but nothing measured what it costs downstream.

## Decision

Measure the attribution baseline and pin it with `daroobank/test_actor_attribution_inventory.py`,
and write the operator-facing consequence into the development guide. No behavior changed.

The suite states the inventory as data (a pinned label-to-actor-field map, a pinned
label-to-creation-field map, the four unattributed models and why) rather than as a rule to be
re-derived, so that a change is a deliberate documentation event; and it measures the two
exceptions behaviorally on PostgreSQL rather than only structurally.

## Measured behavior

| Measurement | Result |
|---|---|
| Project models | 23 across six apps; 19 carry a foreign key to the account model, 4 do not |
| The 19 actor columns | `staged_by` (product and price candidates), `reviewer` (the five review models), `recorded_by` (identity and source drafts and revisions), `author` (clinical draft), `actor` (import receipt); every one is `on_delete=PROTECT`, so deleting an account cannot erase attribution |
| Nullability | 18 of 19 are `NOT NULL`; the single nullable actor column is `pricing.PriceCandidate.staged_by` |
| Creation timestamps | all 19 attributed models have an `auto_now_add` timestamp — `created_at` on 16, `collected_at` on the two candidates, `recorded_at` on `SourceClaim`; none of the 4 unattributed models has one |
| Modification timestamps | zero `auto_now` fields in the project: the schema can say when a row appeared, never when one changed |
| Unattributed models | `catalog.ProductPresentation` (published catalog), `catalog.FormulationComponent` and `ingestion.ImportReceiptItem` (children whose parent link is required and `PROTECT` and whose parent is attributed), `staff_security.StaffLoginWindow` (a synthetic throttle row keyed by an address digest) |
| Published catalog write paths | `ProductPresentation` is named by exactly seven non-test, non-migration project modules and has exactly one write call site, `catalog/projection_repair.py` `.update(...)`; there is no create call site. As a positive control the same scan finds `sources/services.py` `.get_or_create(...)` for `SourceClaim` |
| A projection repair, on PostgreSQL | reports `status: repaired` with `fields: {irc_normalized, search_text}`, leaves every other column of the row byte-identical, and creates **no row in any of the 23 project tables** — the only in-app write to the published catalog leaves no attribution anywhere |
| `stage_price_csv --commit --attest-authorized` | creates a candidate with `staged_by_id IS NULL`; a reviewer holding `pricing.review_pricecandidate` gets a 200 on `/staff/prices/<pk>/` in which `display_stager` is `None`, `can_review` is `False` and `review_form` is `None` |
| The same CSV through the route path | `stage_csv(..., staged_by=account)` — what `pricing/staff_views.py` passes — names the account, and the same reviewer sees `display_stager` set, `can_review` `True` and a review form |
| Replaying an unattributed row | the identical payload through the route reuses the row (`get_or_create` on source URL, record id and payload digest), so a candidate first staged from the command line **never** acquires an actor and stays unreviewable in the portal |

## Red check

Five regressions, each applied alone and reverted (backups in `/tmp/*.rc.bak`):

| Regression | Failures |
|---|---|
| A `ProductPresentation.objects.create(...)` call site added to `catalog/services.py` | the write-path pin listed two sites instead of one |
| `catalog.ProductCandidate.staged_by` made nullable | the nullable-column pin named two models instead of one |
| An `auto_now=True` field added to `PriceCandidate` | the modification-timestamp pin failed (and three database tests errored on the missing column, since a model field without a migration is its own failure) |
| `candidate.display_stager is not None` removed from the portal's `can_review` rule | both command-line staging tests failed: an unattributed candidate became reviewable |
| The importer made to fill in `staged_by` when an existing row is replayed | the replay test failed: an unattributed candidate acquired an actor |

After all five reverts the suite passed again with a clean `git diff --stat`.

## Limits

- This is attribution, not an audit log. Nothing measured here is tamper-resistant, nothing is
  retained under a policy, no row records a change to another row, reads are not recorded, and
  no management command — including the projection repair and the CSV stager — records who ran
  it. The "protected audit" gate stays open.
- The write-call-site scan sees only literal `Model.…` receivers. An instance `.save()`, a
  variable-bound queryset (the three catalog revision models are created through a
  `link_model.objects.create(...)` call and so show zero literal sites) or raw SQL is invisible
  to it; the pinned module list carries part of the weight instead.
- The inventory pins the model set, so adding any model fails a test here whether or not it is
  attributed. That is deliberate friction, not a claim that the current set is complete or
  correct.
- `can_review` also depends on payload status, rights attestation, the review permission and the
  reviewer not being the stager. The tests hold those constant, so they isolate the attribution
  term rather than characterizing the whole rule.
- Whether an unattributed candidate *should* be reviewable, and whether the command-line stager
  should record a self-asserted operator, are governance decisions. Recording a name typed into
  a shell argument would be an assertion, not evidence, and would not close the gap.
  [ADR 0229](0229-attribution-gap-plan.md) writes those decisions down as a costed proposal —
  six options, seven decisions, no owner — and measures three things this record did not: that no
  code path publishes a presentation or sets its verification date, that a command-line staging
  writes no import receipt and no items, and that the command is the only write path not gated
  on debug mode.
