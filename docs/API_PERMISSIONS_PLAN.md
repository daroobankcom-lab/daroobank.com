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
For the residual session-revocation blocker,
[ADR 0191](ARCHITECTURE_DECISIONS/0191-staff-session-revocation-gap.md) records
*"the revival scenario named below is closed by"*
[ADR 0213](ARCHITECTURE_DECISIONS/0213-durable-session-invalidation.md) and leaves
*"a transition no request observes (which is what the `revoke_staff_sessions` command is for),
in-flight requests that already passed the guard, backend removal from settings, MFA, replay
protection, session inventory and any production procedure."* On forwarding headers and client IP
throttling, [the network and TLS plan](NETWORK_TLS_PLAN.md)
([ADR 0234](ARCHITECTURE_DECISIONS/0234-network-tls-plan.md)) establishes
*"`HTTP_X_FORWARDED_FOR` is read by 0 non-test modules"* and quotes
`docs/DEPLOYMENT.md`: *"Rate and size limits still have to be provisioned by the reverse proxy, a CDN
or the host before this service faces the public internet"*.

So the repository has a 55-route URL surface with zero view-level permission decorators, 16 declared
staff permissions out of 63 `auth_permission` rows, a static OpenAPI 3.0.3 file for 3 read-only
endpoints, extensive route-parity and header suites, and an unowned judgement table — and until this
plan, no end-to-end measurement of what sits outside those parity suites: **where view code delegates
authorization to helpers or services rather than decorators, how OpenAPI diverges from live
responses, what signed cursors and session tokens carry, whether permissions stop active superusers,
group grants or cross-revision self-review, and where unlocked in-flight rechecks, dormant sessions
and CLI tools bypass the web boundary.**
[ADR 0235](ARCHITECTURE_DECISIONS/0235-api-permissions-plan.md) records what this document says and
what it measures. It is not a threat model, not an endpoint sign-off, not a token design and not an
approved authorization policy.

This document is a **proposal**. It has no owner and no approval, so it must not be read as a
decision, and it must not treat route-parity tests or development OpenAPI documents as production
authorization. Its prices are counted from the pins and files below, not prototyped: no API token,
OpenAPI edit or permission boundary change was implemented and reverted, so no cascade of pin
failures was run — but the route/decorator inventory, OpenAPI contract drift, denial/CSRF/method/
header/cursor shapes, superuser and group-grant boundaries, single-account accumulation,
revision-lineage separation of duties, in-flight locking race, dormant-session bound and CLI bypass
experiments **were** performed on synthetic data in throwaway PostgreSQL 16.2 databases, and every
number below is the result of those runs.

**Nothing is implemented.** No API token model, no OAuth/JWT dependency, no role-exclusivity policy,
no OpenAPI schema change, no database `CHECK` trigger on actor/reviewer separation and no change to
`STAFF_PORTAL_ENABLED` or CLI gating exists in this tree because of this file.

## What is true today, measured

Counted and measured on this tree by reading the live URL resolver, view ASTs, `docs/openapi.json`,
`docs/API_DESIGN.md`, `daroobank/settings.py`, `daroobank/middleware.py`,
`daroobank/session_guard.py`, `daroobank/signed_cursors.py`, the 121 non-test project modules and the
12 management commands, and by executing live HTTP, ORM and two-connection concurrency probes against
the synthetic PostgreSQL 16.2 cluster. All invariants and live measurements are pinned by
`daroobank/test_api_permissions_plan.py` (12 database-free checks plus 2 live PostgreSQL tests).

### The URL surface, decorator enforcement versus test-asserted authorization, and login behavior

* **55 named routes across exactly two surfaces.** The live resolver exposes 43 `staff_*` routes
  (all gated by `STAFF_PORTAL_ENABLED = DEBUG` in `daroobank/middleware.py`) across `daroobank` (1:
  `staff_workspace`), `sources` (6), `catalog` (15: 6 intake, 7 identity, 2 quality), `pricing` (8:
  6 candidate routes plus the 2 auth CBVs), `clinical` (9) and `ingestion` (4); and 12 non-staff
  routes: 2 `health_*` probes (`health_live` `/health/live/`, `health_ready` `/health/ready/`, gated
  by `DAROOBANK_HEALTH_PROBES_ENABLED`), 3 `/api/v1/*` JSON routes (`search_api`,
  `presentation_api`, `openapi_document`), and 7 public HTML/metadata routes (`home` at site root,
  `search`, `presentation_detail`, `prices`, `about`, `robots`, `sitemap`).
  `daroobank/test_no_django_admin.py` pins the absence of `django.contrib.admin`, so no third
  administrative surface exists.
