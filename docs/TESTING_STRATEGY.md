# Testing strategy and performance budgets

The development slice has Django tests; see [changelog](CHANGELOG.md) for actual runs. No browser-based performance benchmark has been run. Targets below are provisional acceptance budgets, not observed performance or promises; revisit with representative Iranian traffic, hosting and device/network conditions.

## Quality gates

- **Unit/property tests:** Unicode ي/ی, ك/ک, Persian/Arabic/ASCII digits, half-space, mixed RTL/LTR; identity ambiguity, currency and exact Toman-to-Rial conversion, decimal edge cases, effective dates and price percentages including zero/missing prior value.
- **Integration/database:** foreign keys, duplicate source revision, idempotent retries, append-only history, concurrent approvals, atomic publication/rollback, backdated corrections, cache invalidation, migrations and backup restore.
- **API/security:** contract schemas, pagination stability, malicious input, rate limiting, CSRF, authentication, MFA, object authorization, reviewer separation, no drafts/raw/PHI leakage and role escalation. Dependency scans and secret scanning.
- **Frontend:** mobile RTL and mixed-direction, keyboard and screen-reader flows, WCAG 2.2 AA target, contrast, real-device usability and low-JS fallback; patient versus professional views, explicit sources, stale/unknown prices, noindex and canonical tags.
- **Ingestion:** permitted sanitized fixtures for pagination and format drift, empty/partial responses, checkpoint recovery, HTTP timeouts, rate limiting, duplicate/missing IDs, maker/strength/form/pack mismatches, anomalies, source conflict and replay. Verify failed or partial runs never supersede verified data or mark missing products discontinued. Include timezone and 23:00→01:00 cross-midnight tests.
- **Clinical:** independent reviewer checks claims, references, scope, translations and correction/withdrawal; licensed interaction dataset coverage distinguishes verified negative vs not assessed. No safety-critical tool release without independent clinical validation.

## Measurable target proposal

On a defined low-end Android test device with throttled 4G and warm cache: p75 LCP <2.5 s, CLS <0.1 and INP <200 ms for indexable pages; target initial compressed JS <50 KB for public content pages, with an explicit exception process for complex tools. On a staging dataset of 100,000 synthetic packages with representative Persian variants and recorded concurrency, target server-side search p95 <300 ms and p99 <1 s, error rate <1%; measure DB plans, cache status, CPU and dataset size. Verify crawler at maximum configured concurrency does not increase public search p95 by >20% relative to identical baseline, on documented resources. These are experimental budgets, not achieved results. Run Lighthouse/WebPageTest-style controlled browser tests and load tests, recording tool versions, hardware, sample size, dataset and network. Do not use production PHI.

## Release criteria

All relevant tests pass in CI and staging; no critical unresolved security issues; editorial/source approvals and backup restoration signed off; performance measured against agreed targets. Test failures block release. Accessibility and Persian search failures receive explicit triage rather than silent waivers.

## Local CSV staging tests

`pricing/tests.py` covers synthetic dry run and permission-assertion gating, exact identity suggestions, ambiguous/unmatched packages, stale IRC projections and changed catalog records, whole-file rejection, source URL secrets, exact Rial/Toman conversion and unrepresentable values, idempotent replay, revised assertions, no public price exposure, bounded local listing and IRC migration backfill. Tests do not establish source rights, clinical validity, production performance or database immutability.

## Development-only staff tests

`pricing/test_staff.py` exercises anonymous redirects; active staff plus permission enforcement, including group permissions; rejection of inactive and unauthorized users; CSRF login/logout; unsafe redirect rejection; read-only methods; private/no-store/noindex headers; filtering and pagination; escaped stored data; current-versus-stale suggestion handling; and the disabled-portal gate. These tests are not a penetration test or evidence of MFA, throttling, production readiness, accessibility or clinical validity.

`pricing/test_workflow.py` exercises bounded upload and atomic validation, preview/no writes, attestation and role gates, duplicate provenance, independent reviewer separation, CSRF, preliminary decisions/history, stale review/product data, inconsistent source/derived values, ambiguous matches, escaping, and absence of public prices using synthetic fixtures. The tests run on PostgreSQL and do not prove behavior under concurrent writes, DB-level immutability, source rights, visual accessibility or production security.

