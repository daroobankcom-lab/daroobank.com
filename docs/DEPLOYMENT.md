# Deployment

No deployable application, environment configuration, containers or production infrastructure currently exist. No deployment has been performed or authorized.

## Proposed deployment topology

TLS-terminating reverse proxy → independent Django web processes → PostgreSQL; separate scheduler and bounded worker processes → Redis queue and permitted source endpoints. Use private networks and least-privilege credentials; optionally private object storage for authorized payloads/images. Isolate worker resource quotas and egress so a crawl failure does not take down the web service. Choose provider/region only after review of Iranian connectivity, resilience, sanctions/vendor constraints, data residency and qualified local legal advice.

## Release gates

- Pin and scan dependencies and base images, generate SBOM where practical, run tests/migrations on staging and validate rollback compatibility. Encrypted secrets delivered by a secret manager; `.env.example` holds placeholders only when configuration is implemented.
- Provision TLS, secure headers, database backups and off-host encrypted retention, monitoring/alerts, access review and restore drills. Separate production from development and do not use patient data in non-production.
- Test proxy host/origin and cookies, health endpoints, database migrations, worker isolation and no internet dependency for web health. Production release requires explicit user authorization and clinical/data-source sign-off for published data.
- Use expand/contract migrations and versioned API; snapshot/backup before destructive change. Define rollback including content/cache and migration compatibility before release. Reverse proxy caching must respect private responses and invalidation.

## Proposed CI/CD

On PR: lint/type checks, unit/integration/security and dependency scanning, migration checks, RTL/accessibility checks and contract tests. On a separately authorized release: build immutable artifact, run staged smoke tests, require approval, deploy and observe. This is a plan, not an existing pipeline.