* **Code declares zero permission decorators; all 41 matrix routes rely on test-pinned code guards.**
  AST inspection of all 55 callbacks shows **0** uses of `@permission_required` or
  `@staff_member_required`. All 41 matrix function views carry only
  `@login_required(login_url='staff_login')` and an HTTP method decorator (`27` `@require_safe`, `9`
  `@require_http_methods(['GET', 'POST'])`, `5` `@require_POST`); their permission requirements are
  asserted uniformly against the resolver only by `daroobank/test_staff_authorization_matrix.py`
  (`ROUTES | AUTH_ROUTES`) and enforced in Python code through three patterns:
  * **36 views check permissions inline at or near the top of the view function**: 32 call
    `require_staff(...)` or `_require_permission(...)` as statement 1, 2 check `is_active`,
    `is_staff` and (for `staff_ingestion_window`) `any(user.has_perm(...))` inline
    (`daroobank/staff_views.py` `staff_workspace`; `ingestion/staff_views.py`
    `staff_ingestion_window`), and 2 call `visible_kinds(request.user)` after local imports
    (`staff_import_receipts` and `staff_import_receipt_detail` in `ingestion/staff_views.py`).
  * **2 views delegate authorization to a shared view helper**: `staff_product_review_inspection`
    (`catalog/staff_views.py`) and `staff_price_review_inspection` (`pricing/staff_views.py`) both
    delegate directly to `daroobank/candidate_review_scan_views.py:scan_response`, which checks
    `require_staff(...)` before parsing query inputs or querying models.
  * **3 views omit authorization in the view module and rely solely on downstream services**:
    `staff_clinical_lineage` (`clinical/staff_views.py` -> `clinical/lineage.py:inspect_lineage`),
    `staff_identity_lineage` (`catalog/identity_views.py` ->
    `catalog/identity_lineage.py:inspect_lineage`), and `staff_import_manifest_inspection`
    (`ingestion/staff_views.py` -> `ingestion/manifest_inspection.py:inspect_manifest`), where
    `manifest_inspection` even parses `after` (`daroobank/scan_input.py:parse_scan_after`) and
    reads `category` before calling `inspect_manifest(actor=request.user, ...)`. Measured live, a
    permissionless `bare` staff account still receives the canonical `403` (`135` bytes) across all
    3 even with malformed queries (`?cursor=bad` or `?after=abc&category=%00`) because each service
    checks `require_staff` or `visible_kinds` before validation or DB lookup.
  * **Decorator-free endpoints and middleware gates**: `staff_login` and `staff_logout` are
    class-based views in `pricing/staff_views.py` with zero view decorators; `health_live` and
    `health_ready` in `daroobank/health.py` carry zero decorators (checking `HEALTH_PROBES_ENABLED`
    and `request.method in ('GET', 'HEAD')` inline); `10` public HTML/API views in
    `catalog/views.py` carry only `@require_safe`; and `STAFF_PORTAL_ENABLED = DEBUG` plus session
    fingerprint enforcement live in `daroobank/middleware.py`. Notice also that
    `daroobank/session_guard.py` connects `_bind_fingerprint` to `user_logged_in` on module import
    by `daroobank/middleware.py`, so a test or command session bound before middleware loads omits
    `staff_auth_fingerprint` and is flushed by `StaffSessionGuardMiddleware` on its first staff hit.
* **The 41 matrix routes use 16 permissions, while `auth_permission` holds 63 rows.** Excluding
  `staff_login` and `staff_logout`, 36 staff routes require `all of` their listed permissions, 4
  routes require `any of` a cross-domain view set (`staff_import_receipts`,
  `staff_import_receipt_detail`, `staff_import_manifest_inspection` across catalog/pricing view;
  `staff_ingestion_window` across catalog/pricing/sources view), and 1 route (`staff_workspace`)
  requires `is_staff` with no specific permission. `ALL_PERMISSIONS` checks 16 permissions (6 in
  `VIEW_PERMISSIONS`, 4 add, 5 review and `catalog.view_productpresentation`), leaving 47 rows in
  `auth_permission` — including stock `add`, `change`, `delete` and `view` permissions on `auth.User`,
  `auth.Group`, `sessions.Session`, `catalog.ProductPresentation` and `staff_security` models —
  unreferenced by any route.
* **`StaffLoginView` exposes `PUT` and overrides `LOGIN_REDIRECT_URL`.** `daroobank/settings.py` sets
  `LOGIN_REDIRECT_URL = 'staff_prices'`, yet `StaffLoginView.get_default_redirect_url()` in
  `pricing/staff_views.py` redirects a valid login with no `next` parameter to `/staff/`
  (`staff_workspace`, HTTP 302). `StaffLoginView` accepts `GET, POST, PUT, HEAD, OPTIONS`; an empty
  `PUT` returns HTTP 200 without authenticating (`_auth_user_id` absent from session) while still
  counting toward the opt-in login window. A superuser with `is_staff=False` loads `GET /staff/login/`
  with HTTP 200, cannot reach any protected route, and receives HTTP 403 on all 41 matrix routes.

