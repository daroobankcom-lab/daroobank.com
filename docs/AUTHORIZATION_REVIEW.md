# Endpoint-by-endpoint authorization review

Generated 2026-11-26 from the live URL resolver and the pinned staff suites.

**Status: the inventory is derived and drift-checked; the judgement is unsigned.** This
document is not an approval, not a threat model, not a percentage complete, and not
evidence that any route below may be exposed. Owners and dates are deliberately blank:
the project must assign them.

## Why this exists

The Phase 1 gate asks for a complete endpoint-by-endpoint authorization review
([Phase 1 release evidence](PHASE1_RELEASE_EVIDENCE.md)). Two different things hide in
that sentence:

1. an **inventory** — every route the application serves, the requirement it declares,
   the methods it accepts, whether it can write, and where each claim is measured; and
2. a **judgement** — whether those requirements are the right ones, whether this surface
   should exist at all, and whether it may go near production.

Part 1 is derivable from the code and can be held true by a test. Part 2 needs an owner.
So part 1 is generated here, and part 2 is listed at the end as unanswered questions.

A hand-typed inventory would be the fourth place route names live, after `urls.py`, the
ADR 0200 matrix and the ADR 0199 write-route inventory, and it would go stale. Every
table below is therefore produced by `daroobank/authorization_review.py` from the live
resolver and from the pinned suites, and `daroobank/test_authorization_review_drift.py`
re-renders it and fails when the document disagrees with the code.

## How to regenerate

```
. .cache/pg-local.env && .venv/bin/python -c "import os, django; \
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'daroobank.synthetic_test_settings'); \
    django.setup(); from daroobank.authorization_review import write_review; \
    print(write_review())"
```

`write_review()` replaces everything between the two `GENERATED` markers in this file and
prints the length of the block it wrote; it refuses to touch a document whose markers are
missing. Print `render_review()` instead to see the tables without writing them. If the
document and the code disagree, `daroobank/test_authorization_review_drift.py` fails —
that is the point.

## What the columns mean

| Column | Source | Meaning |
|---|---|---|
| Route | the live resolver | the reverse name in `daroobank/urls.py` |
| URL pattern | the live resolver | the pattern string; the site root's pattern is empty and is shown as `(site root)` |
| Allowed methods | `test_staff_method_sweep.EXPECTED_ALLOW` | what the `Allow` header names after a rejected method (ADR 0209) |
| Requirement | `test_staff_authorization_matrix.ROUTES` | the permission shape the route declares: `all of` every listed permission, or `any of` one (ADR 0200–0201) |
| Writes | `test_staff_write_route_inventory` | whether the route can commit a change, and which synchronized in-flight test covers it (ADR 0192–0199) |
| Evidence | ADR files under `docs/ARCHITECTURE_DECISIONS/` | the suites that actually send requests to this route |

Evidence entries are ADR numbers, not coverage percentages and not sign-offs.
`0200, 0209` means those suites send requests to this route and assert the statuses
recorded in them; it does not mean a person reviewed the route. The ADR 0200 matrix
deliberately excludes the two authentication endpoints, and the ADR 0213 guard's suite
measures the other 41 routes plus the session binding that happens at login, which is why
those two rows carry an explicit evidence list of their own.

<!-- GENERATED BEGIN: python -m daroobank.authorization_review -->
Counts derived from the live resolver: **43 staff routes** and **12 non-staff routes**, 17 public probe rows.

## Staff routes

Requirement columns are what the route declares; the evidence columns are the ADRs whose suites measure it.

