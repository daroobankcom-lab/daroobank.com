# The API and permissions plan, and what this boundary actually enforces

`docs/PHASE1_RELEASE_EVIDENCE.md` summarizes the **API and permissions** development evidence as
*"Versioned OpenAPI and selected server-side authorization tests exist"*, and keeps the whole row
open: *"approve each route's requirement, approve exposure and permissions for the intended
deployment, and add threat modeling and an independent security assessment."* `docs/API_DESIGN.md`
says *"The rest of this document is a proposed contract, not running endpoints"*, asks for
*"scoped short-lived tokens with revocation and rate/usage limits"*, notes *"405 and CSRF errors are
not part of the API JSON error schema"*, and states *"Public rate limiting, production-scale indexing
and snapshot-consistent export are not implemented."* `docs/AUTHORIZATION_REVIEW.md` is *"Status:
the inventory is derived and drift-checked; the judgement is unsigned"*, and `docs/SECURITY.md`
asks for *"Default deny; server-side object-level authorization and separation of author/reviewer. Users
may hold multiple roles; implement auditable permission grants, revocation and periodic review"*,
while assigning *"Super administrator | Manage roles/security configuration; no automatic clinical
approval bypass."* `docs/DEPLOYMENT.md` states *"No deployment has been performed or authorized."*

So the repository has a 55-route URL surface, 16 declared staff permissions, a static OpenAPI 3.0.3
file for 3 read-only endpoints, and an unowned judgement table — and no measurement of what sits
outside the parity suites: **does the OpenAPI contract match every live response, do permissions stop a
superuser or cross-revision author/reviewer overlap, and where do in-flight locks, dormant sessions
and CLI commands bypass the web boundary?**
[ADR 0235](ARCHITECTURE_DECISIONS/0235-api-permissions-plan.md) records what this document says and
what it measures. It is not a threat model, not an endpoint sign-off, not a token design and not an
approved authorization policy.

This document is a **proposal**. It has no owner and no approval, so it must not be read as a
decision, and it must not treat route-parity tests or development OpenAPI documents as production
authorization. Its prices are counted from the pins and files below, not prototyped: no API token,
OpenAPI edit or permission boundary change was implemented and reverted, so no cascade of pin
failures was run — but the contract boundary, superuser bypass, single-account accumulation,
revision-lineage separation of duties, in-flight locking race, dormant-session bound and CLI bypass
experiments **were** performed on synthetic data in throwaway PostgreSQL 16.2 databases, and every
number below is the result of those runs.

**Nothing is implemented.** No API token model, no OAuth/JWT dependency, no role-exclusivity policy,
no OpenAPI schema change, no database `CHECK` trigger on actor/reviewer separation and no change to
`STAFF_PORTAL_ENABLED` or CLI gating exists in this tree because of this file.

## What is true today, measured

Counted and measured on this tree by reading the resolver, `docs/openapi.json`, `docs/API_DESIGN.md`,
`daroobank/settings.py`, `daroobank/middleware.py`, the 127 non-test Python modules and the 12
management commands, and by executing live HTTP, ORM and two-connection concurrency probes against
the synthetic PostgreSQL 16.2 cluster. They are pinned by `daroobank/test_api_permissions_plan.py`.

### The URL surface and declared staff permissions

* **55 named routes across exactly two surfaces.** The live resolver exposes 43 `staff_*` routes
  (gated by `STAFF_PORTAL_ENABLED = DEBUG` in `daroobank/middleware.py`) and 12 non-staff routes:
  2 `health_*` probes (gated off by `DAROOBANK_HEALTH_PROBES_ENABLED`), 3 `/api/v1/*` JSON endpoints
  and 7 HTML or metadata routes. `daroobank/test_no_django_admin.py` pins the absence of
  `django.contrib.admin`, so no third administrative surface exists.