### Denial shapes, identifier and query parity, CSRF gate, method sweep and closed header inventory

* **Canonical denial shapes across account shapes (`daroobank/test_staff_authorization_matrix.py`,
  `daroobank/test_staff_denial_parity.py`).** An anonymous GET/POST receives HTTP `302` (`0` body bytes,
  `Location: /staff/login/?next=<url>`, `11` headers: the 7 pinned staff security/privacy headers,
  `Content-Type: text/html; charset=utf-8`, `Content-Length: 0`, `Vary: Cookie`, no `Expires`). Every
  active unauthorized account shape (`outsider`, `bare`, `view-only`, `is_staff=False` superuser)
  receives a byte-identical HTTP `403` (`135` bytes: Django's minimal `<h1>403 Forbidden</h1><p></p>`
  HTML page, identical status, body and headers minus `3` `VOLATILE_HEADERS` = `date`,
  `set-cookie`, `expires`) on both existing rows and missing PK `999_999_999` across all `23`
  `OBJECT_ROUTES` — and across view-inline, `scan_response`-delegated and downstream-service routes
  alike. A previously logged-in full-permission account whose `is_active` is flipped to `False` has
  its bound session flushed by `StaffSessionGuardMiddleware` and receives anonymous `302` (or `403`
  without session binding; `(302, 403)`). Timing is deliberately not compared.
* **Identifier and query shapes cannot change denials (`daroobank/test_staff_identifier_parity.py`,
  `daroobank/test_staff_query_parity.py`).** Sweeping `13` identifier shapes across all `23` object
  routes shows that the `4` `<int:pk>`-resolving identifiers (`999999999`, `0`, `99999999999999999999`,
  `9223372036854775807`) yield canonical `403` for unauthorized accounts and `404` for authorized
  accounts, while the `9` converter-rejected strings (`-1`, `abc`, `1.5`, `1%2f..`, empty string,
  leading/trailing spaces, `+1`, `١`) return the identical unmatched-URL `404` for every account
  including anonymous; wrong HTTP methods answer `405` before authorization on `19` single-method
  object routes (`14` safe-only + `5` POST-only) while the `4` `DUAL_METHOD_ROUTES` apply no method
  gate. Across all `41` matrix routes, `9` caller-controlled `QUERY_VARIANTS` (`{}`, `kind=product`,
  `kind=price`, `<script>alert(1)</script>`, `page=-1`, `page=99999999999999999999`,
  `after=abc&category=\x00`, `q='x'*5000`, `at=not-a-date&days=-3`) never change a `403` denial or
  `302` redirect and never raise a `500`, leaving `KIND_FILTER_ROUTE = 'staff_import_receipts'`
  (`?kind=price` denied to a product-only account) as the single query-driven `403`.
* **CSRF gate precedes authentication, authorization and decorators
  (`daroobank/test_staff_csrf_gate.py`).** Across all `43` `staff_*` routes, POSTs with `5` failure
  modes (missing token, empty token, mangled token, foreign cookie token, cross-origin `Origin: https://evil.example`) fail identically with
  HTML `403` regardless of account or permission — even on routes that otherwise answer `405`. The
  CSRF body depends solely on whether a CSRF cookie is present and on `DEBUG` (`3,174` bytes
  without cookie / `2,504` bytes with cookie in `DEBUG=True`, vs `1,709` / `1,040` bytes in
  `DEBUG=False`), whereas presenting a valid same-session token separates `27` safe-only `405`
  routes, `9` dual-method `200` form renders and `5` POST-only `400` review validations.
* **Method sweep and closed header inventory (`daroobank/test_staff_method_sweep.py`,
  `daroobank/test_staff_header_inventory.py`).** Sweeping `6` methods (`GET`, `HEAD`, `OPTIONS`, `PUT`,
  `PATCH`, `DELETE`) plus `POST` across all `43` routes proves `0` matrix or logout routes accept `PUT`,
  `PATCH` or `DELETE` (empty `405`), `15` routes (`9` dual + `5` POST-only + `staff_logout`) answer
  `405` to `HEAD`, `StaffLoginView` routes `PUT` to `post`, and `Allow` takes values strictly from
  the `5` strings in `EXPECTED_ALLOW` (`GET, HEAD`, `GET, POST`, `POST`, `POST, OPTIONS`,
  `GET, POST, PUT, HEAD, OPTIONS`). Across `1,204` responses (`43` routes × `7` methods × `4` accounts),
  only `ALLOWED_STATUSES = {200, 302, 400, 403, 404, 405, 409}` occur; every response emits all `7`
  `PINNED_HEADERS` (`cache-control: private, no-store, max-age=0`, `pragma: no-cache`,
  `x-robots-tag: noindex, nofollow`, `referrer-policy: same-origin`,
  `x-content-type-options: nosniff`, `cross-origin-opener-policy: same-origin`,
  `content-security-policy`); only `9` `VARIABLE_HEADERS` appear; `0` headers exist outside those 16;
  only the `2` `SAMPLE_ROUTES` (`staff_product_sample`, `staff_price_sample`) emit `text/csv`
  attachments (`product_candidates.synthetic.csv` and `price_candidates.synthetic.csv`); and
  `X-Frame-Options: DENY` is inserted only in non-debug (`14` vs `13` middlewares, pinned by
  `daroobank/test_nondebug_frame_guard.py`).

