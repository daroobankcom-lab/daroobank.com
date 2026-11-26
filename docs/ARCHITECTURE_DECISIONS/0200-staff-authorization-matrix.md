# ADR 0200: an endpoint-by-endpoint staff authorization matrix test

Status: **development-only synthetic evidence**, not an authorization review or an approval. The `API and permissions` release gate remains open.

## Context

Staff authorization was verified route by route, in tests written when each feature landed. Nothing enumerated the whole staff surface, so three questions had no single answer: does every `staff_*` route enforce an explicit requirement; does any route accept an account shape it should reject; and could a new route be added with no authorization test at all? ADR 0199 added a write-route inventory, but it only classified routes as write or non-write and did not state what each one requires.

## Decision

Add `daroobank/test_staff_authorization_matrix.py`. It declares one row per staff route — 41 of the 43 `staff_*` names, excluding only `staff_login` and `staff_logout` — with the route's URL kwargs, the HTTP method that reaches its authorization check, and its requirement: `staff` only, `all` of a permission set, or `any` of a permission set. Expectations are derived from that declaration through one `satisfies` helper rather than recorded per run:

| Account shape | Expectation on every route |
| --- | --- |
| anonymous | 302 to the staff login |
| active non-staff | 403 |
| active staff, no permissions | 403 unless the requirement is `staff` only |
| active staff, view permissions only | 403 unless the requirement is satisfied by view permissions |
| active staff, all sixteen permissions | never 403; 200/302/400/404/405/409 accepted, and a 302 must not go to login |
| deactivated staff with all permissions | 302 to login or 403, never content |

Detail routes use a missing primary key, so an authorized request proves authorization by returning 404 rather than by reading data, and no test writes a row: GET requests render forms, and the five POST-only review routes post empty data, which fails form validation. A further test asserts that a denial still carries the staff privacy headers, and a shape test pins exact counts — 41 routes, 1 satisfied for a permission-less staff account, 25 for a view-only account, 4 `any` routes, 5 POST-only routes, 24 routes with URL arguments — so a weakened requirement or a dropped route moves a number that must then be reviewed. The coverage test fails when a `staff_*` route appears without a declared expectation.

## Limits and consequences

- This records and enforces **current** behavior; it does not judge whether the requirements are the right ones. A route that should require a separate review permission but only requires view would pass, because the expectation is declared by the same authors as the code.
- Permission sets are granted directly to accounts. Group-based grants, superuser shortcuts, alternate authentication backends and permission caching across requests are not exercised here; the actor-recheck suites cover stale caches separately.
- Authorized requests are only asserted to be "not 403". Content correctness, pagination, filtering, private-header completeness on success paths and data scoping remain covered elsewhere or not at all.
- The deactivated-account case observes Django's session user resolution returning an anonymous user, so the route answers with a login redirect rather than 403. That is a denial, not durable revocation; ADR 0191 remains an unresolved production blocker, and in-flight requests already past authentication are covered by the ADR 0192–0199 suites instead.
- The matrix uses `TestCase` with a missing primary key for object routes, so it does not detect authorization differences that only appear for existing rows, row-level ownership, or per-object scoping such as the import receipt kind filter beyond the "no visible kinds" denial.
- Test-only synthetic data on a development-only portal. No production readiness, threat model, independent review or real-data permission follows from this.

## Selected evidence

`daroobank/test_staff_authorization_matrix.py` (8 tests) passes on synthetic PostgreSQL in normal and optimized mode: 41 routes × 6 account shapes, with per-route `subTest` labels so a failure names the route and account. The coverage assertion enumerates the live URL resolver, so the matrix cannot silently fall behind the URLconf.