* **The 41 matrix routes use 16 permissions, while `auth_permission` holds 63 rows.** Excluding
  `staff_login` and `staff_logout`, 36 staff routes require `all of` their listed permissions, 4
  routes require `any of` a cross-domain view set (`staff_import_receipts`,
  `staff_import_receipt_detail`, `staff_import_manifest_inspection` across catalog/pricing view;
  `staff_ingestion_window` across catalog/pricing/sources view), and 1 route (`staff_workspace`)
  requires `is_staff` with no specific permission. `ALL_PERMISSIONS` checks 16 permissions (6 in
  `VIEW_PERMISSIONS`, 4 add, 5 review and `catalog.view_identityworkspace` /
  `catalog.add_identityworkspace` / `catalog.review_identityworkspace` /
  `catalog.view_productpresentation` counted inside those 16), leaving 47 permission rows in
  `auth_permission` — including stock `add`, `change`, `delete` and `view` permissions on `auth.User`,
  `auth.Group`, `sessions.Session`, `catalog.ProductPresentation` and `staff_security` models —
  unreferenced by any route.
* **`StaffLoginView` exposes `PUT` and overrides `LOGIN_REDIRECT_URL`.** `daroobank/settings.py` sets
  `LOGIN_REDIRECT_URL = 'staff_prices'`, yet `StaffLoginView.get_default_redirect_url()` in
  `pricing/staff_views.py` redirects a valid login with no `next` parameter to `/staff/`
  (`staff_workspace`, HTTP 302). `StaffLoginView` accepts `GET, POST, PUT, HEAD, OPTIONS`; an empty
  `PUT` returns HTTP 200 without authenticating (`_auth_user_id` absent from session) while still
  counting toward the opt-in login window. A superuser with `is_staff=False` loads `GET /staff/login/`
  with HTTP 200 and cannot create a session, and receives HTTP 403 on all 41 matrix routes.

### Public API contract versus live behavior

* **`docs/openapi.json` documents 3 paths, while `docs/API_DESIGN.md` sketches 11 more.** The bundled
  OpenAPI 3.0.3 spec (`version: 1.0.0`, `servers: [{"url": "/"}]`) describes `/api/v1/search/`,
  `/api/v1/products/{id}/` and `/api/v1/openapi.json` with 5 response definitions (`200` on each
  route plus `400` and `404`), 3 component schemas (`Presentation`, `SearchPage`, `Error`) and **0**
  `securitySchemes` or `security` blocks. By contrast, `docs/API_DESIGN.md` describes 11 unbuilt
  public and admin paths (`/drugs/{id}`, `/drugs/{id}/monographs`, `/products/{id}`, `/packages/{id}`,
  `/packages/{id}/prices`, `/manufacturers/{id}`, `/safety-alerts/{id}`,
  `/admin/candidates/{id}/decisions`, `/admin/content-versions/{id}/decisions`,
  `/admin/crawl-runs`, `/admin/crawl-runs/{id}`), `page`/`meta.as_of`/`error.request_id` fields,
  and scoped institutional/mobile API tokens — none of which exist in code.
* **Zero response headers and zero 403/405/429 responses appear in `docs/openapi.json`.** Every live
  HTTP 200 response on all 3 `/api/v1/*` routes emits 8 headers (`Cache-Control: no-store`,
  `Content-Length`, `Content-Security-Policy`, `Content-Type: application/json`,
  `Cross-Origin-Opener-Policy: same-origin`, `Referrer-Policy: no-referrer`,
  `X-Content-Type-Options: nosniff`, `X-Robots-Tag: noindex, follow`), none declared in the spec.
  Unsupported methods (`POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`) on all 3 routes return HTTP 405
  with `text/html; charset=utf-8`, a `0`-byte body and `Allow: GET, HEAD` when CSRF is unforced, while
  unsafe methods (`POST`, `PUT`, `PATCH`, `DELETE`) without a CSRF token under `enforce_csrf_checks=True`
  return HTTP 403 with `text/html; charset=utf-8` (`1,709` bytes) before `@require_safe` executes. When
  `PUBLIC_READ_LIMIT_ENABLED` is turned on, requests 1–120 to `/api/v1/search/` return HTTP 200 and
  request 121 returns HTTP 429 with `0` body bytes, `text/html; charset=utf-8`, `Retry-After: 60` and
  the same 7 privacy/security headers — rather than an `Error` JSON payload.