| Route | URL pattern | Allowed methods | Requirement | Writes | Evidence |
|---|---|---|---|---|---|
| `staff_workspace` | `staff/` | `GET, HEAD` | `is_staff`, no specific permission | no — read-only index | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_sources` | `staff/sources/` | `GET, HEAD` | all of `sources.view_sourceclaim` | no — read-only list | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_source_date_inspection` | `staff/sources/dates/` | `GET, HEAD` | all of `sources.view_sourceclaim` | no — read-only inspection | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_source_detail` | `staff/sources/<int:pk>/` | `GET, HEAD` | all of `sources.view_sourceclaim` | no — read-only detail | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_source_review_inspection` | `staff/sources/<int:pk>/reviews/inspection/` | `GET, HEAD` | all of `sources.view_sourceclaim` | no — read-only inspection | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_source_create` | `staff/sources/new/` | `GET, POST` | all of `sources.view_sourceclaim`, `sources.add_sourceclaim` | yes — `daroobank/test_staff_inflight_write.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0192–0199 |
| `staff_source_review` | `staff/sources/<int:pk>/review/` | `POST` | all of `sources.view_sourceclaim`, `sources.review_sourceclaim` | yes — `daroobank/test_staff_inflight_write.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205, 0192–0199 |
| `staff_products` | `staff/products/` | `GET, HEAD` | all of `catalog.view_productcandidate` | no — read-only list | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_product_detail` | `staff/products/<int:pk>/` | `GET, HEAD` | all of `catalog.view_productcandidate` | no — read-only detail | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_product_review_inspection` | `staff/products/<int:pk>/reviews/inspection/` | `GET, HEAD` | all of `catalog.view_productcandidate` | no — read-only inspection | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_product_upload` | `staff/products/import/` | `GET, POST` | all of `catalog.view_productcandidate`, `catalog.add_productcandidate` | yes — `daroobank/test_staff_inflight_stage_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0192–0199 |
| `staff_product_sample` | `staff/products/import/sample/` | `GET, HEAD` | all of `catalog.view_productcandidate`, `catalog.add_productcandidate` | no — static sample download | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_product_review` | `staff/products/<int:pk>/review/` | `POST` | all of `catalog.view_productcandidate`, `catalog.review_productcandidate` | yes — `daroobank/test_staff_inflight_review_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205, 0192–0199 |
| `staff_prices` | `staff/prices/` | `GET, HEAD` | all of `pricing.view_pricecandidate` | no — read-only list | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_price_detail` | `staff/prices/<int:pk>/` | `GET, HEAD` | all of `pricing.view_pricecandidate` | no — read-only detail | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_price_review_inspection` | `staff/prices/<int:pk>/reviews/inspection/` | `GET, HEAD` | all of `pricing.view_pricecandidate` | no — read-only inspection | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_price_upload` | `staff/prices/import/` | `GET, POST` | all of `pricing.view_pricecandidate`, `pricing.add_pricecandidate` | yes — `daroobank/test_staff_inflight_stage_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0192–0199 |
| `staff_price_sample` | `staff/prices/import/sample/` | `GET, HEAD` | all of `pricing.view_pricecandidate`, `pricing.add_pricecandidate` | no — static sample download | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_price_review` | `staff/prices/<int:pk>/review/` | `POST` | all of `pricing.view_pricecandidate`, `pricing.review_pricecandidate` | yes — `daroobank/test_staff_inflight_review_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205, 0192–0199 |
| `staff_clinical_drafts` | `staff/clinical/` | `GET, HEAD` | all of `clinical.view_clinicaldraft` | no — read-only list | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_clinical_inspection` | `staff/clinical/inspection/` | `GET, HEAD` | all of `clinical.view_clinicaldraft` | no — read-only inspection | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_clinical_detail` | `staff/clinical/<int:pk>/` | `GET, HEAD` | all of `clinical.view_clinicaldraft` | no — read-only detail | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_clinical_review_inspection` | `staff/clinical/<int:pk>/reviews/inspection/` | `GET, HEAD` | all of `clinical.view_clinicaldraft` | no — read-only inspection | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_clinical_lineage` | `staff/clinical/<int:pk>/lineage/` | `GET, HEAD` | all of `clinical.view_clinicaldraft` | no — read-only lineage | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_clinical_create` | `staff/clinical/new/` | `GET, POST` | all of `clinical.view_clinicaldraft`, `clinical.add_clinicaldraft` | yes — `daroobank/test_staff_inflight_clinical_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0192–0199 |
| `staff_clinical_revise` | `staff/clinical/<int:pk>/revise/` | `GET, POST` | all of `clinical.view_clinicaldraft`, `clinical.add_clinicaldraft` | yes — `daroobank/test_staff_inflight_revision_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205, 0192–0199 |
| `staff_clinical_reference_create` | `staff/clinical/<int:pk>/references/new/` | `GET, POST` | all of `clinical.view_clinicaldraft`, `clinical.add_clinicaldraft` | yes — `daroobank/test_staff_inflight_clinical_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205, 0192–0199 |
| `staff_clinical_review` | `staff/clinical/<int:pk>/review/` | `POST` | all of `clinical.view_clinicaldraft`, `clinical.review_clinicaldraft` | yes — `daroobank/test_staff_inflight_review_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205, 0192–0199 |
| `staff_identity_list` | `staff/catalog/identity/` | `GET, HEAD` | all of `catalog.view_identityworkspace` | no — read-only list | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_identity_detail` | `staff/catalog/identity/<str:kind>/<int:pk>/` | `GET, HEAD` | all of `catalog.view_identityworkspace` | no — read-only detail | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_identity_lineage` | `staff/catalog/identity/<str:kind>/<int:pk>/lineage/` | `GET, HEAD` | all of `catalog.view_identityworkspace` | no — read-only lineage | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_identity_create` | `staff/catalog/identity/new/<str:kind>/` | `GET, POST` | all of `catalog.view_identityworkspace`, `catalog.add_identityworkspace` | yes — `daroobank/test_staff_inflight_identity_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205, 0192–0199 |
| `staff_identity_revise` | `staff/catalog/identity/package/<int:pk>/revise/` | `GET, POST` | all of `catalog.view_identityworkspace`, `catalog.add_identityworkspace` | yes — `daroobank/test_staff_inflight_revision_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205, 0192–0199 |
| `staff_identity_revise_component` | `staff/catalog/identity/<str:kind>/<int:pk>/correction/` | `GET, POST` | all of `catalog.view_identityworkspace`, `catalog.add_identityworkspace` | yes — `daroobank/test_staff_inflight_revision_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205, 0192–0199 |
| `staff_identity_review` | `staff/catalog/identity/package/<int:pk>/review/` | `POST` | all of `catalog.view_identityworkspace`, `catalog.review_identityworkspace` | yes — `daroobank/test_staff_inflight_identity_writes.py` | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205, 0192–0199 |
| `staff_catalog_quality` | `staff/catalog/quality/` | `GET, HEAD` | all of `catalog.view_productpresentation` | no — read-only quality queue | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_catalog_quality_irc` | `staff/catalog/quality/<int:pk>/irc/` | `GET, HEAD` | all of `catalog.view_productpresentation` | no — read-only IRC inspection | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_import_receipts` | `staff/operations/imports/` | `GET, HEAD` | any of `catalog.view_productcandidate`, `pricing.view_pricecandidate` | no — read-only receipt list | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_import_receipt_detail` | `staff/operations/imports/<int:pk>/` | `GET, HEAD` | any of `catalog.view_productcandidate`, `pricing.view_pricecandidate` | no — read-only receipt detail | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_import_manifest_inspection` | `staff/operations/imports/<int:pk>/inspection/` | `GET, HEAD` | any of `catalog.view_productcandidate`, `pricing.view_pricecandidate` | no — read-only manifest inspection | 0200, 0206, 0207, 0208, 0209, 0210, 0213, 0201, 0204, 0205 |
| `staff_ingestion_window` | `staff/operations/window/` | `GET, HEAD` | any of `catalog.view_productcandidate`, `pricing.view_pricecandidate`, `sources.view_sourceclaim` | no — read-only limiter window | 0200, 0206, 0207, 0208, 0209, 0210, 0213 |
| `staff_login` | `staff/login/` | `GET, POST, PUT, HEAD, OPTIONS` | none — this is the entry point; a successful POST binds a session | no — authentication entry point, covered by revocation boundary tests | 0207, 0208, 0209, 0210, 0211, 0212, 0213 (bound here) |
| `staff_logout` | `staff/logout/` | `POST, OPTIONS` | an authenticated session; POST only | no — session teardown, covered by revocation boundary tests | 0207, 0208, 0209, 0210, 0211, 0212 |

