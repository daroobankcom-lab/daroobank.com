# Deployment

A development Django application, PostgreSQL-only configuration, `.env.example` and a development Compose stack exist; there is no production deployment configuration or infrastructure. The Compose stack and development server are not suitable for production. No deployment has been performed or authorized.

## Proposed deployment topology

TLS-terminating reverse proxy → independent Django web processes → PostgreSQL; separate scheduler and bounded worker processes → Redis queue and permitted source endpoints. Use private networks and least-privilege credentials; optionally private object storage for authorized payloads/images. Isolate worker resource quotas and egress so a crawl failure does not take down the web service. Choose provider/region only after review of Iranian connectivity, resilience, sanctions/vendor constraints, data residency and qualified local legal advice.

## Release gates

- Pin and scan dependencies and base images, generate SBOM where practical, run tests/migrations on staging and validate rollback compatibility. Encrypted secrets delivered by a secret manager; `.env.example` holds placeholders only when configuration is implemented.
- Provision TLS, secure headers, database backups and off-host encrypted retention, monitoring/alerts, access review and restore drills. Separate production from development and do not use patient data in non-production.
- Test proxy host/origin and cookies, health endpoints, database migrations, worker isolation and no internet dependency for web health. Production release requires explicit user authorization and clinical/data-source sign-off for published data.
- Use expand/contract migrations and versioned API; snapshot/backup before destructive change. Define rollback including content/cache and migration compatibility before release. Reverse proxy caching must respect private responses and invalidation.

## Development CI and proposed CI/CD

A basic `.github/workflows/checks.yml` runs on pushes and pull requests with read-only repository contents permission and a temporary PostgreSQL service: pinned Python dependencies are installed, then connection wait, migrations, pip check, Django check, migration drift check and synthetic tests run against PostgreSQL. It does not deploy, upload backups or establish production readiness. Checkout, Python setup and Node setup actions are pinned to version-specific commit SHAs checked against official release tags; checkout does not persist repository credentials. These pins require periodic review and updates and do not verify upstream behavior or secure transitive downloads. Runtime Python and image bootstrap package artifacts are hash-locked as described in the [development guide](DEVELOPMENT_GUIDE.md#maintaining-python-dependency-locks); auditor dependencies and the initial image tooling are not. Base/service image tags remain mutable and the build is not reproducible or supply-chain complete. Hosted results depend on GitHub Actions being enabled.

The workflow also runs synthetic Chromium/axe checks, Compose persistence/build-context probes, and scoped PyPI/npm advisory scans described in [Testing strategy](TESTING_STRATEGY.md). These rely on external registries and do not scan OS packages or establish production security. Further proposed gates include comprehensive lint/type checks, security scanning, accessibility review and contract tests. On a separately authorized release: build immutable artifact, run staged smoke tests, require approval, deploy and observe. Those additional gates and release steps are plans, not implemented.
