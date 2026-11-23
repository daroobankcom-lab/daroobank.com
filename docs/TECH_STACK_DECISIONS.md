# Technology comparison and recommendation

Provisional decision before implementation; validate through a thin vertical slice and measurements. See [ADR 0001](ARCHITECTURE_DECISIONS/0001-initial-stack.md).

## Backend

| Candidate | Advantages | Costs / trade-offs |
|---|---|---|
| **Python, Django + Django REST Framework** (recommend) | Mature relational ORM, migrations, admin, security ecosystem; shared language for data adapters; fast development of reviewer workflows; Python analytics interoperability | Python CPU-bound processing requires separate workers; Django admin needs substantial workflow/permission hardening; avoid blocking I/O in web processes. Pin supported versions at implementation. |
| TypeScript, NestJS | Strong end-to-end types, modular DI, Node I/O, large ecosystem | More assembly for robust editorial/admin, Python analytics remains separate; type guarantees don't replace runtime validation. |
| C#, ASP.NET Core | Strong runtime/performance, mature security and typed APIs | Smaller overlap with desired Python ingestion skills; staffing/hosting ecosystem must be verified. |

Network, database indexes and source reliability usually dominate simple reads; raw framework benchmarks here would be misleading. Load test real queries before choosing additional services.

## Frontend

| Candidate | Advantages | Costs / trade-offs |
|---|---|---|
| **Django server-rendered templates + small progressive enhancements** | Low JS, SEO-readable initial HTML, simplest same-origin deployment and RTL | Rich tables/interactive tools need careful enhancement; complex future PWA may need separate client. |
| Next.js/React SSR | Strong interactive ecosystem | Additional Node runtime, JS weight, hydration and operational complexity; SEO still needs disciplined data and metadata. |
| ASP.NET Razor | SSR and low JS, cohesive if .NET backend | Different stack and team requirements. |

Use semantic RTL, self-hosted licensed Persian font with fallbacks, accessible plain HTML first. Add API-powered enhancements when justified, rather than adopting an SPA by default. A future mobile/PWA client can use the same versioned REST API.

## Data and supporting services

- **PostgreSQL**: transactional relational constraints, JSONB for evolving source payload metadata, audited migrations, full-text and `pg_trgm` for initial search. Evaluate Persian normalization explicitly; FTS is not assumed to solve Persian morphology. Re-evaluate a dedicated engine (e.g. OpenSearch/Meilisearch) when measured relevance/latency or indexing volume justifies synchronization cost.
- **Redis**: cache and Celery broker only once jobs need them. Postgres stays source of truth. Broker messages are not a durable audit or guaranteed exactly-once delivery; workers must be idempotent. Consider RabbitMQ only if delivery/routing needs demand it.
- **Celery + beat**, separate worker: retries, schedules and job isolation, with DB-level run locks/checkpoints. Confirm timezone and cross-midnight tests. No job assumes exactly-once execution.
- **Crawler**: Python source adapters using permitted official API/feed or permitted HTTP parsing; browser automation only if authorized and necessary. No bypass of CAPTCHA/authentication or source technical controls. Without permission, a reviewed manual import is the only ingestion path.
- **Object storage**: private S3-compatible store only if lawful retention of raw files or product images is needed; controlled access, lifecycle and backups. No object store is needed for a documentation-only repository.
- **Vector search**: none initially. If a reviewed AI pilot needs semantic retrieval, compare pgvector with a dedicated service using measured retrieval quality, isolation and scale. It never replaces citations or clinical review.
- **Deployment**: Linux containers/processes, reverse proxy, web, database, scheduled workers, monitoring and backups on infrastructure chosen after Iranian connectivity, data residency, legal and operational review. Scale processes independently; separate databases/hosts when justified. No chosen cloud vendor or deployed environment yet.
- **Interfaces**: HTTPS JSON REST under `/api/v1/`, OpenAPI contract, consistent pagination and errors, scoped authorization and optional later webhooks. Native clients, Python or independent AI access only documented interfaces; no direct database coupling.
