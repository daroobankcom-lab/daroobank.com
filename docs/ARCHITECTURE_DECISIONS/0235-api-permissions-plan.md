# 0235 — the API and permissions plan, and what this boundary enforces

Date: 2026-11-27
Status: accepted
Suite: `daroobank/test_api_permissions_plan.py`

## Context

Seven documents or records govern this repository's API, sessions and permission boundary without
signing off its rules or measuring what sits outside the parity suites.
[PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) summarizes **API and permissions** as
*"Versioned OpenAPI and selected server-side authorization tests exist"* and keeps the gate open:
*"approve each route's requirement, approve exposure and permissions for the intended deployment, and
add threat modeling and an independent security assessment."* [API_DESIGN.md](../API_DESIGN.md)
sketches 11 additional public and internal endpoints beyond the 3 implemented `/api/v1/*` routes
along with scoped institutional/mobile API tokens, while stating *"The rest of this document is a
proposed contract, not running endpoints"* and *"405 and CSRF errors are not part of the API JSON
error schema."* [AUTHORIZATION_REVIEW.md](../AUTHORIZATION_REVIEW.md) derives its 55-route table from
the live resolver and carries blank owner/date/answer cells under *"Status: the inventory is derived
and drift-checked; the judgement is unsigned."* [SECURITY.md](../SECURITY.md) asks for *"Default
deny; server-side object-level authorization and separation of author/reviewer. Users may hold
multiple roles; implement auditable permission grants, revocation and periodic review"* and assigns
*"Super administrator | Manage roles/security configuration; no automatic clinical approval bypass."*
[DEPLOYMENT.md](../DEPLOYMENT.md) states *"No deployment has been performed or authorized."* For the
residual session-revocation blocker, [ADR 0191](0191-staff-session-revocation-gap.md) records that
*"the revival scenario named below is closed by"* [ADR 0213](0213-durable-session-invalidation.md)
while leaving unobserved transitions, in-flight requests past the guard, backend removal, MFA,
replay protection, session inventory and production procedure open. And on client IP throttling behind
a reverse proxy, [the network and TLS plan](../NETWORK_TLS_PLAN.md)
([ADR 0234](0234-network-tls-plan.md)) establishes that *"`HTTP_X_FORWARDED_FOR` is read by 0
non-test modules"* and that rate/size limits belong at the edge — referenced here rather than
re-priced.

The route-parity, denial-parity, identifier/query, CSRF, method, header, grant-path and redirect
suites ([ADR 0200](0200-staff-authorization-matrix.md) through
[ADR 0215](0215-generated-authorization-review.md)) verify consistency against declared
requirements inside `STAFF_PORTAL_ENABLED = DEBUG`. They did not measure which routes rely on
view-body, helper or downstream-service guards with **0** view permission decorators, how signed
cursors and session/CSRF tokens compare against zero API tokens, whether `docs/openapi.json` matches
every live response (`400`, `403`, `404`, `405`, `429`, response headers and parameter limits),
whether active superusers or group/single-user grants bypass separation-of-duties intent, whether
revision chains break author/reviewer separation, how unlocked `recheck_actor` calls behave under
concurrency, when dormant sessions evade revocation, or how management CLI tools interact with web
authorization. [API_PERMISSIONS_PLAN.md](../API_PERMISSIONS_PLAN.md) follows the house model of
[ADR 0230](0230-mfa-implementation-plan.md) through [ADR 0234](0234-network-tls-plan.md): measure
first on live code and synthetic PostgreSQL 16.2 databases, price every option against exact repo
pins, leave eight blocking decisions open with no invented owner, reference lane 2's proxy decision
without re-pricing it, and implement nothing.

## Decision

Measure the route/decorator surface, OpenAPI contract, parity/CSRF/method/header/cursor shapes,
permission/group/SoD boundaries, concurrency races, ADR 0191 session limits and CLI boundaries on
live code and synthetic PostgreSQL 16.2 runs, publish
[API_PERMISSIONS_PLAN.md](../API_PERMISSIONS_PLAN.md) with counted option prices and eight open
decisions, and implement no authorization, token or API control.

