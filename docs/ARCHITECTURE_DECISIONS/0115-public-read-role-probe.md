# ADR 0115: synthetic public-read role probe

Status: development-only test, 24 November 2026. This is not a deployment role or provisioning recipe.

## Decision and evidence

On a disposable PostgreSQL cluster, a transactional test creates a synthetic non-login, non-superuser role and grants it selected schema usage and table-level SELECT on the presentation table. It explicitly revokes public CREATE on that schema, TEMP on the test database and public table grants for the selected presentation and account tables, then uses `SET LOCAL ROLE`. The anonymous HTML search/detail and corresponding JSON endpoints return one published synthetic row. Under the same role, attempts to update the presentation, read the account table, create a normal table or create a temporary table fail with PostgreSQL `42501`. The transaction rolls back role, grant and revocation changes.

A deliberate counterexample shows why this is not a confidentiality guarantee: the API returns 404 for an unpublished synthetic presentation, but the role's table-wide SELECT can retrieve that same row directly. HTTP filtering is not PostgreSQL row-level security. A database credential with this grant can read all columns and rows of the table, not just what the application chooses to publish.

## Limits

The test uses a superuser session switching to a NOLOGIN role, not a separately authenticated network connection. It covers four anonymous endpoints and a few denied statements only; authenticated sessions, staff operations, migration operators, other tables, schemas, sequences, functions, security-definer code, memberships, default privileges, transport and availability are not assessed. The database role design and row/column confidentiality must be independently reviewed alongside the deployment architecture and data classification. No production role, grant, RLS policy, connection pool or security claim is introduced; never use this test on a valuable cluster.
