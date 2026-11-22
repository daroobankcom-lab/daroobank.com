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