1. **The plan records live measurements across five subsections.** Under `## What is true today,
   measured`, it covers the 55-route URL surface and decorator-versus-service split (`0` permission
   decorators; `36` inline, `2` `scan_response`-delegated, `3` downstream-service `inspect_lineage`/
   `inspect_manifest` guards, `2` decorator-free auth CBVs, `2` decorator-free health probes), the
   denial/identifier/query/CSRF/method/header parity inventories (`23` `OBJECT_ROUTES`, `13`
   identifiers, `9` queries, `5` CSRF failure modes, `5` `EXPECTED_ALLOW` strings across `1,204`
   responses), `docs/openapi.json` versus live HTTP behavior and `4` `loads_nonfuture` cursors + `1`
   repair token + `0` API tokens, active superuser bypass (`41/41`), sequential `Group` equivalence
   without exclusivity or lock guards, `16/16` single-account permission accumulation and
   cross-revision SoD, and `15/16` unlocked `recheck_actor` sites, ADR 0191 residual blockers and the
   `5,000`-row session scan cap, `REMOTE_ADDR` reverse-proxy reference to lane 2, `6` non-debug CLI
   commands and zero in-app authorization logging (`LOGGING == {}`).
2. **Eight blocking decisions and seven priced options (A through G) stay open for an owner.** They
   explicitly cover whether to expose sketched API endpoints or keep the 3 read endpoints, how to
   enforce endpoint/object permissions for future APIs, whether `is_superuser` keeps its staff
   bypass, and how to reconcile `docs/openapi.json` against live errors, headers and throttles —
   leaving reverse-proxy `REMOTE_ADDR` trust with lane 2 (`NETWORK_TLS_PLAN.md`).
3. **`daroobank/test_api_permissions_plan.py` stays predominantly database-free.** Twelve
   `SimpleTestCase` methods verify plan structure, verbatim quotes in both source and plan, AST
   route/decorator/service enforcement, OpenAPI contract gaps, closed parity/header/cursor/token
   constants, `recheck_actor`/CLI/`LOGGING` invariants, absence of implementations and cross-links,
   while **two** `TransactionTestCase` methods re-run all live HTTP, concurrency, session-cap,
   group-grant and CLI measurements unconditionally against `daroobank.synthetic_test_settings`.
4. **Nothing was implemented.** No API token model, no OAuth/JWT dependency, no role-exclusivity rule,
   no OpenAPI change, no database `CHECK` trigger on actor/reviewer separation and no change to
   `STAFF_PORTAL_ENABLED` or CLI gating was added. `NothingImplementedTests` pins each absence.

## Measured behavior

All measurements were collected from this tree and executed live against PostgreSQL 16.2 on synthetic
accounts and fixtures:

- **URL resolver, decorator-versus-service enforcement and permission taxonomy.** Live resolution
  counts `55` named routes = `43` `staff_*` routes (`daroobank` 1, `sources` 6, `catalog` 15,
  `pricing` 8, `clinical` 9, `ingestion` 4, all under `STAFF_PORTAL_ENABLED = DEBUG`) + `12` non-staff
  routes (`2` `health_*` probes, `3` `/api/v1/*` JSON routes, `7` HTML/metadata routes). AST inspection
  finds **0** `@permission_required` or `@staff_member_required` decorators; all `41` matrix views
  carry `@login_required(login_url='staff_login')` + `@require_safe` (`27`), `@require_http_methods`
  (`9`) or `@require_POST` (`5`), pinned across routes only by `test_staff_authorization_matrix.py`,
  and implemented `36` inline, `2` in shared helper `candidate_review_scan_views.scan_response`, and
  `3` solely in downstream services (`staff_clinical_lineage`, `staff_identity_lineage`,
  `staff_import_manifest_inspection`, where `parse_scan_after` runs before `inspect_manifest`). `16`
  of `63` `auth_permission` rows are checked (`47` unreferenced); `StaffLoginView` accepts `PUT` (`200`,
  empty session) and redirects valid logins without `next` to `/staff/` (`staff_workspace`) while
  `settings.LOGIN_REDIRECT_URL == 'staff_prices'`.
- **Denials, identifier/query shapes, CSRF, method sweep and closed header inventory.** Anonymous GET
  answers `302` (`0` bytes, `Location: /staff/login/?next=...`, `11` headers). Active unauthorized
  shapes (`outsider`, `bare`, `view-only`, `is_staff=False` superuser) return byte-identical `403`
  (`135` bytes, invariant across `23` `OBJECT_ROUTES` including helper/service routes, `4`
  `<int:pk>`-resolving IDs and `9` `QUERY_VARIANTS` save `KIND_FILTER_ROUTE = 'staff_import_receipts'`;
  `9` non-matching IDs return unmatched `404` before auth). Bound deactivated accounts are flushed to
  `302` by `StaffSessionGuardMiddleware` (note `_bind_fingerprint` attaches on `daroobank.middleware`
  import). CSRF failures fail before auth and decorators (`3,174`/`2,504` bytes in `DEBUG=True`,
  `1,709`/`1,040` in `DEBUG=False`); valid tokens yield `27` safe-only `405` / `9` dual `200` / `5`
  POST-only `400`. `1,204` responses (`43 × 7 × 4`) stay within `7` pinned + `9` variable headers, `5`
  closed `EXPECTED_ALLOW` strings, `2` `text/csv` attachments and `ALLOWED_STATUSES`.
