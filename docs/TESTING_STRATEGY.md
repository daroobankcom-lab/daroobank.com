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


`daroobank/test_postgresql.py` tests PostgreSQL/psycopg selection, UTF-8 Persian/English and JSONB round-trips, representative unique/index/foreign-key behavior, invalid encoding rejection, required configuration and startup wait, including real SELECT 1 against the test database and failure for a randomly named nonexistent database, plus a two-connection clinical stale-review race. The readiness probe does not create or drop that nonexistent database. These synthetic tests are not proof of complete concurrency safety, disaster recovery or production performance.


`ingestion/test_concurrency.py` uses separate PostgreSQL connections and synthetic reversed CSVs, observes an advisory-lock wait via `pg_locks`, checks product/price receipt and manifest order, recorder preservation, rollback recovery, direct stages, previews and lock scopes/savepoints. `clinical/test_concurrency.py` tests competing evidence additions, the ten-reference boundary and review/add races; the older clinical stale-review race is in `daroobank/test_postgresql.py`. These tests do not establish correctness under arbitrary direct SQL, older writers, other isolation levels, all deadlocks, crashes, long-running transactions or production load.


`catalog/test_quality_irc.py` exercises indexed clues across the original batch boundary, 50-row forward pagination, published/unpublished records, stale/invalid indexes, cursor binding/tampering/expiry/anchor changes, private permissions, methods, headers, local CLI and no writes or raw data rendering. It uses synthetic PostgreSQL data and does not establish full-catalog completeness, identity, concurrent snapshot consistency, medical validity, browser accessibility or production load/security.


## Synthetic catalog identity tests

`catalog/test_identity.py` and `catalog/test_identity_migration.py` exercise the additive migration with pre-existing synthetic catalog data, database constraints, graph hash compatibility and query counts, and the private assertion chain, multi-ingredient ordering, validation and rollback, independent review, stale/conflicting graphs, corrupted dependencies and historical graphs, review separation and current/historical labels, escaped historical content, keyset review-history traversal, stale-review conflicts, malformed/empty management forms and duplicate components, permission and staff gate, CSRF, bounded list, public exclusion and two-connection competing PostgreSQL reviews. These synthetic tests do not prove audit integrity, clinical identity, browser accessibility, correctness against uncooperative writers or production readiness. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).


## Synthetic package correction tests

`catalog/test_identity_revision.py` covers branch creation, immutability, reviewer separation, unchanged public records and parent reviews, source and form validation, malformed links and latest reviews, rollback, permissions, CSRF, scoped cursor paging and PostgreSQL two-connection correction/review races. `catalog/test_identity_revision_migration.py` migrates populated synthetic 0005 identity data to 0006 and checks preservation without backfill. Tests do not prove authenticity, whole ancestry, clinical equivalence, browser accessibility or production readiness. See [ADR 0013](ARCHITECTURE_DECISIONS/0013-synthetic-package-revisions.md).


## Synthetic ingredient, formulation and product correction tests

`catalog/test_identity_component_revision.py` covers each typed correction, unchanged dependants, fixed dependencies, hashes, malformed links, rolled-back transactions, role/CSRF/gate, formset tampering, keyset pages and PostgreSQL concurrent branches including reverse ingredient lock order. `catalog/test_identity_component_revision_migration.py` upgrades populated 0006 synthetic identity records and package correction links to 0007 without backfilling. Tests do not establish ancestry authenticity, clinical equivalence, browser accessibility or production readiness. See [ADR 0014](ARCHITECTURE_DECISIONS/0014-synthetic-component-revisions.md).


## Synthetic identity ancestry inspection

`catalog/test_identity_lineage.py` exercises all four types, bounded path traversal, independent permission/group checks and staff gate, private headers, no writes or public data, invalid links and missing dependencies, tampered/wrong/expired/stale cursors, and the documented non-snapshot behavior. Tests use synthetic data on PostgreSQL and are not a browser, clinical, source-rights, authenticity or production security assessment. See [ADR 0015](ARCHITECTURE_DECISIONS/0015-synthetic-lineage-inspection.md).


