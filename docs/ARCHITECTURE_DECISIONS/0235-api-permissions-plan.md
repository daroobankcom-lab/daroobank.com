# 0235 — the API and permissions plan, and what this boundary enforces

Date: 2026-11-27
Status: accepted
Suite: `daroobank/test_api_permissions_plan.py`

## Context

Five documents define or constrain this repository's API and permissions surface without signing off
its rules or measuring what sits outside the parity suites.
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
[DEPLOYMENT.md](../DEPLOYMENT.md) states *"No deployment has been performed or authorized."*

The route-parity, denial-parity, header, CSRF, method and redirect suites
([ADR 0200](0200-staff-authorization-matrix.md) through
[ADR 0215](0215-generated-authorization-review.md)) verify consistency against declared
requirements inside `STAFF_PORTAL_ENABLED = DEBUG`. They did not measure whether `docs/openapi.json`
matches every live response (`400`, `403`, `404`, `405`, `429`, response headers and parameter
limits), whether active superusers or single users bypass separation-of-duties intent, whether
revision chains break author/reviewer separation, how unlocked `recheck_actor` calls behave under
concurrency, when dormant sessions evade revocation, or how management CLI tools interact with web
authorization. [API_PERMISSIONS_PLAN.md](../API_PERMISSIONS_PLAN.md) follows the house model of
[ADR 0230](0230-mfa-implementation-plan.md), [ADR 0231](0231-secret-rotation-plan.md) and
[ADR 0232](0232-backup-recovery-plan.md): measure first on live code and synthetic PostgreSQL 16.2
databases, price every option against exact repo pins, leave eight blocking decisions open with no
invented owner, and implement nothing.

## Decision

Measure the API contract, permission, separation-of-duties, concurrency, session-scan and CLI
boundaries on live PostgreSQL 16.2 runs, publish [API_PERMISSIONS_PLAN.md](../API_PERMISSIONS_PLAN.md)
with counted option prices and eight open decisions, and implement no authorization or API control.

1. **The plan records live measurements across four subsections.** Under `## What is true today,
   measured`, it covers the 55-route URL and 16/63 permission surface (`StaffLoginView` `PUT` and
   redirect override), `docs/openapi.json` versus live HTTP behavior, active superuser bypass (`41/41`),
   single-account permission accumulation (`16/16`) and revision-lineage separation of duties, and
   in-flight locking (`15/16` unlocked `recheck_actor` sites), the `5,000`-row session scan cap, `6`
   non-debug CLI commands and zero in-app authorization logging (`LOGGING == {}`).
2. **Eight blocking decisions and seven priced options (A through G) stay open for an owner.** Options
   range from leaving the boundary unchanged (Option A) and closing OpenAPI/HTTP drift on the 3
   existing endpoints (Option B) through removing superuser bypass and role accumulation (Option C),
   lineage-wide SoD with PostgreSQL constraints (Option D), scoped institutional API tokens (Option E),
   decoupling `STAFF_PORTAL_ENABLED` from `DEBUG` plus CLI/session hardening (Option F), and deferring
   authenticated APIs and staff portal exposure out of Phase 1 (Option G).
3. **`daroobank/test_api_permissions_plan.py` pins the plan, the codebase invariants and the live
   PostgreSQL measurements.** Both structural/AST checks and live `TransactionTestCase` measurements
   run unconditionally in the default suite against `daroobank.synthetic_test_settings`, so any
   unmeasured drift in OpenAPI fields, superuser access, SoD boundaries, `recheck_actor` locks,
   session scan limits or non-debug CLI gating fails tests immediately.
4. **Nothing was implemented.** No API token model, no OAuth/JWT dependency, no role-exclusivity rule,
   no OpenAPI change, no database `CHECK` trigger on actor/reviewer separation and no change to
   `STAFF_PORTAL_ENABLED` or CLI gating was added. `NothingImplementedTests` pins each absence.

## Measured behavior

All measurements were collected from this tree and executed live against PostgreSQL 16.2 on synthetic
accounts and fixtures:

- **URL resolver and permission taxonomy.** Live resolution counts `55` named routes = `43` `staff_*`
  routes (all under `STAFF_PORTAL_ENABLED = DEBUG`) + `12` non-staff routes (`2` `health_*` probes,
  `3` `/api/v1/*` JSON routes, `7` HTML/metadata routes). Of the `41` matrix routes, `36` require
  `all of` listed permissions, `4` require `any of` cross-domain view permissions and `1`
  (`staff_workspace`) requires `is_staff` only. `ALL_PERMISSIONS` checks `16` permissions (`6` in
  `VIEW_PERMISSIONS`) out of `63` rows in `auth_permission` (`47` unreferenced permissions).
  `StaffLoginView` accepts `PUT` (`200`, empty session, consumes throttle) and redirects valid logins
  without `next` to `/staff/` (`staff_workspace`) while `settings.LOGIN_REDIRECT_URL == 'staff_prices'`.
- **OpenAPI 3.0.3 contract versus live `/api/v1/*` HTTP behavior.** `docs/openapi.json` specifies `3`
  paths, `5` response specs (`200`, `400`, `404`), `3` schemas (`Presentation`, `SearchPage`, `Error`),
  `0` response headers, `0` `securitySchemes` and `0` `403`/`405`/`429` responses, while
  `docs/API_DESIGN.md` describes `11` unbuilt endpoints. Live `200` API responses emit `8` HTTP
  headers; unsupported methods (`POST`/`PUT`/`PATCH`/`DELETE`/`OPTIONS`) return HTML `405` (`0` bytes,
  `Allow: GET, HEAD`) without CSRF enforcement and HTML `403` (`1,709` bytes) with CSRF enforcement;
  `PUBLIC_READ_LIMIT_ENABLED=True` serves `120` reads (`200`) then returns HTML `429` (`0` bytes,
  `Retry-After: 60`); `search_api` slices `q` to `MAX_QUERY_LENGTH = 120` before checking `Cc`/`Cs`
  controls (`'A'*120 + 'ZZZZ_IGNORED'` -> `200`, `'A'*10 + '\x00'` -> `400`, `'A'*120 + '\x00'` ->
  `200`); and `/api/v1/products/{id}/` returns JSON `404` for `0`, `2^63` and `4,300`-digit IDs while
  a `4,301`-digit ID hits `sys.get_int_max_str_digits()` (`4300`) inside `<int:pk>` and returns HTML
  `404` (`179` bytes in `DEBUG=False`, `25,938` bytes technical 404 in `DEBUG=True`).