- **OpenAPI drift, cursors and session/CSRF tokens vs 0 API tokens.** `docs/openapi.json` (`271`
  lines, `3` paths, `5` responses, `3` schemas, `0` headers, `0` `securitySchemes`) omits `11` unbuilt
  `docs/API_DESIGN.md` endpoints, `8` live 200 headers, HTML `405`/`403`/`429` (`Retry-After: 60`
  after `120` reads), `MAX_QUERY_LENGTH=120` slicing before `Cc`/`Cs` filtering and the `4,300`/`4,301`
  digit HTML/JSON split. `4` signed cursors share `loads_nonfuture` (`3600` s, uncompressed, HMAC-SHA256
  digests, `512` chars on `catalog.search.cursor.v1` / `catalog.quality.irc.cursor.v1` and `1024`
  chars on `catalog.identity.lineage.v1` / `clinical.draft.lineage.v1`) alongside `projection_repair`
  (`600` s, `512` chars), `3` unsigned query cursors (`before`/`revisions_before`, `after`, `page`),
  cookie sessions (`HttpOnly`, `Lax`, `3600` s) + `staff_auth_fingerprint`
  (`daroobank.staff.session.v1`), and **0** `HTTP_AUTHORIZATION`/`Bearer` reads.
- **Superuser bypass, group grants, SoD limits, ADR 0191 blockers, proxy `REMOTE_ADDR` and CLI/audit.**
  Active staff superusers reach `41/41` matrix routes (`0` grants); `Group` grants match sequentially
  (`41/41`, `25/25`) and trigger `recheck_actor` failure after `user.groups.remove`, yet have `0`
  exclusivity/audit rules and bypass `lock=True` on `auth_user`. `16/16` permission accumulation holds;
  `0/37` DB `CHECK` constraints cover SoD; `clinical` & `catalog.identity` permit `v1`-author review of
  `v2`. `15/16` `recheck_actor` calls use `lock=False` (`sources.review_claim` race commits disabled +
  password-rotated review); ADR 0191 leaves off/on survival, passed-guard requests, backend removal,
  MFA, replay protection and production revocation (`5,000`-row `django_session` cap) open;
  `HTTP_X_FORWARDED_FOR` has `0` non-test readers while `StaffLoginView` and `PublicReadLimitMiddleware`
  use `REMOTE_ADDR` (referenced to `docs/NETWORK_TLS_PLAN.md`); `6/12` commands run under `DEBUG=False`
  (`stage_price_csv` sets `staged_by_id=None`, `0` receipts); and `LOGGING == {}` with `0` `logging`
  imports.

## Red checks

Each of the twenty-two one-by-one mutations below was applied to the clean tree, run against
`daroobank.test_api_permissions_plan` (`14` tests: `12` database-free + `2` PostgreSQL 16.2),
observed to fail non-zero, and restored byte-for-byte (SHA-256 verified):