## Non-staff routes

Every one of these is probed anonymously and as a fully permitted staff account for private-data leakage; the statuses column is what those probes expect today.

| Route | URL pattern | Probe rows | Expected statuses | Evidence |
|---|---|---|---|---|
| `health_live` | `health/live/` | 1 | 404 | 0202 |
| `health_ready` | `health/ready/` | 1 | 404 | 0202 |
| `home` | `(site root)` | 1 | 200 | 0202 |
| `search` | `search/` | 3 | 200 | 0202 |
| `search_api` | `api/v1/search/` | 2 | 200 | 0202 |
| `openapi_document` | `api/v1/openapi.json` | 1 | 200 | 0202 |
| `presentation_detail` | `products/<int:pk>/` | 2 | 200, 404 | 0202 |
| `presentation_api` | `api/v1/products/<int:pk>/` | 2 | 200, 404 | 0202 |
| `prices` | `prices/` | 1 | 200 | 0202 |
| `about` | `about/` | 1 | 200 | 0202 |
| `robots` | `robots.txt` | 1 | 200 | 0202 |
| `sitemap` | `sitemap.xml` | 1 | 200 | 0202 |
<!-- GENERATED END -->

## This surface is DEBUG-only

`STAFF_PORTAL_ENABLED = DEBUG` (`daroobank/settings.py`), and
`StaffPrivacyHeadersMiddleware` answers every `/staff/…` request with a 404 when that flag
is off. So the 43 routes above are a development-only portal: under default settings they
are unreachable, and this review describes code that is not exposed. The two `health_*`
routes are likewise behind `DAROOBANK_HEALTH_PROBES_ENABLED` and answer 404 without it,
which is why their expected status is 404 rather than 200.