* **`q` truncation precedes Unicode control filtering, and parameter bounds are missing.** In
  `docs/openapi.json`, `/api/v1/search/` parameter `q` states only `{"type": "string"}` (omitting
  `maxLength: 120`, whereas `cursor` states `maxLength: 512`), `Error.error.code` states
  `{"type": "string"}` without an enum, and `/api/v1/products/{id}/` parameter `id` states
  `format: int64, minimum: 1` without `maximum: 9223372036854775807`. Live, `catalog/views.py` slices
  `q` at `MAX_QUERY_LENGTH = 120` before `search_product_page()` checks Unicode `Cc`/`Cs` code points:
  `120` `'A'`s followed by `'ZZZZ_IGNORED'` returns HTTP 200 with `1` matching hit, `'A'*10 + '\x00'`
  returns HTTP 400 (`invalid_query`), and `'A'*120 + '\x00'` returns HTTP 200 because the NUL past
  character 120 is silently discarded.
* **Integer-digit limits split `/api/v1/products/{id}/` 404 responses between JSON and HTML.**
  Requests to `/api/v1/products/0/`, `/api/v1/products/9223372036854775808/` (`2^63`) and a
  `4,300`-digit ID all match `<int:pk>` and return HTTP 404 `application/json`
  (`{"error": {"code": "not_found", "message": "Presentation not found."}}`). A `4,301`-digit ID hits
  Python's `sys.get_int_max_str_digits()` (`4300`) inside `<int:pk>`, skips the view with
  `Resolver404`, and returns HTTP 404 `text/html; charset=utf-8` — `179` bytes in `DEBUG=False`, or
  Django's `25,938`-byte technical 404 page exposing URL patterns in `DEBUG=True`.

### Superuser bypass, single-user accumulation and separation-of-duties boundaries