| # | Mutation | Outcome | Caught by |
|---|---|---|---|
| 1 | Remove `**Nothing is implemented.**` from `docs/API_PERMISSIONS_PLAN.md` | Failed (`rc=1`, `failures=2`) | `NothingImplementedTests.test_no_api_token_role_sod_or_audit_control_exists_while_the_plan_says_so`, `PlanStructureTests.test_the_plan_is_an_unowned_proposal_that_implements_nothing` |
| 2 | Add `api/v1/tokens/` route to `daroobank/urls.py` | Failed (`rc=1`, `failures=2`) | `LiveApiAndPermissionsMeasurementTests.test_live_http_api_contract_denials_csrf_methods_headers_and_grants`, `UrlSurfaceAndPermissionBoundaryTests.test_resolver_and_decorator_vs_service_enforcement_inventory` |
| 3 | Add `@permission_required('catalog.view_productcandidate')` to `catalog/staff_views.py:candidates` | Failed (`rc=1`, `failures=2`) | `LiveApiAndPermissionsMeasurementTests.test_live_http_api_contract_denials_csrf_methods_headers_and_grants`, `UrlSurfaceAndPermissionBoundaryTests.test_resolver_and_decorator_vs_service_enforcement_inventory` |
| 4 | Move `parse_scan_after` below `inspect_manifest(` in `ingestion/staff_views.py` | Failed (`rc=1`, `failures=1`) | `UrlSurfaceAndPermissionBoundaryTests.test_resolver_and_decorator_vs_service_enforcement_inventory` |
| 5 | Restrict `StaffLoginView.http_method_names` in `pricing/staff_views.py` to drop `put` | Failed (`rc=1`, `failures=1`) | `LiveApiAndPermissionsMeasurementTests.test_live_http_api_contract_denials_csrf_methods_headers_and_grants` |
| 6 | Change `LOGIN_REDIRECT_URL` in `daroobank/settings.py` to `'staff_workspace'` | Failed (`rc=1`, `failures=1`) | `UrlSurfaceAndPermissionBoundaryTests.test_recheck_sites_logging_and_management_command_gates` |
| 7 | Add `securitySchemes` (`bearerAuth`) to `docs/openapi.json` | Failed (`rc=1`, `failures=1`) | `UrlSurfaceAndPermissionBoundaryTests.test_openapi_specification_omits_headers_error_codes_and_method_or_limit_responses` |
| 8 | Check raw query control characters before `MAX_QUERY_LENGTH` slicing in `catalog/views.py:search_api` | Failed (`rc=1`, `failures=1`) | `LiveApiAndPermissionsMeasurementTests.test_live_http_api_contract_denials_csrf_methods_headers_and_grants` |
| 9 | Omit `Content-Security-Policy` middleware header in `daroobank/middleware.py` | Failed (`rc=1`, `failures=1`) | `LiveApiAndPermissionsMeasurementTests.test_live_http_api_contract_denials_csrf_methods_headers_and_grants` |
| 10 | Omit `Retry-After` header on `429` in `daroobank/middleware.py` | Failed (`rc=1`, `errors=1`) | `LiveApiAndPermissionsMeasurementTests.test_live_http_api_contract_denials_csrf_methods_headers_and_grants` |
| 11 | Change `CURSOR_MAX_AGE` in `catalog/services.py` from `3600` to `7200` | Failed (`rc=1`, `failures=1`) | `UrlSurfaceAndPermissionBoundaryTests.test_signed_cursors_session_tokens_and_proxy_remote_addr_boundary` |
| 12 | Refuse `is_superuser` in `clinical/services.py:require_staff` | Failed (`rc=1`, `failures=1, errors=1`) | `LiveApiAndPermissionsMeasurementTests.test_live_http_api_contract_denials_csrf_methods_headers_and_grants`, `LiveApiAndPermissionsMeasurementTests.test_live_sod_lineage_recheck_races_dormant_sessions_and_cli_boundary` |
| 13 | Reject parent draft author in `clinical/services.py:review_draft` | Failed (`rc=1`, `errors=1`) | `LiveApiAndPermissionsMeasurementTests.test_live_sod_lineage_recheck_races_dormant_sessions_and_cli_boundary` |
| 14 | Reject prior package revision author in `catalog/identity.py:review_package` | Failed (`rc=1`, `errors=1`) | `LiveApiAndPermissionsMeasurementTests.test_live_sod_lineage_recheck_races_dormant_sessions_and_cli_boundary` |
| 15 | Pass `lock=True` to `recheck_actor` in `sources/services.py:review_claim` | Failed (`rc=1`, `failures=1, errors=1`) | `LiveApiAndPermissionsMeasurementTests.test_live_sod_lineage_recheck_races_dormant_sessions_and_cli_boundary`, `UrlSurfaceAndPermissionBoundaryTests.test_recheck_sites_logging_and_management_command_gates` |
| 16 | Remove `lock=True` from `recheck_actor` in `sources/services.py:record_claim` | Failed (`rc=1`, `failures=2`) | `LiveApiAndPermissionsMeasurementTests.test_live_sod_lineage_recheck_races_dormant_sessions_and_cli_boundary`, `UrlSurfaceAndPermissionBoundaryTests.test_recheck_sites_logging_and_management_command_gates` |
| 17 | Raise `SCAN_LIMIT` from `5000` to `10000` in `staff_security/management/commands/list_staff_sessions.py` | Failed (`rc=1`, `failures=1`) | `LiveApiAndPermissionsMeasurementTests.test_live_sod_lineage_recheck_races_dormant_sessions_and_cli_boundary` |
| 18 | Gate `stage_price_csv` on `settings.DEBUG` in `pricing/management/commands/stage_price_csv.py` | Failed (`rc=1`, `failures=1, errors=1`) | `LiveApiAndPermissionsMeasurementTests.test_live_sod_lineage_recheck_races_dormant_sessions_and_cli_boundary`, `UrlSurfaceAndPermissionBoundaryTests.test_recheck_sites_logging_and_management_command_gates` |
| 19 | Define non-empty `LOGGING` dict in `daroobank/settings.py` | Failed (`rc=1`, `failures=1`) | `UrlSurfaceAndPermissionBoundaryTests.test_recheck_sites_logging_and_management_command_gates` |
| 20 | Add `PyJWT==2.10.1` to `requirements.in` | Failed (`rc=1`, `failures=1`) | `NothingImplementedTests.test_no_api_token_role_sod_or_audit_control_exists_while_the_plan_says_so` |
| 21 | Remove `API_PERMISSIONS_PLAN.md` cross-link from `docs/SECURITY.md` | Failed (`rc=1`, `failures=1`) | `PlanConsequenceTests.test_the_neighbouring_documents_name_the_plan_and_what_it_measured` |
| 22 | Remove `0235-api-permissions-plan.md` entry from `docs/ARCHITECTURE_DECISIONS/README.md` | Failed (`rc=1`, `failures=1`) | `PlanConsequenceTests.test_the_record_states_its_decision_and_its_limits` |