- **Superuser bypass, accumulation and SoD limits.** An active `is_staff=True, is_superuser=True`
  account with `0` direct permissions and `0` groups reaches `41/41` matrix routes (`200`/`400`), while
  `is_staff=False, is_superuser=True` receives `403` on `41/41` routes yet loads `GET /staff/login/`
  (`200`). One single user can hold all `16` matrix permissions simultaneously, and `0` of `37`
  `public` `CHECK` constraints reference user/actor/reviewer columns. Direct self-review fails closed
  (`403`) across all `5` domains even for a superuser, yet Author A (`v1`) can review `v2` revised by
  Author B in both `clinical/services.py` (`review_draft`) and `catalog/identity.py`
  (`review_package` when `pkg_v1` sits on another author's product), and CLI-staged `PriceCandidate`
  rows (`staged_by_id=None`) are unreviewable (`403`) in the portal.
- **In-flight locking, session scan ceiling, CLI non-debug execution and audit.** `15` of `16`
  `recheck_actor` sites pass `lock=False`; only `sources/services.py:113` (`record_claim`) passes
  `lock=True` (blocking `auth_user` updates on `SQLSTATE 55P03` while not blocking
  `user_permissions.clear()`), and a live race on `sources.review_claim` (`lock=False`) commits a
  review whose reviewer has `is_active=False` and a changed password. Toggling `is_active` off/on
  without an intervening request preserves identical `authorization_fingerprint` (`200` at `/staff/`),
  `/api/v1/openapi.json` serves `200` while inactive, `list_staff_sessions` and
  `revoke_staff_sessions --apply` stop at row `5,000` (`scanned: 5000, matched: 0, revoked: 0`) leaving
  a target session at key `'zzzz...'` active, `6` of `12` commands run under `DEBUG=False` (with
  `stage_price_csv --commit --attest-authorized` staging `staged_by_id=None` and `0` receipts, and
  `list_price_candidates` printing JSON), and `settings.LOGGING == {}` with `0` `logging` imports.

## Red checks

Each of the twenty one-by-one mutations below was applied to the clean tree, run against
`daroobank.test_api_permissions_plan` (`13` tests on synthetic PostgreSQL 16.2), observed to fail
non-zero, and restored byte-for-byte (SHA-256 verified):

| # | Mutation | Outcome | Caught by |
|---|---|---|---|
| 1 | Remove `**Nothing is implemented.**` from `docs/API_PERMISSIONS_PLAN.md` | Failed (`failures=2`) | `PlanStructureTests.test_the_plan_is_an_unowned_proposal_that_implements_nothing`, `NothingImplementedTests.test_no_api_token_role_sod_or_audit_control_exists_while_the_plan_says_so` |
| 2 | Add `api/v1/tokens/` route to `daroobank/urls.py` | Failed (`failures=2`) | `UrlSurfaceAndPermissionBoundaryTests.test_resolver_and_permission_matrix_match_the_measured_counts`, `LiveApiAndPermissionsMeasurementTests.test_public_api_contract_drift_and_rate_limit_behavior` |
| 3 | Restrict `StaffLoginView.http_method_names` in `pricing/staff_views.py` to drop `put` | Failed (`failures=1`) | `LiveApiAndPermissionsMeasurementTests.test_superuser_bypass_permission_accumulation_and_sod_boundaries` |
| 4 | Change `LOGIN_REDIRECT_URL` in `daroobank/settings.py` to `'staff_workspace'` | Failed (`failures=2`) | `UrlSurfaceAndPermissionBoundaryTests.test_recheck_sites_logging_and_management_command_gates`, `LiveApiAndPermissionsMeasurementTests.test_superuser_bypass_permission_accumulation_and_sod_boundaries` |
| 5 | Add `securitySchemes` (`bearerAuth`) to `docs/openapi.json` | Failed (`failures=1`) | `UrlSurfaceAndPermissionBoundaryTests.test_openapi_specification_omits_headers_error_codes_and_method_or_limit_responses` |
| 6 | Check raw query control characters before `MAX_QUERY_LENGTH` slicing in `catalog/views.py:search_api` | Failed (`failures=1`) | `LiveApiAndPermissionsMeasurementTests.test_public_api_contract_drift_and_rate_limit_behavior` |
| 7 | Omit `Content-Security-Policy` middleware header in `daroobank/middleware.py` | Failed (`failures=1`) | `LiveApiAndPermissionsMeasurementTests.test_public_api_contract_drift_and_rate_limit_behavior` |
| 8 | Omit `Retry-After` header on `429` in `daroobank/middleware.py` | Failed (`errors=1`) | `LiveApiAndPermissionsMeasurementTests.test_public_api_contract_drift_and_rate_limit_behavior` |
| 9 | Refuse `is_superuser` in `clinical/services.py:require_staff` | Failed (`failures=1`) | `LiveApiAndPermissionsMeasurementTests.test_superuser_bypass_permission_accumulation_and_sod_boundaries` |
| 10 | Reject parent draft author in `clinical/services.py:review_draft` | Failed (`errors=1`) | `LiveApiAndPermissionsMeasurementTests.test_superuser_bypass_permission_accumulation_and_sod_boundaries` |
| 11 | Reject prior package revision author in `catalog/identity.py:review_package` | Failed (`errors=1`) | `LiveApiAndPermissionsMeasurementTests.test_superuser_bypass_permission_accumulation_and_sod_boundaries` |
| 12 | Pass `lock=True` to `recheck_actor` in `sources/services.py:review_claim` | Failed (`failures=1, errors=1`) | `UrlSurfaceAndPermissionBoundaryTests.test_recheck_sites_logging_and_management_command_gates`, `LiveApiAndPermissionsMeasurementTests.test_in_flight_race_dormant_sessions_scan_cap_and_nondebug_cli` |
| 13 | Remove `lock=True` from `recheck_actor` in `sources/services.py:record_claim` | Failed (`failures=2`) | `UrlSurfaceAndPermissionBoundaryTests.test_recheck_sites_logging_and_management_command_gates`, `LiveApiAndPermissionsMeasurementTests.test_in_flight_race_dormant_sessions_scan_cap_and_nondebug_cli` |
| 14 | Raise `SCAN_LIMIT` from `5000` to `10000` in `staff_security/management/commands/list_staff_sessions.py` | Failed (`failures=1`) | `LiveApiAndPermissionsMeasurementTests.test_in_flight_race_dormant_sessions_scan_cap_and_nondebug_cli` |
| 15 | Gate `stage_price_csv` on `settings.DEBUG` in `pricing/management/commands/stage_price_csv.py` | Failed (`failures=1, errors=1`) | `UrlSurfaceAndPermissionBoundaryTests.test_recheck_sites_logging_and_management_command_gates`, `LiveApiAndPermissionsMeasurementTests.test_in_flight_race_dormant_sessions_scan_cap_and_nondebug_cli` |
| 16 | Define non-empty `LOGGING` dict in `daroobank/settings.py` | Failed (`failures=1`) | `UrlSurfaceAndPermissionBoundaryTests.test_recheck_sites_logging_and_management_command_gates` |
| 17 | Add `PyJWT==2.10.1` to `requirements.in` | Failed (`failures=1`) | `NothingImplementedTests.test_no_api_token_role_sod_or_audit_control_exists_while_the_plan_says_so` |
| 18 | Remove `API_PERMISSIONS_PLAN.md` cross-link from `docs/SECURITY.md` | Failed (`failures=1`) | `PlanConsequenceTests.test_the_neighbouring_documents_name_the_plan_and_what_it_measured` |
| 19 | Define `AUTHENTICATION_BACKENDS` in `daroobank/settings.py` | Failed (`failures=1`) | `NothingImplementedTests.test_no_api_token_role_sod_or_audit_control_exists_while_the_plan_says_so` |
| 20 | Remove `0235-api-permissions-plan.md` entry from `docs/ARCHITECTURE_DECISIONS/README.md` | Failed (`failures=1`) | `PlanConsequenceTests.test_the_record_states_its_decision_and_its_limits` |

## Consequences

- `docs/API_PERMISSIONS_PLAN.md` answers the **API and permissions** row of
  `docs/PHASE1_RELEASE_EVIDENCE.md` with counted options and live-measured gaps; the row remains
  **Open** until an owner fills the judgement table in `docs/AUTHORIZATION_REVIEW.md`.
- `docs/API_DESIGN.md`, `docs/AUTHORIZATION_REVIEW.md`, `docs/SECURITY.md`, `docs/DEPLOYMENT.md`,
  `docs/OPERATIONS_RUNBOOK.md`, `docs/DEVELOPMENT_GUIDE.md`, `docs/TESTING_STRATEGY.md`,
  `docs/PHASE1_RELEASE_EVIDENCE.md` and `docs/CHANGELOG.md` cross-link the plan and this record;
  no route, permission, model, migration, setting or dependency changed.
- `daroobank/test_document_links.py` pins `DOCUMENT_COUNT = 269`, `ADR_COUNT = 235`,
  `LINK_COUNT = 1157`, `SUITE_LINE_COUNT = 25`; `daroobank/test_backup_recovery_plan.py` and
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
  edits, `clinical` evidence chains or ORM bulk updates remain outside the demonstrated two-step cases.
- **Non-debug CLI execution was measured inside Django `override_settings(DEBUG=False)` rather than
  separate production host privileges.** OS access controls, DB roles and process supervisors are
  outside Django's boundary.
- **The suite measures current invariants and contracts, not threat adequacy.** Passing all assertions
  confirms what the boundary enforces today; it is not a security sign-off or penetration test.