## Opt-in synthetic Chromium smoke test

`daroobank/test_browser.py` and `tests/browser/smoke.cjs` use a real headless Chromium and an isolated, randomly named disposable PostgreSQL test database with synthetic-only fixtures. On Linux x86-64, install Node 22.17 or newer in the 22.x series and run from the project root after setting PostgreSQL environment variables for a role allowed to create/drop databases:

```sh
npm ci --prefix tests/browser --ignore-scripts
DAROOBANK_BROWSER_TESTS=1 python manage.py test daroobank.test_browser --settings=daroobank.browser_test_settings --noinput
```

Never point this at production or use real records; do not use `--keepdb` or parallel execution. Django creates and removes the separate test database; an interrupted run may require manual removal of the specific `test_daroobank_browser_<random>` database after verifying its identity. The live server binds to loopback, the browser subprocess receives no database credentials, and non-test-origin requests are intercepted. The bundled Chromium and libraries are extracted to a temporary directory and removed after the run. The browser runs without its OS sandbox, so use a trusted isolated development/CI environment. In the local lean container Chromium previously intermittently exited with SIGSEGV during startup before any page loaded. The test now disables GPU acceleration and removes the bundled GPU/SwiftShader launch flags; it does not retry or treat failures as passes. On this host, a separate repeated about:blank launch experiment observed 4 failures in 30 starts with the old flags and 0 failures in 130 starts with GPU disabled. This is a local observation, not a root-cause proof or reliability guarantee on other hosts; GPU/WebGL behavior is not covered. The optional test is skipped in the normal suite and is run separately in CI.

It checks real login, missing-token CSRF rejection, logout, same-origin form submissions, cross-origin referrer suppression, public synthetic search and product detail isolation, responsive overflow and RTL at 320/390/768/1440 CSS pixels, skip-link and keyboard submission for search and staff login, computed focus-outline presence/contrast for selected controls, validation error association, identity correction flows, private lineage pagination and stale review conflict. Real Tab/Enter/Tab skip-link checks cover home, about and staff login at each width, plus invalid login and selected forced-color states at 390; intentionally broken targets, focus order, visibility, fragment activation and next focus fail. The test waits for fragment navigation and actual native focus on the `tabindex="-1"` main landmark before Tab, and keeps axe out of the key sequence; the staff login no longer autofocuses the username. Removing the target tabindex on a separate synthetic page fails the test. It also uses Chromium-emulated forced colors and reduced motion to exercise focus, search, login and keyboard toggling of a synthetic-data acknowledgment. The focus check compares the computed outline against its selected opaque container, not every possible underlying pixel; deliberate missing-outline and low-contrast regressions were confirmed to fail. A separate Django CSRF-enforcing test checks matching/hostile/null origins and secure Referer cases with a valid synthetic token and cookie.

At 390 CSS pixels, axe-core 4.14.1 runs the `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa` and `wcag22aa` tagged automated rules on home, search results, invalid search query and cursor, product detail, prices, about, login, staff workspace, source date summary and inspection, both scan error pages, catalog quality, identity correction and lineage, invalid identity form and stale review states. Detected violations fail the run; inconclusive results are printed with selectors for manual review and do not pass as verified. In the local run, color contrast contained inconclusive items on each page. For the home-page lead, search hint, status text and placeholder, the test separately calculates contrast from computed colors against both opaque monotonic hero-gradient endpoints or the input background (minimum 4.5:1); a deliberate low-contrast mutation was confirmed to fail. The eyebrow and decorative captions also have direct opaque-background contrast checks, including a deliberate low-contrast mutation. Other inconclusive elements remain for manual review. Automated tools do not cover all WCAG success criteria; this narrow smoke test is not a comprehensive accessibility, screen-reader, device, other-browser, security, load, medical or production assessment.


## Resolved public-read error headers