## Consequences

- `docs/API_PERMISSIONS_PLAN.md` answers the **API and permissions** row of
  `docs/PHASE1_RELEASE_EVIDENCE.md` with counted options and live-measured gaps while referencing
  `docs/NETWORK_TLS_PLAN.md` for `REMOTE_ADDR` proxy trust; the row remains **Open** until an owner
  fills the judgement table in `docs/AUTHORIZATION_REVIEW.md`.
- `docs/API_DESIGN.md`, `docs/AUTHORIZATION_REVIEW.md`, `docs/SECURITY.md`, `docs/DEPLOYMENT.md`,
  `docs/OPERATIONS_RUNBOOK.md`, `docs/DEVELOPMENT_GUIDE.md`, `docs/TESTING_STRATEGY.md`,
  `docs/PHASE1_RELEASE_EVIDENCE.md` and `docs/CHANGELOG.md` cross-link the plan and this record;
  no route, permission, model, migration, setting or dependency changed.
- `daroobank/test_document_links.py` pins `DOCUMENT_COUNT = 269`, `ADR_COUNT = 235`,
  `LINK_COUNT = 1175`, `SUITE_LINE_COUNT = 25`; `daroobank/test_backup_recovery_plan.py` and
  `daroobank/test_database_migration_plan.py` pin `DOCS_MARKDOWN_COUNT = 268`,
  `daroobank/test_mfa_implementation_plan.py` and `daroobank/test_secret_rotation_plan.py` pin
  `TEST_MODULE_COUNT = 241` (plus `LOGIN_ROUTE_TESTS = 45` in the MFA suite and `45 of the 241`
  in `docs/MFA_IMPLEMENTATION_PLAN.md`), `daroobank/test_database_migration_plan.py` pins
  `TEST_MODULE_COUNT = 242`, and `daroobank/test_attribution_gap_plan.py` pins
  `TEST_MODULES_NAMING_COMMAND = 9` and `COMMAND_MENTIONS_IN_TESTS = 20`.

## Limitations

- **All runtime measurements used synthetic fixtures on throwaway local PostgreSQL 16.2 databases.**
  Throughput, query plans, real proxy headers and multi-worker production concurrency were not tested.
- **No option was implemented, evaluated for regulatory/legal compliance or assigned an owner.**
  Decisions 1–8 and the `docs/AUTHORIZATION_REVIEW.md` judgement table remain unanswered.
- **Option prices are counted from repository pins rather than prototyped.** Unlike the reverted
  in-app prototype in [ADR 0227](0227-read-audit-plan.md), exact pin failure counts for options B–F
  will depend on the concrete implementation chosen.
- **Only selected revision and race schedules were executed.** Other combinations of `identity` graph
  edits, `clinical` evidence chains, concurrent group mutations or ORM bulk updates remain outside
  the demonstrated two-step cases.
- **Non-debug CLI execution was measured inside Django `override_settings(DEBUG=False)` rather than
  separate production host privileges.** OS access controls, DB roles and process supervisors are
  outside Django's boundary.
- **The suite measures current invariants and contracts, not threat adequacy.** Passing all assertions
  confirms what the boundary enforces today; it is not a security sign-off or penetration test.
