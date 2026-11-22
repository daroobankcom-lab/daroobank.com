# Development guide

At present, checkout the repository and read the documents; there is no application to start or database to migrate. Do not run a production deployment. Node and Python availability in the audit sandbox are environment facts, not installed project dependencies.

## Proposed layout

```text
server/                     Django project settings and entrypoints
  apps/catalog/             Product, organization, identifiers
  apps/clinical/            Versioned monographs and evidence
  apps/pricing/             Price observations and approvals
  apps/ingestion/           Sources, runs and adapter contracts
  apps/identity/             Roles and audit
  apps/consultation/         Future disabled boundary (when justified)
templates/                  Persian-first server-rendered pages
static/                     Self-hosted licensed assets and minimal JS
tests/                      Domain, API, security, integration and fixtures
infra/                      Local and deployment configuration when implemented
docs/                       Design, operational and decision records
```

This tree is illustrative, not present. Implement a small tested vertical slice before expanding. Define pinned supported runtime versions and a lockfile, isolated development environment, local PostgreSQL and synthetic fixtures when code exists. Introduce `.env.example` with placeholders only at that time; never commit real credentials, source payloads without permission or patient data. Follow formatter/linter and migration conventions documented by the first implementation PR.

## Working agreements

Work on the existing Arena feature branch; preserve history and do not force push. Each change updates relevant design docs and tests, and records substantive architectural changes as ADRs. Source integrations require owner permission, sanitized fixtures and documented scope. Use bilingual names only where useful, normalized search fields separately from source display strings, and explicit currency/unit/date at boundaries. Never claim unrun tests or implemented functionality.
