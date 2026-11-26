# 0215 — the authorization review's tables are generated, not typed

Date: 2026-11-26
Status: accepted
Document: `docs/AUTHORIZATION_REVIEW.md`
Code: `daroobank/authorization_review.py`
Suite: `daroobank/test_authorization_review_drift.py` (12 tests, ~0.01 s, no database)

## Context

The Phase 1 checklist carries an open gate reading *"complete endpoint-by-endpoint
authorization review, threat modeling and independent security assessment"*. Two
different things hide in it:

1. an **inventory** — every route the application serves, the requirement it declares,
   the methods it accepts, whether it can write and where each claim is measured; and
2. a **judgement** — whether those requirements are the right ones, whether the surface
   should exist, and whether it may go near production.

Before this ADR, part 1 existed but was spread across code: the ADR 0200 matrix declares
requirements for 41 routes, the ADR 0209 sweep pins the methods for all 43, the ADR 0199
inventory classifies which routes write and which in-flight test covers them, and the ADR
0202 matrix enumerates the 12 non-staff routes. Nothing collected them into one reviewable
document, and the obvious way to do that — typing a table by hand — would create a fourth
copy of the route names, one that goes stale silently.

Part 2 cannot be done in this repository: it needs an owner, and the project has not
assigned one. Fabricating a sign-off line would be worse than leaving the gate open.

## Decision

Split the two. Part 1 is **generated from the code** into
`docs/AUTHORIZATION_REVIEW.md`; part 2 is written down as unanswered questions with blank
owner, date and answer columns that a test keeps blank.

`daroobank/authorization_review.py` derives two markdown tables from:

* the live URL resolver — route names and URL patterns, so a route cannot be omitted;
* `test_staff_authorization_matrix.ROUTES` — the requirement each staff route declares;
* `test_staff_csrf_gate` and `test_staff_method_sweep` — which method group a route is in,
  and therefore the `Allow` set the ADR 0209 suite measured for it;
* `test_staff_write_route_inventory` — whether the route writes and which synchronized
  in-flight test covers it;
* `test_public_route_privacy_matrix.PUBLIC_ROUTES` — the probe rows and expected statuses
  for the non-staff surface.

The tables live between two `GENERATED` markers. `write_review()` replaces exactly that
block and refuses to rewrite a document whose markers are missing, so the prose around it
cannot be clobbered by a regeneration. `render_review()` prints the block without writing.

Two details mattered:

- **Order is fixed, not inherited.** `AUTH_ROUTES` in the matrix is a `frozenset`, and set
  iteration order follows the interpreter's hash seed. Iterating it to place the two
  authentication endpoints made the generated block differ between runs, and the drift test
  caught it on the first run after the change. The module now renders them through an
  explicit `AUTH_ORDER` tuple, asserted equal as a set to `AUTH_ROUTES`.
- **Evidence is per route, and honest about exclusions.** The ADR 0200 matrix deliberately
  excludes `staff_login` and `staff_logout`, and the ADR 0213 guard's suite measures the
  other 41 routes plus the binding that happens at login. Those two rows therefore carry an
  explicit evidence list rather than inheriting the base one, so the table does not claim
  coverage that no suite provides.

`daroobank/test_authorization_review_drift.py` re-renders and compares byte for byte, and
additionally asserts: the header counts match the resolver; the staff table's route names
are exactly the resolver's staff names in both directions; every staff row agrees with the
derived row in all five data columns and names a method set some suite pins; the non-staff
table covers exactly the resolver's non-staff names and accounts for every public probe
row; every ADR number cited in an evidence column has a document in
`docs/ARCHITECTURE_DECISIONS/`; every module named in a writes column exists, references
that route and still parks a write around a password invalidation; the document still
states its own limits (`not an approval`, `not a threat model`, `no MFA`, `DEBUG-only`,
`dormant-session residual`, `does not establish`, `Sign-off`, `runs to completion`,
`synthetic`, `fabrication`); the sign-off table's owner, date and answer cells are all
empty; and the Phase 1 checklist links the review.

## Measured behavior

The generated document reports **43 staff routes** and **12 non-staff routes** with 17
public probe rows, which is exactly what the resolver serves. Of the 43 staff rows, 36
declare `all of` a permission list, four declare `any of` one (the import-receipt and
ingestion-window inspection routes), one declares `is_staff` with no specific permission,
and the two authentication rows state their own requirement in prose — counts the drift
test pins, so they cannot go stale in this document either. 14 staff routes are marked as
writing, each
naming the in-flight test that covers it; the other 29 are marked read-only with the
reason the ADR 0199 inventory records. Twelve tests pass in ~0.01 s with no database and
under four different `PYTHONHASHSEED` values.

## Red checks

1. Dropping `sources.add_sourceclaim` from `staff_source_create`'s declared requirement in
   the ADR 0200 matrix — a one-token change in code the review is supposed to describe —
   fails **2** assertions: the generated block no longer matches, and the row no longer
   equals its derived counterpart.
2. Citing a nonexistent ADR `0299` in the evidence base fails **43** assertions: 41 row
   comparisons, the block comparison, and the citation check reporting `['0299'] != []`.

Both were reverted from backups; `git diff --stat` was clean afterwards.

## Limitations

- **This is not the review the gate asks for.** It is the inventory the review has to be
  based on. Nobody has judged whether a requirement is correct, and the document says so
  in a section the drift test keeps present. Threat modeling and an independent security
  assessment remain open.
- The sign-off table is empty by design and a test keeps it empty. That makes fabrication
  visible, but it also means the gate stays open until a real owner answers, and no
  engineering work in this repository can close it.
- Generated content is only as true as its inputs. If a suite stops covering a route
  without the matrix changing, the evidence column keeps citing it. The drift test checks
  that cited ADRs exist and that named modules mention their route; it cannot check that a
  suite still sends requests to every route it claims.
- The tables describe the URL surface only. Management commands, middleware behavior,
  signals and background jobs are not endpoints and are not listed.
- The document is a rendering of a DEBUG-only portal: `STAFF_PORTAL_ENABLED = DEBUG`, and
  every `/staff/…` request is answered 404 when the flag is off. Describing these routes
  precisely is not a recommendation to expose them.