### Public API contract versus live behavior, and cursor and token shapes

* **`docs/openapi.json` documents 3 paths, while `docs/API_DESIGN.md` sketches 11 more.** The bundled
  OpenAPI 3.0.3 spec (`version: 1.0.0`, `servers: [{"url": "/"}]`, `271` lines) describes
  `/api/v1/search/`, `/api/v1/products/{id}/` and `/api/v1/openapi.json` with 5 response definitions
  (`200` on each route plus `400` and `404`), 3 component schemas (`Presentation`, `SearchPage`,
  `Error`) and **0** `securitySchemes` or `security` blocks. By contrast, `docs/API_DESIGN.md`
  describes 11 unbuilt public and admin paths (`/drugs/{id}`, `/drugs/{id}/monographs`,
  `/products/{id}`, `/packages/{id}`, `/packages/{id}/prices`, `/manufacturers/{id}`,
  `/safety-alerts/{id}`, `/admin/candidates/{id}/decisions`, `/admin/content-versions/{id}/decisions`,
  `/admin/crawl-runs`, `/admin/crawl-runs/{id}`), `page`/`meta.as_of`/`error.request_id` fields, and
  scoped institutional/mobile API tokens — none of which exist in code.
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
* **Cursor and token shapes: 4 signed cursors, 1 repair token, 3 unsigned cursors, 0 API tokens.**
  All 4 pagination/lineage cursors share `daroobank/signed_cursors.py:loads_nonfuture`
  (`CURSOR_MAX_AGE = 3600` s, rejecting compressed `.`-prefixed tokens and future timestamps via base62
  clock checks) and replace sensitive inputs with SHA-256 `salted_hmac` digests while leaving integer PKs visible and providing
  neither encryption nor authorization: `catalog/services.py` (`catalog.search.cursor.v1`,
  `MAX_CURSOR_LENGTH = 512`, `{query, pk, name}`), `catalog/quality_irc.py`
  (`catalog.quality.irc.cursor.v1`, `512`, `{anchor, code, last}`), `catalog/identity_lineage.py`
  (`catalog.identity.lineage.v1`, `1024`, `{kind, anchor, anchor_graph, current, current_graph, depth}`),
  and `clinical/lineage.py` (`clinical.draft.lineage.v1`, `1024`,
  `{anchor, anchor_hash, current, current_hash, depth}`). A fifth signed shape sits in
  `catalog/projection_repair.py` (`catalog.synthetic-projection-repair.v1`, `TOKEN_AGE = 600` s,
  `MAX_TOKEN_LENGTH = 512`, `{id, state, database}`). Three unsigned pagination inputs also exist:
  `before` and `revisions_before` in `catalog/identity_views.py` (1–`9_223_372_036_854_775_807`, max
  19 ASCII digits), `daroobank/scan_input.py:parse_scan_after` (`0..5000`/`MAX_PK`), and Django
  `Paginator` (`page`, 20 rows/page). Authentication uses solely database-backed cookies
  (`SESSION_COOKIE_HTTPONLY = True`, `SESSION_COOKIE_SAMESITE = 'Lax'`, `SESSION_COOKIE_AGE = 3600`,
  `SESSION_SAVE_EVERY_REQUEST = False`), `_auth_user_hash` (password) plus
  `daroobank/session_guard.py:authorization_fingerprint` (`daroobank.staff.session.v1` SHA-256
  `salted_hmac` over `is_active|is_staff|is_superuser|session_auth_hash|sorted_perms`), and CSRF
  tokens; **0** non-test modules read `HTTP_AUTHORIZATION` or `Bearer`.

### Superuser bypass, group grants, single-user accumulation and separation-of-duties boundaries