`catalog/test_public_read_privacy.py` checks the `no-store`, `no-referrer` and `noindex` policy on resolved search, presentation and OpenAPI views for GET/HEAD, selected 400/404/500 responses, Django's 405s with `Allow: GET, HEAD`, and CSRF middleware's 403 before the view. Rejected methods perform no database queries in the tested paths. Tests also check that unrelated pages and the staff portal retain their existing policies. These checks do not cover unresolved paths, redirects before resolution, reverse proxies, log redaction, all middleware configurations or deployment security; debug error pages can disclose request data.

## Browser failure diagnostics in CI

When the isolated synthetic browser subprocess exits unsuccessfully under GitHub Actions, the test also emits a small error annotation containing only its exit code, a fixed heuristic error category and, when recognizable JavaScript stack frames exist, up to three source-line numbers in `tests/browser/smoke.cjs` (the first as the annotation location, the rest as call sites). For an exact match against a fixed allowlist of focus-check assertion labels and reasons, it also identifies the control and, where applicable, the test width. A similarly fixed allowlist identifies the page, width and phase of skip-link assertions and, for selected focus failures, only a broad active-element region; unknown messages are not copied. A subprocess timeout is annotated separately. The full output still goes to the normal failure log; no retry is performed and failures remain failures. `daroobank/test_browser_diagnostics.py` tests classification and ensures arbitrary sample error text, paths and URLs are not copied to the annotation. The summary cannot diagnose every failure (including failures before launching the subprocess), identify root cause or replace access to job logs. Run 45135591434 failed at the old home skip assertion; its log could not be retrieved and the failure could not be rerun. The cause and width are unknown. A subsequent run 45137885675 failed the login next-focus check at 1440, without recording the active element; its cause is also unknown. See [ADR 0027](ARCHITECTURE_DECISIONS/0027-keyboard-skip-navigation.md). Use synthetic fixtures only; ordinary failure logs may include test values.

## Invalid search cursor recovery