`catalog/test_presentation.py` covers search-to-detail navigation, shared JSON contract and eligibility, drafts and missing or out-of-range IDs, invalid/bypassed source metadata and required fields, withdrawal, HTML escaping, optional IRC, GET/HEAD-only methods, privacy headers, noindex, sitemap exclusion and the bounded candidate scan. Fixtures are synthetic; this is not browser, clinical, rights, concurrency or accessibility certification.

`catalog/test_pagination.py` covers duplicate-name page boundaries, query normalization/binding, tampering, oversized/compressed/expired/wrong-shape cursors, empty but continuable pages, validation scan limits, withdrawal/deletion/rename/key rotation, non-snapshot changes and URL encoding. `catalog/test_api_contract.py` checks response shapes and limits against the bundled contract; it validates only the schema keywords used there, not all OpenAPI semantics. The document was separately checked locally with `openapi-spec-validator==0.7.2` in an isolated temporary environment. These tests do not prove concurrent consistency, realistic load, production security or browser accessibility.

`catalog/test_intake.py` tests synthetic product CSV preview/staging, whole-file validation and size/row bounds, actor/group permissions, CSRF failure and valid-token flow, private headers, debug gate, deduplication, pagination/filtering by latest decision, independent reviewer enforcement, sequential staleness, tampered fields/source/fingerprint, escaped text, transaction rollback and absence of public catalog creation. It uses PostgreSQL and does not prove concurrent safety, immutability, source rights, browser accessibility or production security.

`catalog/test_comparisons.py` checks bounded revision/IRC clues, script escaping, permission/visibility boundaries, Persian/Arabic and digit normalization, absent IRC, changed fields, invalid/stale indexes, truncated results, no public writes and review rejection on index inconsistency. `catalog/test_candidate_migration.py` migrates a historical database state with existing valid, invalid and overlong candidate IRCs and verifies backfill without truncation. These are PostgreSQL tests, not production concurrency, full database integrity, clinical identity, source rights, browser or load validation.

`pricing/test_comparisons.py` uses synthetic records to test exact Rial/Toman differences and integer boundaries, category/unit/source/identity mismatch suppression, unknown dates, tampering and invalid Unicode, 10-revision cap, source isolation, no public leakage, permissions/debug gate, last-review filtering, pagination, normalization-empty identity rejection and conservative ambiguity over 100 indexed presentations. It is not clinical or source validation, a browser/penetration test, a production-scale load test or proof of concurrency safety.


`sources/tests.py` uses synthetic claims to exercise staff/group permissions, debug gate, private headers, independent review, CSRF, XSS escaping, URL and scope validation, date boundary labels, replay provenance, sequential stale checks, fingerprint mismatches, invalid Unicode, latest-review filters, pagination, exact-URL bounded hints, permission-gated product/price detail integration, and absence of public catalog/price writes. A mocked socket connection checks the local claim path does not make network connections; this is not a comprehensive network sandbox. Tests use PostgreSQL and do not establish source rights, legal validity, actual database immutability, concurrent behavior, penetration resistance or browser accessibility.


`ingestion/tests.py` covers default Tehran cross-midnight intervals, inclusive/exclusive boundaries, same-day intervals, calendar/leap rollover, non-UTC inputs, historical Tehran offset change, New York DST transitions and gap/fold rejection, invalid inputs, CLI JSON/error behavior, staff/group permissions, GET/HEAD-only UI, debug gate, escaped input and privacy headers. The CLI is tested under Django's DB-blocking `SimpleTestCase`; a socket-creation mock covers that path but is not a complete network sandbox. `daroobank/test_validation.py` checks shared URL/review validation, ingestion fail-closed and legacy-invalid URL reviews using synthetic fixtures. These tests do not validate a scheduler, source authorization, production clock/tzdata, concurrent execution, actual network policy, browser accessibility or production security.


