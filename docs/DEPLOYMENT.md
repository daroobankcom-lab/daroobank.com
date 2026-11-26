# Deployment

A development Django application, PostgreSQL-only configuration, `.env.example` and a development Compose stack exist; there is no production deployment configuration or infrastructure. The Compose stack and development server are not suitable for production. No deployment has been performed or authorized.

## Non-debug configuration prerequisites

Non-debug startup requires an explicit `DAROOBANK_SECRET_KEY` and `DAROOBANK_ALLOWED_HOSTS`. The key must meet the shape checks in [ADR 0183](ARCHITECTURE_DECISIONS/0183-nondebug-config-guards.md); those checks cannot establish randomness or secrecy. Supply a unique randomly generated key through an approved secret manager. List only authorized ASCII hostnames (IDNA/punycode for international names) or bracketed IPv6 addresses, without ports or URLs; `*` is refused and `.example.org` trusts all of its subdomains. Changing a key affects existing signatures and sessions; no production rotation policy is implemented. These requirements do not configure a production deployment or grant authorization.

## Optional HSTS header

HSTS is off unless `DAROOBANK_HSTS_SECONDS` is explicitly set to a positive value outside debug. Before using it, review HTTPS certificates, proxy behavior, affected hosts and recovery: browsers cache this policy, and later setting the option to zero does not clear an existing browser policy. The application does not enable subdomain inclusion or preload; an upstream proxy may independently set HSTS. See [ADR 0185](ARCHITECTURE_DECISIONS/0185-opt-in-hsts.md).

## Optional proxy scheme configuration

For a separately reviewed non-debug TLS proxy only, `DAROOBANK_TRUST_PROXY_SSL_HEADER=1` requires an explicit `DAROOBANK_TRUSTED_PROXY_CIDRS` list. The application accepts only a single `http` or `https` value from an immediate peer in those networks. This is **not** a firewall or proof that the peer is an authorized proxy: the proxy must overwrite incoming forwarding headers, preserve the approved Host, and the app must be network-restricted. The flag is off by default and ignored in debug. Do not enable it until the complete topology is reviewed and tested; see [ADR 0184](ARCHITECTURE_DECISIONS/0184-trusted-proxy-scheme.md).

## Optional minimal operational probes

`DAROOBANK_HEALTH_PROBES_ENABLED=1` opts in to unauthenticated `/health/live/` and `/health/ready/` GET/HEAD paths; the default is off. Liveness only checks that the process can return a response, while readiness performs a narrow default PostgreSQL `SELECT 1`, not a complete service or migration check. A failure returns 503 without database details. Network/proxy restrictions, polling limits, host and HTTPS configuration, response deadlines, monitoring and incident ownership remain external responsibilities. A PostgreSQL statement timeout is not a hard request deadline. See [ADR 0180](ARCHITECTURE_DECISIONS/0180-opt-in-process-database-probes.md); enabling these paths is not production authorization. For the wider settings and migration shape, `manage.py check_deployment_readiness` reports ten required checks and the conditions that still need a decision in one JSON document; it is not monitoring, serves no request and does not replace these probes ([ADR 0217](ARCHITECTURE_DECISIONS/0217-deployment-readiness-report.md)).

## Proposed deployment topology

TLS-terminating reverse proxy → independent Django web processes → PostgreSQL; separate scheduler and bounded worker processes → Redis queue and permitted source endpoints. Use private networks and least-privilege credentials; optionally private object storage for authorized payloads/images. Isolate worker resource quotas and egress so a crawl failure does not take down the web service. Choose provider/region only after review of Iranian connectivity, resilience, sanctions/vendor constraints, data residency and qualified local legal advice.

## Release gates

- Pin and scan dependencies and base images, generate SBOM where practical, run tests/migrations on staging and validate rollback compatibility. Encrypted secrets delivered by a secret manager; `.env.example` holds placeholders only when configuration is implemented.
- Provision TLS, secure headers, database backups and off-host encrypted retention, monitoring/alerts, access review and restore drills. Separate production from development and do not use patient data in non-production.
- Test proxy host/origin and cookies, health endpoints, database migrations, worker isolation and no internet dependency for web health. Production release requires explicit user authorization and clinical/data-source sign-off for published data.
- Run `python manage.py check_deployment_readiness` for each process before and after a deploy: it writes nothing, exits non-zero when a required check fails, and `--strict` also fails while any condition still needs a decision. A zero exit status is not a deployment authorization ([ADR 0217](ARCHITECTURE_DECISIONS/0217-deployment-readiness-report.md)).
- Use expand/contract migrations and versioned API; snapshot/backup before destructive change. Define rollback including content/cache and migration compatibility before release. Reverse proxy caching must respect private responses and invalidation.

## Development CI and proposed CI/CD

A basic `.github/workflows/checks.yml` runs on pushes and pull requests with read-only repository contents permission and a temporary PostgreSQL service: pinned Python dependencies are installed, then connection wait, migrations, pip check, Django check, migration drift check and synthetic tests run against PostgreSQL. It does not deploy, upload backups or establish production readiness. Checkout, Python setup and Node setup actions are pinned to version-specific commit SHAs checked against official release tags; checkout does not persist repository credentials. These pins require periodic review and updates and do not verify upstream behavior or secure transitive downloads. Runtime Python and image bootstrap package artifacts are hash-locked as described in the [development guide](DEVELOPMENT_GUIDE.md#maintaining-python-dependency-locks); auditor dependencies and the initial image tooling are not. Base/service image tags remain mutable and the build is not reproducible or supply-chain complete. Hosted results depend on GitHub Actions being enabled.

The workflow also runs synthetic Chromium/axe checks, Compose persistence/build-context probes, and scoped PyPI/npm advisory scans described in [Testing strategy](TESTING_STRATEGY.md). These rely on external registries and do not scan OS packages or establish production security. Further proposed gates include comprehensive lint/type checks, security scanning, accessibility review and contract tests. On a separately authorized release: build immutable artifact, run staged smoke tests, require approval, deploy and observe. Those additional gates and release steps are plans, not implemented.