`catalog/test_pagination.py` checks malformed Unicode, NUL and overlong cursors on GET and HEAD: the request is rejected before database access, the cursor is not reflected, privacy headers remain set, and the HTML restart form retains a valid query but does not submit a cursor. Synthetic Chromium follows this recovery using Enter at four widths and runs axe on the error page at 390. These selected cases do not prove all malformed tokens safe, prevent access-log disclosure, or establish comprehensive accessibility. Cursors are signed, not encrypted, and pagination is not a snapshot. See [API design](API_DESIGN.md#development-endpoint-example).

## Invalid public search queries

`catalog/test_search_invalid_query.py` checks that NUL and surrogate code points in the retained query prefix fail before any database query; HTML and API return HTTP 400 without reflecting the bad input, including HEAD and an invalid cursor. It checks the 120-character boundary and successful responses for selected other Unicode inputs. API contract tests check the new error shape. Synthetic Chromium tests exercise an encoded NUL, the blank recovery form and resubmission at four widths, with axe at 390. These cases are not exhaustive Unicode testing, a security audit or access-log redaction. Search URLs may still be logged. See [API design](API_DESIGN.md#development-endpoint-example).

## Staff scan input-error recovery

`catalog/test_quality.py` and `sources/test_date_inspection.py` check that invalid starting IDs or date categories produce a generic Persian HTTP 400 for authorized staff, without echoing input or calling the scan service; HEAD, privacy headers and permission denial are covered. `daroobank/test_scan_responses.py` checks that restart destinations cannot be chosen arbitrarily. Synthetic Chromium checks the error, responsive layout, keyboard restart and default input at 320/390/768/1440 pixels and axe at 390. Restart clears the position and category rather than preserving a submitted value. These tests do not cover all malformed input, accessibility on real devices, URL logging or production security; private URLs may still appear in same-origin logs.

## Inspection starting-ID input syntax

The source-date and catalog-quality scan forms use required text inputs with `inputmode=numeric` and a one-to-19-digit pattern accepting ASCII, Persian and Arabic-Indic digits, including mixed forms, with visible, associated guidance. Chromium tests check exact preservation of large IDs, invalid/exponent/unsupported-digit/overlong forms, and that an invalid exponent does not submit, at four widths; they submit localized digits to both endpoints. The shared parser has boundary and 500 seeded mixed-script round-trip checks. PostgreSQL-backed tests verify equivalent batches and continued cursors, exact maximum and invalid values. Other numeral sets, signs, whitespace, separators and exponents remain invalid. The client pattern checks syntax only: some 19-digit values exceed the maximum and still receive HTTP 400 from the server. Numeric keyboards and native validation messages vary by browser/device; clients can bypass HTML validation. No JavaScript conversion to floating-point or clinical/rights inference is involved.

## Inspection form keyboard and contrast regressions

The synthetic Chromium suite uses keyboard Tab and Enter on the source date scan and catalog quality numeric filters at 320/390/768/1440 CSS pixels. It checks focus visibility/outline contrast for these selected controls; the source form is also exercised under emulated forced colors and reduced motion. Numeric-mode starting-ID text inputs share the visual styling of the other staff filters. The selected workspace warning/link, source date summary labels/counts and source scan warning, labels, input values, button and result text/link are checked at 390 using computed opaque foreground/background colors (minimum 4.5:1). The helper rejects background images, nontransparent intermediate backgrounds, opacity, filters and blending rather than inferring their contrast. Deliberately removing the category focus outline, lowering a result's contrast and adding a gradient each cause their targeted checks to fail.

This is not a screenshot/pixel comparison: it compares selected computed styles against chosen opaque containers and does not establish contrast for every pixel, overlay, hover, text run or UI state. Forced colors is emulated, not an OS/device or screen-reader test. Axe's other inconclusive items remain for manual review; these checks are not a WCAG or production accessibility certification.

## Bounded source date inspection

`sources/test_date_inspection.py` covers 50-row ascending-ID scans, one-row lookahead, category filtering after scanning, empty batches with continuation, invalid and tampered assertions, changing dates/data across requests, input bounds, authorization, debug gate, headers, no business writes or displayed source text, and one query per scan. Chromium exercises the new form and layout at 320/390/768/1440 CSS pixels and axe at 390. A mocked socket path is not a network sandbox; page limits do not bound all database work. Scans do not establish complete coverage, snapshot consistency, legal rights or production security. See the [development guide](DEVELOPMENT_GUIDE.md#development-only-source-rights-assertions).

## Page-local source date summary

`sources/tests.py` verifies the five mutually exclusive date categories on the currently displayed 20-row page, inclusive start/end boundaries, invalid claims, a single local date per response, active timezone across midnight, filter and permission isolation, empty pages, no extra per-row source queries and no business writes. Tests use synthetic assertions; the list's database-side filter/count may still scan more data than one page. The Chromium suite exercises the summary at four widths and runs axe at 390 CSS pixels. These checks do not verify source rights, authorize ingestion, prove snapshot consistency or cover manual accessibility and production performance. See the [development guide](DEVELOPMENT_GUIDE.md#development-only-source-rights-assertions).

## Private staff workspace navigation

The read-only `/staff/` page lists existing sections according to view permissions for an active staff account. It has no record counts or operational data. After login, staff land there by default unless Django accepts an explicit safe `next` destination. Shortcuts for product, price, source and clinical queues use the existing `pending` filters, meaning no review event, not all outstanding work or reviewer eligibility. Tests cover each individual permission (including a group permission), independently authorized destinations, missing and revoked permissions, safe and unsafe login redirects, inactive/non-staff/anonymous users, disabled portal, private response headers, read-only methods, CSRF logout and synthetic unreviewed versus deferred records for all four shortcuts. The Chromium smoke test exercises login, a queue shortcut and navigation at 320/390/768/1440 CSS pixels and an axe check at 390. Axe's inconclusive contrast results still require manual review. Link filtering is convenience only; destination checks and the development-only staff gate remain authoritative. This does not add monitoring, production security or approval.

## Development image build-context checks

The Compose CI job creates synthetic root and nested environment, backup, cache and `node_modules` probes in its ephemeral checkout. It checks Git ignore behavior, builds the image, checks that excluded probes are absent and `.env.example` templates outside excluded directories remain, and verifies actual PostgreSQL readiness and a nonexistent-database failure. It also checks named-volume persistence after normal shutdown. No real credentials or backups are used. This is not a secret scan, a test of every possible pathname, production image hardening, disaster recovery or a substitute for protecting pre-existing image layers and tracked history.


## CI action pin and credential review

The workflow pins the official checkout, setup-python and setup-node actions to full version-specific commit SHAs and disables checkout credential persistence. The three v7 actions run on the Node 24 Actions runtime (the browser suite itself uses Node 22), requiring a compatible hosted runner. GitHub CI must exercise both jobs after pin changes; recheck release notes, official tag-to-commit mappings and updates periodically. Pinning is not an upstream-code audit, secret scan, immutable container-image policy, or proof that package/cache downloads are safe.


## Python artifact locks

The runtime lock includes direct and transitive version pins and hashes for PyPI release artifacts, including platform-specific distributions. `daroobank/test_lock_metadata.py` tests the optional read-only PyPI metadata comparison with offline fixtures, including mismatched hashes and registry failure; the live comparison is a manual maintenance check rather than an additional CI registry gate. CI checks direct pins against `requirements.in` and installs with pip hash checking; the development image separately hash-checks its pip/setuptools upgrade. The consistency guard checks only the repository's simple pin format and is not a resolver or hash verifier. Validate updates with a clean installation and pip check, advisory scans, platform-specific testing and CI. CI also requires a deliberately incorrect Django hash to fail a fresh download for the expected reason. Locally, hash-checked wheel downloads succeeded for CPython 3.11 targets Windows x64, macOS arm64 and manylinux 2.28 arm64; pip evaluates environment markers on the host during cross-download, so this is not installation or marker validation on those operating systems. The existing psycopg-binary 3.3.9 has no manylinux2014 arm64 wheel; verify target compatibility before deployment. The lock does not establish upstream authenticity or safety, lock the image tag or initial pip, or guarantee a bit-for-bit reproducible build. See the [maintenance procedure](DEVELOPMENT_GUIDE.md#maintaining-python-dependency-locks).

## Known dependency vulnerability checks

CI runs `pip-audit==2.10.1` from isolated tool virtual environments against the resolved `requirements.txt` dependencies and, separately, the exact Python package list installed in the development web image. It also runs `npm audit --audit-level=info` against the browser-test lockfile. A known advisory, unresolved dependency or unavailable advisory registry causes the relevant step to fail; results change as registries update. These checks query external PyPI/npm services, do not send database data, and do not automatically upgrade dependencies.

A local audit on 2026-11-22 found no advisories for the resolved application requirements or npm lockfile, but did flag the locally created Python venv's older pip and setuptools. Only the ignored development venv was updated after retaining its old tool wheels and package list in the ignored `.cache/security-tool-backup/`; the application requirements and database were unchanged. The development image installs pinned newer pip and setuptools; new virtual environments can inherit different tool versions and should be independently reviewed.

These scans depend on registry advisory coverage and do not prove safety: they do not cover OS packages, bundled native libraries, Chromium binary vulnerabilities, container image contents outside Python distributions, GitHub actions, source integrity, the auditor's own dependencies or unknown vulnerabilities. Runtime requirements and the development image's pip/setuptools upgrade are now hash-locked; the initial base-image tools and auditor dependencies are not, and image tags remain mutable. CI is not a production security assessment or a substitute for updating, reviewing and scanning deployed environments.

## Source and clinical triage boundaries

`daroobank/test_review_input_boundaries.py` checks direct input types, signed bigint boundaries, permission ordering and web recovery responses for source and clinical triage. `sources/test_review_concurrency.py` and `clinical/test_concurrency.py` use separate PostgreSQL connections and selected controlled interleavings, including a clinical reference bypass that could stale a successful review before commit at that historical stage; ADR 0029 later narrows that particular existing-row race. The browser smoke covers invalid hidden review IDs and restart links at 390 pixels with synthetic data. These tests do not prove universal concurrency, authenticity, clinical safety, rights or accessibility; see [ADR 0028](ARCHITECTURE_DECISIONS/0028-source-clinical-triage-boundaries.md).

## Limited clinical reference row locks

`clinical/test_concurrency.py`, `clinical/test_reference_locking.py` and `clinical/test_parent_locking.py` exercise selected reference and immediate-parent interleavings, lock waits, rollback and outer transactions, sibling contention, a stale preloaded parent, an 11-row sentinel, non-locking reads, a deferred insert and an unprotected grandparent update. These tests do not establish predicate or whole-lineage locks, universal concurrency, provenance, clinical safety or production readiness. See [ADR 0029](ARCHITECTURE_DECISIONS/0029-clinical-reference-row-locks.md) and [ADR 0030](ARCHITECTURE_DECISIONS/0030-clinical-immediate-parent-locks.md).

## Clinical review detail comparisons

`clinical/test_evidence.py` checks independent draft/author and reference comparisons, supported missing evidence without an age claim, invalid record and contributor conflicts, unknown current states, a missing reviewer with a preserved expected-review ID, selected non-snapshot and ABA behavior, 25 displayed reviews and no per-review SQL in selected requests. A bounded reviewer lookup adds one query when reviews exist. Synthetic Chromium checks the normal detail text and layout at four widths. These checks do not establish chronology, actor qualifications, authenticity or accessibility across browsers. See [ADR 0031](ARCHITECTURE_DECISIONS/0031-clinical-detail-review-comparisons.md).

## Intake review-history missing accounts

`daroobank/test_recent_review_history.py` uses synthetic deferred-FK corruption to cover missing latest and older reviewers for source, product and price histories, expected IDs, stale and fresh submission outcomes, permissions, 25-row order and query counts. A selected separate-read race shows the lookup can be stale. Chromium covers normal history display at four widths and selected axe checks; broken accounts are covered by HTTP tests, not live browser corruption. These checks do not verify review snapshots or historical actor identity. See [ADR 0032](ARCHITECTURE_DECISIONS/0032-reviewer-lookup-in-intake-history.md).

## Missing source and clinical creator accounts

`daroobank/test_missing_recorders.py` uses synthetic deferred-FK corruption to check missing-account behavior in source review and three clinical writers, private HTTP responses, queue visibility, ordinary/inactive accounts, page-local lookup, unverified diagnostic and ancestry boundaries, selected later bypasses and an unlocked-account race. Browser smoke checks the scan warnings and normal flows at four widths. These tests do not certify attribution, concurrency or production use; see [ADR 0033](ARCHITECTURE_DECISIONS/0033-missing-source-and-clinical-creators.md).

## Missing product and price stager accounts

`daroobank/test_missing_stagers.py` exercises synthetic deferred-FK corruption for both review services and HTTP pages, all decisions, nullable price stagers, normal/inactive accounts, permission and self-review checks, comparison and receipt inspection boundaries, same-transaction bypasses, and selected unlocked-account update races. Browser smoke checks comparison and inspection warnings at four widths. The race does not establish concurrent deletion behavior or every schedule. See [ADR 0034](ARCHITECTURE_DECISIONS/0034-missing-product-and-price-stagers.md).

## Missing receipt actor accounts

`ingestion/test_missing_receipt_actors.py` uses restored, synthetic deferred-FK corruption to test product/price receipt visibility, privacy, permissions, legacy manifests, diagnostic boundaries, escaping, inactive accounts, page-local lookup and a selected stale-read bypass. Chromium exercises ordinary receipt pages and warnings at four widths. These checks do not establish receipt authenticity, concurrent deletion behavior or production readiness; see [ADR 0035](ARCHITECTURE_DECISIONS/0035-missing-receipt-actors.md).

## Identity package missing reviewers

`catalog/test_identity_missing_reviewers.py` uses synthetic deferred-FK corruption to test missing review accounts, hidden details, cursors, stale/fresh HTTP submissions, later corrections, permissions and privacy, inactive accounts, bounded lookup, selected stale reads and a graph-creator check boundary. Chromium covers normal identity views and warnings at four widths. These cases do not authenticate reviewers or demonstrate all concurrent schedules; see [ADR 0036](ARCHITECTURE_DECISIONS/0036-identity-reviewer-lookup.md).

## Identity graph creator presence

`catalog/test_identity_missing_creators.py` temporarily deletes synthetic creator accounts under deferred FKs in rollback savepoints to exercise selected graph writers and every creator position, no-write conflicts, permissions, self-review, selected HTTP paths, inactive accounts and bounded lookup. Same-transaction bypass and a separate account-deactivation test show selected limits, not concurrent deletion or every schedule. See [ADR 0037](ARCHITECTURE_DECISIONS/0037-identity-graph-creator-presence.md).

## Identity package/product concurrency and input validation

`catalog/test_identity_product_lock.py` covers synthetic PostgreSQL product update contention in both directions for review and correction, stale cached product replacement, missing product, outer-transaction lock lifetime, direct and HTTP input validation, and (after ADR 0040) a same-transaction ingredient bypass after a review snapshot. These selected schedules do not prove graph-wide isolation, deletion safety or absence of deadlocks. See [ADR 0038](ARCHITECTURE_DECISIONS/0038-identity-package-product-lock.md).

## Identity package/formulation concurrency

`catalog/test_identity_formulation_lock.py` exercises selected PostgreSQL formulation update contention in both directions for package review and correction, cache replacement, missing formulation, outer-transaction lock lifetime, a same-transaction component-update bypass and a same-transaction component-insertion bypass. It does not establish concurrent insert/deletion behavior, full graph isolation or absence of deadlocks. See [ADR 0039](ARCHITECTURE_DECISIONS/0039-identity-package-formulation-lock.md).

## Identity component and ingredient concurrency

`catalog/test_identity_component_locks.py` checks synthetic PostgreSQL locks, updates before and during selected writer operations, missing rows, outer transactions, bounded SQL, shared ingredients, deletion of the sole component before each selected writer locks it, an immediate-FK insertion blocked during review, and a deferred concurrent insertion that commits after review. Other tests demonstrate same-transaction bypasses. These are selected schedules and do not prove deadlock freedom, general concurrent deletion safety or full isolation; see [ADR 0040](ARCHITECTURE_DECISIONS/0040-identity-components-and-ingredients-locks.md).

## Identity latest-review concurrency

`catalog/test_identity_latest_review_lock.py` covers selected PostgreSQL latest-row update/delete contention, rereads, outer transactions, ordered bounded SQL, older-row mutation, same-transaction bypass, and immediate versus deferred foreign-key insertion. These scenarios are not a proof of gap locking, history isolation, deadlock freedom or reviewer authenticity. See [ADR 0041](ARCHITECTURE_DECISIONS/0041-identity-latest-review-lock.md).

## Identity write error translation

`catalog/test_identity_write_conflicts.py` covers selected actual PostgreSQL lock timeouts across eight direct and private HTTP writers, one arranged deadlock, a serialization failure with a rolled-back outer transaction, a nested savepoint timeout, injected SQLSTATE mappings and unrelated errors. These are selected schedules; tests do not set application lock timeouts or establish retry, throughput or freedom from other database failures. See [ADR 0042](ARCHITECTURE_DECISIONS/0042-identity-write-concurrency-errors.md).

## Skip-link focus diagnostics

CI run 45171291395 failed the forced-colors home skip-link visibility assertion; its job log was unavailable during investigation. The assertion now reports fixed computed visibility and geometry values (no page text, field values or URLs) on failure, while keeping the same bounds and negative tests. The failure's cause is not established and should not be conflated with earlier skip-link failures. Forced-color emulation does not establish support on real devices.