* **An active staff superuser bypasses every declared route permission (`41/41`).** Measured on a
  `is_staff=True, is_superuser=True` account with `0` `user_permissions` and `0` `groups`: all 41
  matrix routes succeed (`0` 403 denials, returning 200 or 400). This directly contradicts the target
  in `docs/SECURITY.md` (*"Super administrator | Manage roles/security configuration; no automatic
  clinical approval bypass"*). Only `is_staff=False, is_superuser=True` is blocked (`41/41` 403).
* **One account can hold all 16 permissions, and 0 of 37 database `CHECK` constraints cover SoD.**
  Neither `auth_permission` assignment nor any view checks role exclusivity: a single account held
  all 16 matrix permissions at once, able to stage/author and to review colleagues' work across every
  domain. Inspecting `pg_constraint` across schema `public` counts 37 `CHECK` constraints, **0** of
  which reference any user, author, recorder, stager or reviewer column — all separation of duties
  lives in Python services and views.
* **Row-level self-review fails closed on all 5 domains, except across revisions and CLI rows.** On
  direct self-authored objects (`sources`, `catalog` candidate, `pricing`, `clinical`, `catalog`
  identity package), even an active superuser receives HTTP 403 when attempting self-review (and the
  detail view omits the review form on self-authored claims). However, live probes across two
  versioned workflows confirm the boundary is immediate-node only:
  * In `clinical/services.py`, if Author A creates draft `v1` and Author B creates revision `v2`,
    `review_draft()` checks only `draft.author_id` (`v2`) and current supplementary `evidence`
    recorders — so Author A can legally review `v2` even though `v2` descends from Author A's `v1`.
  * In `catalog/identity.py`, `graph_authors()` reads only the current 4-node graph (package,
    product, formulation, ingredients) — so if Author A creates `pkg_v1` under another author's
    product and Author B revises it into `pkg_v2`, Author A is absent from `graph_authors(pkg_v2)` and
    can legally review `pkg_v2`.
  * A `PriceCandidate` staged by `manage.py stage_price_csv` sets `staged_by_id=None`, causing portal
    review to refuse every reviewer (`403`), including active superusers.

### In-flight locking, dormant sessions, management CLI and audit boundaries

* **15 of 16 `recheck_actor` sites run `lock=False`, leaving a measured concurrency window.** Across 7
  non-test modules (`catalog/identity.py` ×7, `catalog/intake.py` ×2, `clinical/services.py` ×2,
  `clinical/evidence.py` ×1, `pricing/importer.py` ×1, `pricing/reviews.py` ×1, `sources/services.py`
  ×2), only `sources/services.py:113` (`record_claim`) calls `recheck_actor(..., lock=True)`. A live
  two-connection test confirms `lock=True` blocks concurrent
  `User.objects.filter(...).update(is_active=False)` with PostgreSQL lock-timeout `SQLSTATE 55P03`
  while **not** blocking `user_permissions.clear()` on `auth_user_user_permissions`. Meanwhile, a
  live synchronized race on `sources.review_claim` (`lock=False`) committed a `SourceClaimReview`
  whose reviewer's `is_active` was `False` and whose password had already been invalidated before
  `commit`.
* **Dormant sessions survive off/on transitions and hide beyond row 5,000.** Because
  `StaffSessionGuardMiddleware` checks only on incoming `/staff/` requests, toggling `is_active` off
  and back on without an intervening request leaves `authorization_fingerprint` identical before and
  after (`staff_workspace` still returns HTTP 200), while public endpoints (`/api/v1/openapi.json`)
  return HTTP 200 even while the account is `is_active=False`. In addition, both `list_staff_sessions`
  and `revoke_staff_sessions` (`BATCH_LIMIT = 500`, `SCAN_LIMIT = 5000`, ordered by `session_key`)
  inspect only the first 5,000 rows in `django_session`: seeded with 5,000 filler sessions sorting
  ahead of target key `'zzzz...'`, both commands reported `scanned: 5000, matched: 0, revoked: 0` and
  left the live target session untouched.
* **6 of 12 management commands operate with `DEBUG=False`, outside web RBAC and receipts.** While
  `inspect_postgresql_access`, `inspect_postgresql_schema`, `repair_catalog_projection`,
  `cleanup_staff_login_windows`, `list_staff_sessions` and `revoke_staff_sessions` raise
  `CommandError` under `DEBUG=False`, the other 6 (`stage_price_csv`, `list_price_candidates`,
  `inspect_catalog_irc`, `inspect_catalog_quality`, `inspect_ingestion_window`,
  `check_deployment_readiness`) execute under `DEBUG=False` — and 5 of those never inspect
  `settings.DEBUG`. With `DEBUG=False`, `stage_price_csv --commit --attest-authorized` writes a
  `PriceCandidate` with `staged_by_id=None`, `0` `ImportReceipt` rows and `0` `ImportReceiptItem`
  rows, and `list_price_candidates` prints the full JSON payload to stdout.
* **Authorization decisions leave 0 in-application audit records.** `settings.LOGGING == {}`, **0** of
  the 127 non-test project modules import `logging`, `MIDDLEWARE` holds 13 entries in `DEBUG=True`
  (14 in `DEBUG=False` with `XFrameOptionsMiddleware` inserted), and neither HTTP 403 denials,
  superuser bypasses, permission grants/revocations nor non-review staff actions write an audit row.

## Candidate approach and decisions required

The measured boundary is 43 debug-gated staff routes plus 12 public routes, a 16-permission model out
of 63 `auth_permission` rows bypassed completely by active staff superusers, immediate-only SoD that
crosses neither revision chains nor DB constraints, 15 unlocked in-flight rechecks, a 5,000-row
session scan ceiling, 6 non-debug management commands outside web RBAC, and a 3-path OpenAPI document
whose headers, 403/405/429 responses and input bounds diverge from live HTTP responses. Everything
below requires owner decisions, and none of them is answered here.

1. **Which public, institutional and internal endpoints belong in Phase 1, and what replaces
   `STAFF_PORTAL_ENABLED = DEBUG`?** Today all 43 staff routes disappear outside `DEBUG=1` and the
   11 additional endpoints sketched in `docs/API_DESIGN.md` do not exist.
2. **Is the current per-route requirement set approved, including `is_staff`-only on
   `staff_workspace` and `any of` on import and window inspection routes?** Today those 5 exceptions
   sit beside 36 `all of` routes and 47 unreferenced `auth_permission` rows.
3. **Should an active superuser keep automatic access to all 41 staff routes, or must clinical,
   source and catalog review deny superusers without explicit scoped grants?** Today zero explicit
   grants suffice for 41/41 routes (`docs/SECURITY.md` proposes no automatic clinical approval bypass).
4. **May one account accumulate author and reviewer permissions across or within domains, or must
   mutually exclusive roles be enforced at grant time and in the database?** Today one user can hold
   all 16 matrix permissions at once.
5. **Should separation of duties extend across revision lineages and into PostgreSQL constraints, or
   stay bound to immediate drafts and graphs?** Today Author A can review `v2` of A's own `v1` draft or
   package, and 0 of 37 `CHECK` constraints enforce actor separation.
6. **How are `docs/openapi.json`, Django error handlers (`400`, `403`, `404`, `405`, `429`) and query
   bounds reconciled before external clients rely on them?** Today `<int:pk>` overflows, CSRF rejections,
   405s and 429s return HTML rather than `Error` JSON, `q` drops controls past byte/char 120, and 8
   response headers are undocumented.
7. **Which authentication scheme, scoping and revocation boundary applies to institutional and mobile
   API clients?** Today zero `securitySchemes`, zero token models and zero non-cookie credentials exist.
8. **How are dormant sessions beyond the 5,000-row scan bound, unlocked in-flight rechecks and
   unauthenticated management CLI commands closed and audited?** Today 15/16 rechecks run unlocked,
   `django_session` scans stop at 5,000 rows, 6 commands run under `DEBUG=False`, and `LOGGING` is `{}`.

## Options and what each costs

Prices are counted from the pins and files above, not prototyped.

| Option | What changes | Price, counted | What it still does not answer |
| --- | --- | --- | --- |
| **A. Leave the API and permission boundary as documented** | nothing | 0 code files, 0 OpenAPI changes, 0 migrations and 0 pins move; `docs/openapi.json` (3 paths), the 41/41 superuser bypass, 16-permission accumulation, immediate-only revision SoD, 15 unlocked rechecks, 5,000-row session scan cap and 6 un-gated CLI commands stay as measured | decisions 1–8 and the unsigned `docs/AUTHORIZATION_REVIEW.md` table that keeps `API and permissions` **Open** in `docs/PHASE1_RELEASE_EVIDENCE.md` |
| **B. Close the OpenAPI and HTTP API contract drift on the 3 existing endpoints** | update `docs/openapi.json` (`q` `maxLength: 120`, `id` `maximum: 9223372036854775807`, `Error.error.code` enum, documented headers and 405/429 responses), move `catalog/views.py` `MAX_QUERY_LENGTH` slicing after control-char validation, add a regex/JSON 404 handler for >4300-digit `/api/v1/products/` IDs, and emit JSON on API 405/429 paths | `docs/openapi.json` (271 lines, 3 paths, 5 responses, 3 schemas), `catalog/views.py`, `daroobank/urls.py`, `daroobank/middleware.py`, `docs/API_DESIGN.md`, and 6 test suites (`catalog/test_api_contract.py`, `catalog/test_public_read_privacy.py`, `catalog/test_search_invalid_query.py`, `catalog/test_public_detail_id.py`, `daroobank/test_public_route_privacy_matrix.py`, `daroobank/test_public_read_limit.py`); 0 migrations and 0 dependency changes (`33` tables, `279` columns, `32` applied migrations intact) | decisions 1–5, 7 and 8: staff RBAC, superuser bypass, SoD, institutional tokens and CLI parity |
| **C. Remove active superuser bypass, block single-user add+review accumulation, and harden `StaffLoginView` and `LOGIN_REDIRECT_URL`** | replace default `ModelBackend` or route-level `has_perm` superuser shortcut on staff review/write routes, reject incompatible add+review permission assignments, disable `PUT` on `StaffLoginView`, and align `settings.LOGIN_REDIRECT_URL` with `staff_workspace` | `daroobank/settings.py` (`AUTHENTICATION_BACKENDS` currently unset, `LOGIN_REDIRECT_URL = 'staff_prices'`), `pricing/staff_views.py` (`StaffLoginView`), `daroobank/test_staff_grant_paths.py` (`test_a_superuser_reaches_every_route_without_any_explicit_grant`), `daroobank/test_staff_method_sweep.py` (login `PUT`), `daroobank/test_staff_header_inventory.py`, `daroobank/test_authorization_review_drift.py`, `daroobank/test_mfa_implementation_plan.py` (which pins `AUTHENTICATION_BACKENDS` unset) and `daroobank/test_secret_rotation_plan.py` | decisions 5, 6 and 7: historical revision lineage SoD, PostgreSQL constraints, unlocked `recheck_actor` races and public API contract drift |
| **D. Enforce lineage-wide separation of duties, row-locked `recheck_actor`, and PostgreSQL `CHECK` or trigger constraints** | traverse ancestor creators in `clinical/services.py` and `catalog/identity.py` review checks, review lock order across multi-table graphs so `15` `lock=False` `recheck_actor` sites can serialize account/permission changes safely, and add database constraints/triggers beyond today's `37` `public` `CHECK` constraints (`138` total constraints) | `daroobank/actor_recheck.py` plus the 5 domain review/service modules, `1`–`5` migrations (`17` → `18+` project migrations, `32` → `33+` applied) moving schema pins in `daroobank/test_migration_reversibility.py`, `daroobank/test_populated_rollback_drill.py`, `daroobank/test_postgresql_inspection.py`, `daroobank/test_mfa_implementation_plan.py`, `daroobank/test_read_audit_plan.py`, `daroobank/test_backup_recovery_plan.py` and `docs/PHASE1_RELEASE_EVIDENCE.md`, plus concurrency suites under `catalog/`, `clinical/`, `pricing/` and `sources/` | decisions 1, 3, 6 and 7: what replaces `STAFF_PORTAL_ENABLED = DEBUG`, API tokens, OpenAPI drift and whether DB triggers hold under bulk/ORM repair |
| **E. Add scoped API token authentication and endpoint authorization for the proposed institutional/v1 endpoints** | introduce token persistence/scopes/revocation, Bearer/header authentication middleware, endpoint authorization checks, `securitySchemes` in `docs/openapi.json`, and new API endpoints from `docs/API_DESIGN.md` | at least 1 new model (`24` → `25+` project models, `33` → `34+` tables), new middleware (`13`/`14` entries), new `requirements.in` package if JWT/asymmetric signing is selected (`4` → `5+` direct pins, moving `requirements.txt` `94` lines / `7` names / `78` hashes and `pip-audit --strict`), `docs/openapi.json`, and moving resolver-count pins (`55` routes) in `daroobank/test_no_django_admin.py`, `daroobank/test_authorization_review_drift.py`, `daroobank/test_public_route_privacy_matrix.py` and `daroobank/test_staff_header_inventory.py`, plus `docs/SECRET_ROTATION_PLAN.md` and `docs/READ_AUDIT_PLAN.md` | decisions 2–5 and 8: who issues/revokes institutional keys, how key rotation interacts with tokens, and internal staff RBAC |
| **F. Decouple staff portal activation from `DEBUG` and remove the 5,000-session bound and CLI bypass** | replace `STAFF_PORTAL_ENABLED = DEBUG` with an explicit gate and readiness rule, replace fixed 5,000-row scan limits in `list_staff_sessions`/`revoke_staff_sessions`, gate or require actor attribution on the `6` un-gated management commands, and add request/permission audit logging | new environment variable(s) moving `daroobank/test_environment_documentation.py` (`16` read vars), `.env.example` (`12`), `compose.yaml` (`6`), `daroobank/management/commands/check_deployment_readiness.py` and `daroobank/test_deployment_readiness.py`; `daroobank/test_staff_disabled_boundary.py` and `daroobank/test_authorization_review_drift.py` (`DEBUG-only`); `daroobank/test_command_documentation.py` (`12` commands) and `daroobank/test_attribution_gap_plan.py`; plus `daroobank/test_no_read_audit.py` and `docs/READ_AUDIT_PLAN.md` if `LOGGING` becomes non-empty | decisions 3–7: replacing `DEBUG` without first resolving MFA, SoD, superuser bypass and read/write audit opens production exposure prematurely |
| **G. Keep Phase 1 read-only anonymous `/api/v1` only and defer authenticated APIs and production staff portal** | record in `docs/API_DESIGN.md`, `docs/AUTHORIZATION_REVIEW.md`, `docs/SECURITY.md` and `docs/PHASE1_RELEASE_EVIDENCE.md` that institutional/write APIs and any non-debug staff portal are deferred out of Phase 1, leaving only the 3 public read routes | 4 documents reworded, `daroobank/test_authorization_review_drift.py` updated if open questions are closed, `0` schema/code/dependency changes | decision 6 on whether the 3 remaining public API endpoints require Option B contract hardening and edge rate limits before exposure |

## Required behavior before any enablement

1. **Eliminate superuser and single-user role accumulation bypasses.** Replace implicit 41/41
   superuser permission grant with explicit, least-privilege permission enforcement on review/approval
   paths and prevent one account from accumulating incompatible author and reviewer permissions across
   all 16 matrix grants.
2. **Extend separation of duties across revision lineages and PostgreSQL.** Ensure clinical and
   identity package review checks reject ancestors in the revision chain — not only immediate draft or
   4-node graph authors — and enforce actor/reviewer separation with database constraints rather than
   Python checks alone (`0` of `37` `CHECK` constraints enforce it today).
3. **Close the OpenAPI contract against every live response.** Reconcile `docs/openapi.json` (`3` paths,
   `0` documented response headers, missing parameter bounds and `Error.error.code` enum) with live
   headers, JSON `403`/`405`/`429` error envelopes, >4300-digit `/api/v1/products/{id}/` resolution and
   `MAX_QUERY_LENGTH = 120` filtering before truncation.
4. **Remove login-method and redirect drift.** Disable unintended `PUT` handling on `StaffLoginView`
   and align `settings.LOGIN_REDIRECT_URL` (`'staff_prices'`) with
   `StaffLoginView.get_default_redirect_url()` (`staff_workspace`).
5. **Close unlocked `recheck_actor` races without inducing deadlocks.** Move the `15` `lock=False`
   service rechecks onto lock-ordered account and permission verification so an active-status or
   permission revocation between check and commit cannot persist a review or write.
6. **Remove the 5,000-row session scan bound and close dormant session survival.** Ensure session
   listing and revocation do not stop silently at row 5,000 of `django_session`, and address the
   off/on dormant session window with an operational or database-backed invalidation control.
7. **Gate CLI tools and record authorization audit events.** Reconcile the 6 management commands
   that operate under `DEBUG=False` without web RBAC or import receipts, and establish handler-backed
   audit logging (`LOGGING` is `{}` today) for grants, revocations, denials and superuser actions.

## Verification before any enablement

- Re-run the live resolver, OpenAPI and HTTP probes on synthetic data in throwaway PostgreSQL 16.2
  databases and verify every measured count in this plan: `55` routes (`43` staff, `12` non-staff),
  `41` matrix routes (`36` `all of`, `4` `any of`, `1` `is_staff`), `63` `auth_permission` rows vs
  `16` `ALL_PERMISSIONS`, `3` OpenAPI paths, `8` undocumented live `200` headers, HTML `405`/`403`/`429`
  bodies, `120`-character query truncation preceding `\x00` filtering, and JSON vs HTML split at
  `4,300` vs `4,301` digits on `/api/v1/products/{id}/`.
- Re-verify the permission and concurrency measurements: active superuser `41/41` access, non-staff
  superuser `41/41` 403 refusal, `StaffLoginView` `PUT` HTTP 200 and `/staff/` redirect, `0` of `37`
  PostgreSQL `CHECK` constraints covering actor separation, `clinical` v1-author reviewing `v2`,
  `identity` v1-package author reviewing `pkg_v2`, and the unlocked `sources.review_claim` race
  committing after reviewer deactivation and password invalidation.
- Re-verify session and CLI boundaries: dormant session survival across an off/on `is_active` toggle,
  `5,000`-row truncation in `list_staff_sessions` and `revoke_staff_sessions`, and `stage_price_csv`
  / `list_price_candidates` executing under `DEBUG=False` with `staged_by_id=None` and `0` receipt rows.
- Confirm that no API token model, OAuth/JWT dependency, OpenAPI security scheme, new middleware, new
  database constraint or `STAFF_PORTAL_ENABLED` change named as absent in this plan has been added,
  and recompute `daroobank/test_api_permissions_plan.py` pins rather than deleting them if a chosen
  option lands.
- Complete the empty owner, date and answer columns in `docs/AUTHORIZATION_REVIEW.md` and record
  named security, clinical and operational sign-offs in `docs/PHASE1_RELEASE_EVIDENCE.md`.
- Treat every successful run here as synthetic measurement only; no production API exposure, token
  issuance or Phase 1 gate sign-off follows from these checks.