* **An active staff superuser bypasses every declared route permission (`41/41`).** Measured on a
  `is_staff=True, is_superuser=True` account with `0` `user_permissions` and `0` `groups`: all 41
  matrix routes succeed (`0` 403 denials, returning 200 or 400). This directly contradicts the target
  in `docs/SECURITY.md` (*"Super administrator | Manage roles/security configuration; no automatic
  clinical approval bypass"*). Only `is_staff=False, is_superuser=True` is blocked (`41/41` 403).
* **Group grants match direct grants sequentially, with no exclusivity or lock guard.** In
  `daroobank/test_staff_grant_paths.py`, `auth.Group` grants (`grants-full` 41/41, `grants-view`
  25/25) match direct `user_permissions` and sequential `user.groups.remove` makes `recheck_actor`
  deny a stale in-memory user object; yet no exclusivity rule limits `auth_group_permissions`, no
  audit records group changes, `47` of `63` `auth_permission` rows remain unexercised by route or
  group parity tests, and `recheck_actor(..., lock=True)` locks only `auth_user` — not
  `auth_user_groups` or `auth_group_permissions`.
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

### In-flight locking, ADR 0191 blockers, proxy `REMOTE_ADDR`, CLI and audit boundaries

* **15 of 16 `recheck_actor` sites run `lock=False`, leaving a measured concurrency window.** Across 7
  non-test modules (`catalog/identity.py` ×7, `catalog/intake.py` ×2, `clinical/services.py` ×2,
  `clinical/evidence.py` ×1, `pricing/importer.py` ×1, `pricing/reviews.py` ×1, `sources/services.py`
  ×2), only `sources/services.py:113` (`record_claim`) calls `recheck_actor(..., lock=True)`. A live
  two-connection test confirms `lock=True` blocks concurrent
  `User.objects.filter(...).update(is_active=False)` with PostgreSQL lock-timeout `SQLSTATE 55P03`
  while **not** blocking `user_permissions.clear()` on `auth_user_user_permissions` or
  `groups.clear()` on `auth_user_groups`. Meanwhile, a live synchronized race on
  `sources.review_claim` (`lock=False`) committed a `SourceClaimReview` whose reviewer's `is_active`
  was `False` and whose password had already been invalidated before `commit`.
* **ADR 0191 residual blockers and the 5,000-row session scan cap.** While
  [ADR 0213](ARCHITECTURE_DECISIONS/0213-durable-session-invalidation.md) closed revival on observed
  requests, [ADR 0191](ARCHITECTURE_DECISIONS/0191-staff-session-revocation-gap.md) and
  `daroobank/session_guard.py` leave 6 unproven gaps: toggling `is_active` off and back on without an
  intervening `/staff/` request leaves `authorization_fingerprint` identical (`staff_workspace` still
  returns HTTP 200, while `/api/v1/openapi.json` stays `200` even while `is_active=False`);
  `list_staff_sessions` and `revoke_staff_sessions` (`BATCH_LIMIT = 500`, `SCAN_LIMIT = 5000`,
  ordered by `session_key`) ignore rows past 5,000 (`scanned: 5000, matched: 0, revoked: 0` against
  target key `'zzzz...'`); in-flight requests past `StaffSessionGuardMiddleware` finish; removing a
  backend from `AUTHENTICATION_BACKENDS` is unobserved at request time; MFA and stolen-cookie replay
  protection are absent; and no approved production session-revocation procedure exists.
* **`REMOTE_ADDR` behind a reverse proxy (referenced from lane 2, not re-priced).** Both
  `StaffLoginView` (`pricing/staff_views.py` via `staff_security`) and `PublicReadLimitMiddleware`
  (`daroobank/middleware.py`) read `request.META.get('REMOTE_ADDR')`, while
  [the network and TLS plan](NETWORK_TLS_PLAN.md)
  ([ADR 0234](ARCHITECTURE_DECISIONS/0234-network-tls-plan.md)) measures that `HTTP_X_FORWARDED_FOR`
  is read by 0 non-test modules. Behind an un-rewritten reverse proxy, every caller collapses onto the
  proxy peer address for both login and public-read throttles. Trusting proxy headers and edge
  isolation are owned and priced in `docs/NETWORK_TLS_PLAN.md` and are not re-priced here.
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
  the 121 non-test project modules import `logging`, `MIDDLEWARE` holds 13 entries in `DEBUG=True`
  (14 in `DEBUG=False` with `XFrameOptionsMiddleware` inserted), and neither HTTP 403 denials,
  superuser bypasses, permission grants/revocations nor non-review staff actions write an audit row.

## Candidate approach and decisions required

The measured boundary is 43 debug-gated staff routes (0 permission decorators; 36 inline, 2 helper
and 3 downstream-service guards pinned only by suites) plus 12 non-staff routes, 16 checked permissions
out of 63 `auth_permission` rows bypassed completely by active staff superusers, immediate-only SoD
that crosses neither revision chains nor DB constraints, 4 signed cursors alongside 0 API tokens,
ADR 0191's residual blockers and 5,000-row session scan cap, 15 unlocked in-flight rechecks, 6
non-debug management commands outside web RBAC, and a 3-path OpenAPI document whose headers,
403/405/429 responses and input bounds diverge from live HTTP responses. Everything below requires
owner decisions, and none of them is answered here. (`REMOTE_ADDR` reverse-proxy handling stays with
lane 2 in `docs/NETWORK_TLS_PLAN.md`.)

1. **Expose more of the sketched API or keep the three read endpoints — and what replaces
   `STAFF_PORTAL_ENABLED = DEBUG`?** Today `docs/API_DESIGN.md` sketches 11 unbuilt routes while only
   the 3 `/api/v1/*` read endpoints exist, and all 43 staff routes disappear outside `DEBUG=1`.
2. **Enforce endpoint/object permissions for future API endpoints, and approve the current 41-route
   matrix and 47 unreferenced permissions?** Today 0 routes carry permission decorators, 3 routes check
   authorization only inside downstream services, `staff_workspace` checks `is_staff` only, 4 routes
   check `any of`, and 47 `auth_permission` rows have no route; institutional token scopes and object
   rules remain undesigned.
3. **Settle whether `is_superuser` keeps its staff bypass, or must clinical, source and catalog
   review deny superusers without explicit scoped grants?** Today zero explicit grants suffice for
   41/41 routes (`docs/SECURITY.md` proposes no automatic clinical approval bypass).
4. **May one account accumulate author and reviewer permissions (directly or via groups), or must
   mutually exclusive roles be enforced at grant time and in the database?** Today one user or group
   can hold all 16 matrix permissions at once.
5. **Should separation of duties extend across revision lineages and into PostgreSQL constraints, or
   stay bound to immediate drafts and graphs?** Today Author A can review `v2` of A's own `v1` draft or
   package, and 0 of 37 `CHECK` constraints enforce actor separation.
6. **Reconcile OpenAPI (`docs/openapi.json`) against live error, header and throttle behavior — or
   defer contract alignment?** Today `<int:pk>` overflows (>4300 digits), CSRF rejections (`403`),
   `405`s and throttled `429`s return HTML rather than `Error` JSON, `q` drops controls past character
   120, `0` `securitySchemes` exist, and all 8 live `200` headers are omitted from the spec.
7. **Which authentication scheme, scoping and revocation boundary applies to institutional and mobile
   API clients?** Today zero token models and zero `HTTP_AUTHORIZATION`/`Bearer` readers exist.
8. **How are ADR 0191's residual blockers (dormant sessions beyond 5,000 rows, unlocked in-flight
   rechecks), unauthenticated non-debug CLI commands and missing audit logs closed?** Today 15/16
   rechecks run unlocked, `django_session` scans stop at 5,000 rows, 6 commands run under
   `DEBUG=False`, and `LOGGING` is `{}`.