`ingestion/test_receipts.py` tests product and price web stages, repeated files and suggestion recounts, preview/validation/attestation behavior, failed candidate and receipt writes rolling back together, service permissions, missing receipts for CLI/direct stages, domain-isolated list/count/detail filtering, group permissions, pagination, escaping, CSRF, debug gate, public exclusion, model guards and database count constraints. Fixtures are synthetic and tests use PostgreSQL. They do not establish source rights, original-file provenance, immutable audit, concurrency/crash safety, browser accessibility or production security.


`ingestion/test_manifest.py` uses synthetic rows to test new versus duplicate/replayed inputs, revision mapping, domain-isolated receipt links, bounded pagination, escaping, current-candidate and structural mismatch suppression, malformed Unicode, protected foreign keys, basic DB constraints, rollback on row-write/outcome errors, unchanged preview behavior, debug gate and migration of old receipts without fabricated membership. Candidate-to-receipt hints are tested for distinctness, output caps and permissions. The tests use PostgreSQL and do not prove source rights, the original file, tamper resistance, production concurrency, browser accessibility or security.


`clinical/tests.py` uses entirely fictional content to exercise role/group permissions and clinical-only login, portal gate and privacy headers, source URL/date/text validation, synthetic-data acknowledgement, XSS escaping, CSRF and methods, independent review and snapshot, sequential stale checks, branching/version relationships, immediate-parent tampering, the intentionally unverified older ancestry boundary, bounded child lists, pagination/filters, separate source-claim access and absence of public clinical content. A mocked socket-connection path is not a complete network sandbox. Tests do not establish medical validity, source permission, reviewer qualifications, full ancestry integrity, concurrency, durable audit, production security or browser accessibility.


`clinical/test_evidence.py` exercises synthetic supplementary-reference validation, permissions/group access, CSRF, deduplication and recorder preservation, per-version isolation, the ten-reference limit and fail-closed over-limit/tamper cases, sequential stale add/review forms, reviewer separation from all recorders, new/historical snapshots, legacy review migration without fabricated history, and public exclusion. Corrupted snapshots are withheld rather than displayed; tests also check private headers and XSS escaping. PostgreSQL tests and a mocked connection path do not prove source rights, medical evidence quality, complete network isolation, concurrent role separation, immutable audit, browser accessibility or production security.




`catalog/test_quality.py` exercises bounded ascending scans, page-local duplicate IRCs, drift and stricter URL warnings, current public-filter outcomes, unknown corrupt-text outcomes, no output of product/source text, read-only behavior, command validation, independent staff/group permissions, private headers, login, HTTP method/debug gate and no writes using synthetic records. A mocked socket path is not a network sandbox. These tests do not establish full-catalog uniqueness, concurrent snapshot consistency, source rights, clinical validity, browser accessibility, production security or performance.


`daroobank/test_postgresql.py` tests PostgreSQL/psycopg selection, UTF-8 Persian/English and JSONB round-trips, representative unique/index/foreign-key behavior, invalid encoding rejection, required configuration and startup wait, plus a two-connection clinical stale-review race. These synthetic tests are not proof of complete concurrency safety, disaster recovery or production performance.


`ingestion/test_concurrency.py` uses separate PostgreSQL connections and synthetic reversed CSVs, observes an advisory-lock wait via `pg_locks`, checks product/price receipt and manifest order, recorder preservation, rollback recovery, direct stages, previews and lock scopes/savepoints. `clinical/test_concurrency.py` tests competing evidence additions, the ten-reference boundary and review/add races; the older clinical stale-review race is in `daroobank/test_postgresql.py`. These tests do not establish correctness under arbitrary direct SQL, older writers, other isolation levels, all deadlocks, crashes, long-running transactions or production load.


`catalog/test_quality_irc.py` exercises indexed clues across the original batch boundary, 50-row forward pagination, published/unpublished records, stale/invalid indexes, cursor binding/tampering/expiry/anchor changes, private permissions, methods, headers, local CLI and no writes or raw data rendering. It uses synthetic PostgreSQL data and does not establish full-catalog completeness, identity, concurrent snapshot consistency, medical validity, browser accessibility or production load/security.
