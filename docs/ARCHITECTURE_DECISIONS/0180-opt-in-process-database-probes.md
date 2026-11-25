# ADR 0180: opt-in process and database connectivity probes

Status: narrow operational foundation; not deployment approval or a complete readiness check.

## Decision

Provide `/health/live/` and `/health/ready/` only when `DAROOBANK_HEALTH_PROBES_ENABLED=1` is explicitly set. The default is disabled, including in the development Compose stack. The unauthenticated GET/HEAD liveness probe returns only `ok` and does not touch PostgreSQL. The readiness probe returns `ok` only after a default PostgreSQL connection executes `SELECT 1` and returns the expected result; supported database failures return a generic 503 `unavailable`. The database query uses `SET LOCAL statement_timeout = '1s'` inside a short transaction and refuses to alter an already active or non-autocommit transaction. Unhandled application/configuration faults are not hidden as healthy. Response bodies do not include query input, exception text, database settings, credentials, schema or application records. Health path responses, including early redirects and errors, are no-store/noindex; CSRF and ordinary host/HTTPS middleware still apply.

An enabled route is unauthenticated: restrict it at the reverse proxy/network and avoid public reachability or high-frequency polling. An external observer can infer process/database availability from status, and upstream logs can retain URLs and client addresses. The application does not enforce rate limits or proxy authorization. The one-second limit applies to PostgreSQL statement execution, not DNS, connection acquisition, TLS negotiation, network stalls, worker queuing or the complete HTTP request. Configure appropriate database connect and external probe timeouts separately; do not assume they are hard application deadlines. This probe is not included in the public catalog OpenAPI contract.

The database probe does not verify migrations, tables, privileges for all operations, disk capacity, replication lag, backup freshness, source rights, task workers, clinical safety or successful handling of public requests. It can pass while the application is unable to serve real work and can fail due to transient conditions. It must not by itself trigger destructive recovery or certify production readiness. No monitoring, alert thresholds, operator ownership or deployment infrastructure is established by this ADR.

## Evidence

Synthetic PostgreSQL tests exercise the default-off gate, exact environment opt-in, non-cacheable redirects/errors and CSRF, GET/HEAD/unsafe methods, real `SELECT 1`, a disconnected socket, timeout rollback and connection recovery, an outer transaction, and preservation of the prior session timeout. Tests do not establish complete network-failure handling or production behavior.