## Options and what each costs

Prices are counted from the pins and files above, not prototyped.

| Option | What changes | Price, counted | What it still does not answer |
| --- | --- | --- | --- |
| **A. Leave the API and permission boundary as documented** | nothing | 0 code files, 0 OpenAPI changes, 0 migrations and 0 pins move; `docs/openapi.json` (3 paths), 0 permission decorators, the 41/41 superuser bypass, 16-permission user/group accumulation, immediate-only revision SoD, 15 unlocked rechecks, 5,000-row session scan cap and 6 un-gated CLI commands stay as measured | decisions 1–8 and the unsigned `docs/AUTHORIZATION_REVIEW.md` table that keeps `API and permissions` **Open** in `docs/PHASE1_RELEASE_EVIDENCE.md` |
| **B. Keep the 3 read endpoints only and reconcile `docs/openapi.json` against live error, header and throttle behavior** | update `docs/openapi.json` (`q` `maxLength: 120`, `id` `maximum: 9223372036854775807`, `Error.error.code` enum, documented 8 headers and `403`/`405`/`429` responses), move `catalog/views.py` `MAX_QUERY_LENGTH` slicing after control-char validation, add a regex/JSON 404 handler for >4300-digit `/api/v1/products/` IDs, and emit JSON on API `405`/`429` paths | `docs/openapi.json` (271 lines, 3 paths, 5 responses, 3 schemas), `catalog/views.py`, `daroobank/urls.py`, `daroobank/middleware.py`, `docs/API_DESIGN.md`, and 6 test suites (`catalog/test_api_contract.py`, `catalog/test_public_read_privacy.py`, `catalog/test_search_invalid_query.py`, `catalog/test_public_detail_id.py`, `daroobank/test_public_route_privacy_matrix.py`, `daroobank/test_public_read_limit.py`); 0 migrations and 0 dependency changes (`33` tables, `279` columns, `32` applied migrations intact) | decisions 1 (staff gate & 11 sketched routes), 2–5, 7 and 8 (`REMOTE_ADDR` throttle proxy trust stays priced in `docs/NETWORK_TLS_PLAN.md`) |
| **C. Settle `is_superuser` bypass, block user/group add+review accumulation, harden `StaffLoginView` and promote downstream service guards to view entry** | replace default `ModelBackend` or route-level `has_perm` superuser shortcut on staff review/write routes, reject incompatible add+review direct/group grants, move `inspect_lineage`/`inspect_manifest` checks ahead of view-level parsing or into uniform wrappers, disable `PUT` on `StaffLoginView`, and align `settings.LOGIN_REDIRECT_URL` with `staff_workspace` | `daroobank/settings.py` (`AUTHENTICATION_BACKENDS` currently unset, `LOGIN_REDIRECT_URL = 'staff_prices'`), `pricing/staff_views.py` (`StaffLoginView`), `clinical/staff_views.py`, `catalog/identity_views.py`, `ingestion/staff_views.py`, `daroobank/test_staff_grant_paths.py` (`test_a_superuser_reaches_every_route_without_any_explicit_grant`), `daroobank/test_staff_method_sweep.py` (login `PUT`), `daroobank/test_staff_header_inventory.py`, `daroobank/test_authorization_review_drift.py`, `daroobank/test_mfa_implementation_plan.py` (which pins `AUTHENTICATION_BACKENDS` unset) and `daroobank/test_secret_rotation_plan.py` | decisions 5, 6 and 7: historical revision lineage SoD, PostgreSQL constraints, unlocked `recheck_actor` races and public API contract drift |
| **D. Enforce lineage-wide separation of duties, lock-ordered `recheck_actor` across user/group tables, and PostgreSQL `CHECK` or trigger constraints** | traverse ancestor creators in `clinical/services.py` and `catalog/identity.py` review checks, review lock order across `auth_user`, `auth_user_groups`, `auth_group_permissions` and multi-table graphs so `15` `lock=False` `recheck_actor` sites serialize account/group/permission changes safely, and add database constraints/triggers beyond today's `37` `public` `CHECK` constraints (`138` total constraints) | `daroobank/actor_recheck.py` plus the 5 domain review/service modules, `1`–`5` migrations (`17` → `18+` project migrations, `32` → `33+` applied) moving schema pins in `daroobank/test_migration_reversibility.py`, `daroobank/test_populated_rollback_drill.py`, `daroobank/test_postgresql_inspection.py`, `daroobank/test_mfa_implementation_plan.py`, `daroobank/test_read_audit_plan.py`, `daroobank/test_backup_recovery_plan.py` and `docs/PHASE1_RELEASE_EVIDENCE.md`, plus concurrency suites under `catalog/`, `clinical/`, `pricing/` and `sources/` | decisions 1, 3, 6 and 7: what replaces `STAFF_PORTAL_ENABLED = DEBUG`, future API tokens, OpenAPI drift and whether DB triggers hold under bulk/ORM repair |
| **E. Expose the sketched institutional/v1 endpoints with scoped tokens and endpoint/object permission enforcement** | introduce token persistence/scopes/revocation, Bearer/header authentication middleware, endpoint and object-level permission checks on new API routes, `securitySchemes` in `docs/openapi.json`, and new paths from `docs/API_DESIGN.md` | at least 1 new model (`24` → `25+` project models, `33` → `34+` tables), new middleware (`13`/`14` entries), new `requirements.in` package if JWT/asymmetric signing is selected (`4` → `5+` direct pins, moving `requirements.txt` `94` lines / `7` names / `78` hashes and `pip-audit --strict`), `docs/openapi.json`, and moving resolver-count pins (`55` routes) in `daroobank/test_no_django_admin.py`, `daroobank/test_authorization_review_drift.py`, `daroobank/test_public_route_privacy_matrix.py`, `daroobank/test_staff_header_inventory.py`, `docs/SECRET_ROTATION_PLAN.md` and `docs/READ_AUDIT_PLAN.md` | decisions 3–5 and 8: who issues/revokes institutional keys, how key rotation interacts with tokens, and internal staff RBAC |
| **F. Decouple staff portal activation from `DEBUG` and close ADR 0191's residual gaps, the 5,000-row scan bound and CLI bypass** | replace `STAFF_PORTAL_ENABLED = DEBUG` with an explicit gate and readiness rule, replace fixed 5,000-row scan limits in `list_staff_sessions`/`revoke_staff_sessions`, tie session invalidation to DB-backed generation counters or explicit revocation on off/on transitions, gate or require actor attribution on the `6` un-gated management commands, and add request/permission audit logging | new environment variable(s) moving `daroobank/test_environment_documentation.py` (`16` read vars), `.env.example` (`12`), `compose.yaml` (`6`), `daroobank/management/commands/check_deployment_readiness.py` and `daroobank/test_deployment_readiness.py`; `daroobank/test_staff_disabled_boundary.py` and `daroobank/test_authorization_review_drift.py` (`DEBUG-only`); `daroobank/test_command_documentation.py` (`12` commands) and `daroobank/test_attribution_gap_plan.py`; plus `daroobank/test_no_read_audit.py` and `docs/READ_AUDIT_PLAN.md` if `LOGGING` becomes non-empty | decisions 3–7: replacing `DEBUG` without first resolving MFA, SoD, superuser bypass and read/write audit opens production exposure prematurely |
| **G. Defer authenticated APIs and production staff portal out of Phase 1, leaving only the 3 read endpoints** | record in `docs/API_DESIGN.md`, `docs/AUTHORIZATION_REVIEW.md`, `docs/SECURITY.md` and `docs/PHASE1_RELEASE_EVIDENCE.md` that institutional/write APIs and any non-debug staff portal are deferred out of Phase 1, leaving only the 3 public `/api/v1/*` read routes | 4 documents reworded, `daroobank/test_authorization_review_drift.py` updated if open questions are closed, `0` schema/code/dependency changes | decision 6 on whether the 3 remaining public API endpoints require Option B contract hardening and lane 2's edge rate limits (`docs/NETWORK_TLS_PLAN.md`) before exposure |