The 12 non-staff routes are the public surface and carry no authorization at all by
design; ADR 0202 probes each of them for private-data leakage rather than for
permissions, and every one of them is probed both anonymously and as a fully permitted
staff account.

## What this review does not establish

- **That any requirement is the right one.** The tables say what each route asks for and
  that it asks for it. Nothing here argues that `catalog.view_productcandidate` is the
  correct requirement for `staff_products`, that review should be separable from add, or
  that a superuser without `is_staff` should receive 403 — ADR 0203 measures that
  behavior, it does not endorse it.
- **A threat model.** No adversary is defined, no trust boundary is analyzed and no abuse
  case is enumerated. The suites are behavioral parity and drift guards.
- **Anything about a deployed instance.** Every measurement was taken against synthetic
  data, inside a test transaction, on a development-only portal, in this repository's CI.
  No real proxy, TLS, session lifetime, clock skew, concurrency or user was involved.
- **The residuals of ADR 0213.** A dormant session whose account flags were toggled off
  and back on with no request in between is still alive. `list_staff_sessions` (ADR 0214)
  makes such a session visible and `revoke_staff_sessions` can end it, but neither is a
  production procedure with access control, audit and an owner. A request that has already
  passed the guard still runs to completion. Removing a backend from
  `AUTHENTICATION_BACKENDS` is invisible at request time. Granting a permission ends
  sessions exactly as revoking one does, because the guard compares state and not intent.
- **Authentication strength.** There is no MFA. `MFA_IMPLEMENTATION_PLAN.md` is an
  unowned proposal that now measures this tree — one login view rendering two credential
  fields, no factor state in any model or module, a stock account model, nothing between
  the password and the session, two address-keyed opt-in limiters that are not lockouts,
  and no cryptographic library — and prices six options against seven decisions nobody
  has made. ADR 0230 records that measurement and implements nothing. An earlier
  prototype of the plan was reverted.
- **Exhaustiveness beyond the resolver.** The tables are exhaustive of the URL surface,
  which is what "endpoint" means here. Management commands, middleware-only behavior,
  signals and background jobs are not routes and do not appear.
- **Sign-off.** The table below is empty and stays empty until the project assigns an
  owner. Filling it in with a name or a date would be a fabrication.

## Questions that need an owner

| Question | Owner | Date | Answer |
|---|---|---|---|
| Is the requirement per route the intended one, including `is_staff` with no specific permission for the workspace index and `any of` for the import-receipt and ingestion-window inspection routes? | | | |
| Should review stay separable from add on every domain, as it does today? | | | |
| Is a DEBUG-only portal the intended production shape? If not, what replaces `STAFF_PORTAL_ENABLED`, and what gates these routes then? | | | |
| Which of the 12 public routes may be exposed, and with what caching, indexing and referrer policy? | | | |
| Is the dormant-session residual of ADR 0213 acceptable, or does it require a written counter or database trigger plus an incident procedure? | | | |
| What is the production session revocation and inventory procedure, who may run it, and what is audited and retained? | | | |
| Is MFA in scope for Phase 1, and which option in the unreviewed plan is chosen? | | | |
| Do the health probes belong in the public surface, and is 404 the right answer when they are disabled? | | | |