## Required behavior before any enablement

1. **Eliminate superuser and single-user/group role accumulation bypasses.** Replace implicit 41/41
   superuser permission grant with explicit, least-privilege permission enforcement on review/approval
   paths, prevent one account or group from accumulating incompatible author and reviewer permissions
   across all 16 matrix grants, and remove reliance on view-absent downstream service guards.
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
5. **Close unlocked `recheck_actor` races across account and group tables.** Move the `15`
   `lock=False` service rechecks onto lock-ordered verification covering `auth_user`,
   `auth_user_groups`, `auth_group_permissions` and `auth_user_user_permissions` so an active-status,
   group or permission revocation between check and commit cannot persist a write.
6. **Close ADR 0191's residual blockers and the 5,000-row session scan cap.** Ensure session listing
   and revocation do not stop silently at row 5,000 of `django_session`, invalidate dormant sessions
   across off/on transitions and backend changes without waiting for an observed request, and pair
   any production exposure with MFA and replay controls.
7. **Gate CLI tools, record authorization audit events and pair with lane 2's proxy controls.**
   Reconcile the 6 management commands that operate under `DEBUG=False` without web RBAC or import
   receipts, establish handler-backed audit logging (`LOGGING` is `{}` today) for grants,
   revocations, denials and superuser actions, and resolve `REMOTE_ADDR` reverse-proxy trust under
   [the network and TLS plan](NETWORK_TLS_PLAN.md) before enabling any rate-limited endpoint.

## Verification before any enablement

- Re-run the resolver, view-AST, OpenAPI, parity/header/cursor/token and HTTP probes on synthetic
  data in throwaway PostgreSQL 16.2 databases and verify every measured count in this plan: `55`
  routes (`43` staff, `12` non-staff), `0` view permission decorators (`36` inline, `2` `scan_response`
  helper, `3` downstream service), `41` matrix routes (`36` `all of`, `4` `any of`, `1` `is_staff`),
  `63` `auth_permission` rows vs `16` `ALL_PERMISSIONS`, `23` `OBJECT_ROUTES`, `13` identifier shapes,
  `9` query shapes, `1,204` closed-header responses, `4` `loads_nonfuture` signed cursors + `1` repair
  token + `0` API tokens, `3` OpenAPI paths, `8` undocumented live `200` headers, HTML
  `405`/`403`/`429` bodies, `120`-character query truncation preceding `\x00` filtering, and JSON vs
  HTML split at `4,300` vs `4,301` digits on `/api/v1/products/{id}/`.
- Re-verify the permission, group and concurrency measurements: active superuser `41/41` access,
  non-staff superuser `41/41` `403` refusal, `StaffLoginView` `PUT` HTTP 200 and `/staff/` redirect,
  group parity (`41/41` and `25/25`) and sequential `recheck_actor` refusal on group removal, `0` of
  `37` PostgreSQL `CHECK` constraints covering actor separation, `clinical` v1-author reviewing `v2`,
  `identity` v1-package author reviewing `pkg_v2`, and the unlocked `sources.review_claim` race
  committing after reviewer deactivation and password invalidation.
- Re-verify session, proxy reference and CLI boundaries: dormant session survival across an off/on
  `is_active` toggle, `5,000`-row truncation in `list_staff_sessions` and `revoke_staff_sessions`,
  `0` non-test `HTTP_X_FORWARDED_FOR` readers (referencing `docs/NETWORK_TLS_PLAN.md`), and
  `stage_price_csv` / `list_price_candidates` executing under `DEBUG=False` with `staged_by_id=None`
  and `0` receipt rows.
- Confirm that no API token model, OAuth/JWT dependency, OpenAPI security scheme, new middleware, new
  database constraint or `STAFF_PORTAL_ENABLED` change named as absent in this plan has been added,
  and recompute `daroobank/test_api_permissions_plan.py` pins rather than deleting them if a chosen
  option lands.
- Complete the empty owner, date and answer columns in `docs/AUTHORIZATION_REVIEW.md` and record
  named security, clinical and operational sign-offs in `docs/PHASE1_RELEASE_EVIDENCE.md`.
- Treat every successful run here as synthetic measurement only; no production API exposure, token
  issuance or Phase 1 gate sign-off follows from these checks.
