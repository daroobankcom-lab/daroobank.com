# Implementation changelog

Entries describe the state at each change; later entries can supersede earlier limitations.

## 2026-11-23 — isolated synthetic restore drill

**Changes:** An opt-in PostgreSQL test creates separate random synthetic source and target databases, verifies archive creation, one failed truncated restore, a full restore, migration state and a synthetic identity graph. CI runs it with matching PostgreSQL 16 client commands in a container; guarded settings refuse reuse and parallel tests.

**Limits:** This is not an encrypted/off-host backup, production recovery policy, complete-data verification or clinical assurance. Use a disposable cluster only; see ADR 0043.

## 2026-11-23 — skip-link diagnostic classification

**Changes:** Restore privacy-preserving CI classification of the structured skip-link visibility assertion; report only fixed failure categories, not the diagnostic JSON. Test malformed and injected input. A separate local 100-context forced-colors probe passed.

**Limits:** The earlier CI failure was not reproduced and its cause remains unknown; the probe is not a real-device accessibility test.

## 2026-11-23 — selected identity write concurrency errors

**Changes:** After rollback, selected private identity writer boundaries convert PostgreSQL lock-not-available, deadlock and serialization SQLSTATEs to a generic conflict; private HTTP writers return 409. Actual synthetic PostgreSQL timeout, deadlock and serialization tests cover selected schedules.

**Limits:** No timeout or automatic retry is configured; errors at a later outermost commit remain the caller's responsibility. The whole enclosing transaction must be abandoned/retried as appropriate after deadlock or serialization failure. See ADR 0042.

## 2026-11-23 — latest identity package review lock

**Changes:** Package review and correction now lock the latest existing review before their existing optimistic-token checks; correction still validates that row structurally. Synthetic PostgreSQL tests cover selected update, delete, outer-transaction, older-row and concurrent insertion cases.

**Limits:** This is not a history, absent-row or predicate lock; review creation still checks only the previous ID, and concurrent deferred inserts or later/same-transaction bypasses remain possible. See ADR 0041.

## 2026-11-22 — bounded identity component and ingredient locks

**Changes:** Selected identity dependent-creation, package-review and correction services now lock and re-read bounded existing component and ingredient rows after their applicable parent locks. Missing rows fail closed. Synthetic tests exercise both update directions across six writer paths, shared ingredients, outer transactions, bounded SQL and a deferred concurrent insertion.

**Limits:** New rows and later or same-transaction bypass mutations can still stale observations; locks are not gap locks or evidence of authenticity. Waiting/deadlocks remain possible without retry. See ADR 0040.

## 2026-11-22 — identity package formulation lock

**Changes:** Package review and correction now re-read and lock the product's formulation after the package/product locks. Missing formulations conflict. Synthetic tests cover selected contention in both directions, cached rows, missing FKs, outer transactions and still-unlocked component/ingredient changes; interface text describes the limits.

**Limits:** Ingredient/component rows and account identities remain outside this explicit lock, the reads are not a full snapshot, and a same-transaction bypass can add components. More locks can wait or deadlock; no retries or production/clinical guarantee. See ADR 0039.

## 2026-11-22 — identity package immediate-product lock

**Changes:** Package review and correction lock the package then re-read and lock its immediate product before evaluating the graph. Missing products conflict, and direct non-string review decisions now conflict rather than raising an unhashable-input type error. Synthetic PostgreSQL tests exercise both lock directions, cached reads, outer transactions, missing products, validation and an unlocked formulation mutation; Chromium checks the new scope notice.

**Limits:** This is not whole-graph isolation: formulation, ingredients, components and exclusive account locks are outside this change. More locks can wait or deadlock; no retries, clinical approval or production guarantee. See ADR 0038.

## 2026-11-22 — identity graph creator presence in writes

**Changes:** Selected identity dependent creation, package review and correction writers now reject a missing current creator anywhere in their validated current graph, with one bounded bulk account read per check. Tests cover every graph position with temporary deferred-FK account deletion, independent permissions and self-review, conflicts and rollback, inactive accounts, maximum graph size and selected unlocked/bypass behavior.

**Limits:** Structural views and lineage remain account-independent; creator accounts are not locked or authenticated, correction ancestor/link actors are not checked, and graph reads are not a snapshot. See ADR 0037.

## 2026-11-22 — identity package review account display

**Changes:** Identity package history and correction pages retain reviews but suppress details when the current reviewer account is missing, using a bounded page-local lookup. Cursor positions and real latest-review versions remain intact; missing prior accounts alone do not block later review or correction. Identity workspace and lineage pages explicitly warn that graph/link creator existence is not checked. Synthetic tests cover permissions, missing reviewers, pagination, fresh/stale submissions, account/graph boundaries and stale reads.

**Limits:** Separate reads are not a snapshot and an existing account does not establish historical identity, reviewer qualification or graph validity. Graph creator existence is still not enforced; see ADR 0036.

## 2026-11-22 — missing receipt actor accounts

**Changes:** Permission-scoped receipt lists and details retain receipts with a missing current actor and show a notice, with one page-local account lookup rather than an inner join. Related-receipt and manifest-inspection pages state that they do not check receipt actors. Synthetic tests cover orphaned product/price receipts, privacy and domain permissions, legacy data, pagination/query counts and stale reads; Chromium exercises ordinary pages at four widths.

**Limits:** An account name is not historical identity or authorization, and separate reads are not a snapshot. Receipt actor changes, other relationships, authenticity and production use are not guaranteed; see ADR 0035.

## 2026-11-22 — missing product and price stager accounts

**Changes:** Product and price review now conflict if the current stager account is missing. Orphaned products remain visible, both details show a notice and disable review, and nullable price stagers retain their separate handling. Comparisons and receipt inspections explicitly describe their narrower checks. Synthetic tests exercise service and HTTP paths, all decisions, nullable and inactive accounts, diagnostic boundaries and selected bypass/race limitations.

**Limits:** Existence is not attribution or authorization and accounts are not locked; receipt actors and other relationships are outside this change. See ADR 0034.

## 2026-11-22 — missing source and clinical creator accounts

**Changes:** Source review and the three clinical writers now reject a missing current creator account. Source and clinical queues/details retain orphaned rows; clinical text/actions are hidden and source review is disabled. The clinical queue uses a page-local author lookup. Synthetic tests cover deferred-FK corruption, direct/HTTP writes, ordinary and inactive accounts, ancestor and diagnostic boundaries, nonparticipating mutations and selected account-update races; scan pages explain that they do not check creator accounts.

**Limits:** Existence is neither historical identity nor qualification, accounts are not locked, and parent authors or other domains are not covered. Nonparticipating changes can occur after the check. Synthetic only; see ADR 0033.

## 2026-11-22 — reviewer lookup in intake histories

**Changes:** Source, product and price detail retain recent review rows even if their reviewer account is missing, show an unknown-details notice and keep the real latest review ID in the form. The bounded reviewer lookup is shared with clinical detail. Synthetic tests cover missing latest and older reviewers, stale and fresh submissions, permissions, 25-row/query bounds and non-snapshot lookup; Chromium checks normal histories at four widths.

**Limits:** A fresh review remains permitted when a previous reviewer is absent. Lookup is not a historical identity check, audit or review-snapshot validation. Missing parent authors, direct database writes and later changes remain out of scope; see ADR 0032.

## 2026-11-22 — clinical review detail comparison boundaries

**Changes:** The private detail distinguishes the reviewed draft/author comparison from the reference-set comparison, uses the existing technical classifier before displaying historical assertions, and treats missing evidence without claiming age. Invalid record decisions and reasons are suppressed, and a missing reviewer no longer hides the row or resets the expected-review ID. Tests cover corruption, contributor conflicts, separate-read and ABA behavior, the 25-row cap, query counts and synthetic Chromium at four widths.

**Limits:** Readings are non-snapshot; a match does not prove absence of intervening changes, actor qualifications, source rights or clinical correctness. A corrupted missing draft author can still hide the draft in the existing detail join. No historic data is rewritten or authenticated; see ADR 0031.

## 2026-11-22 — immediate-parent locks for clinical writes

**Changes:** Review, supplementary reference addition and revision creation now lock and re-read the immediate parent of the already locked draft before their local consistency check. Selected PostgreSQL tests cover both directions of parent updates, stale preloaded objects, sibling contention, rollback, missing parents and outer transaction lifetime.

**Limits:** Only one parent is checked; a grandparent can change during review. Later bypass writes and deferred reference inserts can still stale observations. More locks can increase waits or deadlocks and no retry is provided. This is not provenance, clinical approval, whole-lineage validation or production hardening. See ADR 0030.

## 2026-11-22 — limited clinical reference row locking

**Changes:** Review and reference addition lock the bounded existing assertion rows after the draft lock, before validation, while read-only inspection stays non-locking. PostgreSQL tests exercise waiting updates, stale conflicts, rollback, outer transaction lifetime and the 11-row sentinel. The specific concurrent existing-reference update from ADR 0028 is blocked while the write transaction holds the lock.

**Limits:** Later updates and pending new inserts can stale snapshots; a separate test demonstrates an unprotected concurrent parent update. There is no predicate or parent lock, retry, audit or clinical guarantee, and locks can wait or deadlock. See ADR 0029.

## 2026-11-22 — source and clinical triage boundaries

**Changes:** Source review rejects malformed/out-of-range IDs, boolean IDs and non-string decisions; clinical review applies the same expectation bounds and decision type check. Both hidden fields reject out-of-range values and offer a private, explicit detail-page restart. Tests exercise direct services, permissions, HTTP errors, synthetic Chromium recovery and selected PostgreSQL review races. Clinical detail warns about stale reference snapshots.

**Limits:** A controlled bypass writer can change an existing clinical reference during review despite the parent lock, leaving a coherent but already stale review snapshot. This limitation is demonstrated, not fixed. Results are not a production concurrency, source-rights, audit or clinical guarantee. See ADR 0028.

## 2026-11-22 — focusable skip target and failure categories

**Changes:** The shared main landmark is focusable by native fragment navigation but not in normal Tab order. Browser checks wait for actual landmark focus before Tab, verify a missing target tabindex fails, and report only a fixed active-element region on selected failures. This follows CI run 45137885675, which failed the login skip next-focus check at 1440 pixels.

**Limits:** The active element in that historical run was not recorded; the failure's cause remains unknown, as does the older home failure's. This change is not a demonstrated root-cause fix or screen-reader and cross-browser certification. See ADR 0027.

## 2026-11-22 — skip navigation and contrast checks

**Changes:** The staff login form no longer forces focus to username. Real-keyboard browser coverage now checks skip navigation on home, about and login, invalid-login recovery and selected forced-color states, with negative mutation tests and bounded diagnostic annotations. The test waits for the fragment before Tab and keeps axe outside the keyboard sequence. Darkened a home eyebrow and decorative captions after axe reported low contrast; selected opaque-background contrast checks were added.

**Limits:** CI run 45135591434 failed on the old home skip assertion; its full log was unavailable and rerun failed. The cause and width remain unknown, and later passes do not prove the historical failure fixed. Some axe results remain inconclusive; manual contrast, screen-reader, other-browser and device review remain necessary. See ADR 0027.

## 2026-11-22 — receipt validation reuse and product triage checks

**Changes:** Receipt detail and inspection reuse pure candidate integrity results within a single joined page/batch while checking each manifest row independently; tests cover duplicate and distinct candidates, corruption, page boundaries, operation and query counts, and a duplicate receipt in Chromium. Product review IDs are bounded in the form and direct service; PostgreSQL tests exercise selected simultaneous reviewers and candidate updates.

**Limits:** This is not an optimization of staging writes, a benchmark, a database snapshot or proof of provenance/identity. Privileged writers can bypass review protocols; no retry, audit or production guarantee is added. See ADR 0026.

## 2026-11-22 — bounded receipt-row consistency inspection

**Changes:** Added a private, permission-scoped, read-only inspection of one receipt at a time, scanning up to 50 current candidate comparisons plus lookahead and filtering only within that batch. Shared the structural and per-row checks with receipt detail. Tests cover both domains, legacy and corrupt manifests, permissions, private errors, query counts, selected non-snapshot behavior and synthetic Chromium access at four widths.

**Limits:** Technical consistency is not file provenance, source authorization, identity or clinical approval. Aggregate and row reads can observe different times; no snapshot or complete-history claim is made. Recorded price matching is not recomputed. Synthetic data only; database work and bytes are not bounded by the output cap. See ADR 0025.

**Browser-test correction:** A later recurrence of the 320px upload-result failure showed `staff.css` had not yet applied (`display: block`, no input max width) when layout was measured. The POST test now waits for page load, explicitly asserts the stylesheet's grid is applied, and exercises an intentionally delayed stylesheet; it still fails on real overflow. Earlier CSS width constraints remain, but the prior change alone did not establish the cause of every occurrence.

## 2026-11-22 — explicit synthetic projection repair

**Changes:** Added a DEBUG-only local command to preview a single presentation's projection drift and explicitly repair only derived fields after a signed, short-lived state/database recheck under a row lock and a synthetic-data attestation. Tests cover stale/deleted records, malformed inputs, time precision, failure rollback, private output, CLI flags, matching/search effects and selected PostgreSQL concurrency.

**Limits:** Repair can alter search and matching of already-published records without changing publication flags. It does not verify identity, rights or clinical content; DEBUG and attestation do not make real data safe. There is no batch operation, audited user attribution, automatic retry or production authorization. See ADR 0024. During validation, Chromium intermittently reported horizontal overflow in the 320px price preview; geometry identified the file input extending beyond the viewport. The form grid and file input now have bounded widths, and the browser smoke checks a long selected filename. Overflow failures report bounded geometry without form values; broader browser/device coverage remains incomplete.

## 2026-11-22 — presentation partial-save projection consistency

**Changes:** Nonempty partial model saves lock and read the presentation row inside a transaction before recomputing the search and IRC projections. Deprecated Django 5.2 positional save parameters are parsed before projection handling; empty updates remain no-ops. The quality inspector shares the projection field list. Synthetic PostgreSQL tests exercise overlapping partial saves, lock waits, errors, rollback, stale instances, positional calls and pricing lookup.

**Limits:** This adds locking and possible waits/deadlocks without retries. Bulk/SQL writes, historical models and stale full saves are not covered; existing inconsistencies are not automatically repaired. It does not prevent concurrent duplicate matching rows or provide source or clinical verification. See ADR 0023.

## 2026-11-22 — price review concurrency limits and validation

**Changes:** Added separate-connection PostgreSQL tests for simultaneous reviewers, locked product updates, concurrent duplicate inserts and a staging cache observed across a committed product change. The price detail page now warns that acceptance does not guarantee uniqueness. Review service and form reject out-of-range IDs, with direct service calls rejecting boolean IDs and malformed decisions.

**Limits:** One test deliberately reproduces a duplicate inserted between the fresh locked match and acceptance; it is not fixed by this change. Row locks do not protect absent matches or future writes. Tests cover selected interleavings with synthetic data, not production behavior or an approval, provenance or audit system. See ADR 0022.

## 2026-11-22 — bounded per-IRC price matching reuse

**Changes:** Added a per-invocation, eight-group LRU of bounded candidate indexes, so distinct price identities sharing an IRC can reuse one catalog query. Fresh matching and accept-review use the same matching logic, retaining conservative over-limit ambiguity and row locking. Tests compare the previous algorithm, exercise stale indexes, duplicate matches, the 100/101 boundary, eviction and changing catalog data; Chromium covers a synthetic multi-identity preview.

**Limits:** Cached IRC groups can miss catalog changes across distinct identities; eviction can mix observations from different times with older per-identity results. This is not a snapshot, validation of product or source, or production benchmark. Cache group/row limits do not bound byte size, database work or time.

## 2026-11-22 — request-local price matching reuse

**Changes:** Price CSV preview and staging now reuse one matching observation per normalized identity within each invocation, preserving per-row counts, receipts, source/payload deduplication and fresh detail and accept-suggestion review matching. The web form and CLI explain the reuse. Tests cover 5,000 repeated and distinct keys, all identity fields, ambiguous sets, replay, receipt outcomes, rollback and catalog changes between rows; synthetic Chromium exercises price preview at four widths.

**Limits:** Repeated rows may reuse a stale first observation if the catalog changes during the call; different identities can reflect different times. This is not a snapshot, production benchmark, source authorization or approval. Up to 5,000 distinct identities can still cause 5,000 matching queries; byte size, database work and time are not bounded by the cache.

## 2026-11-22 — synthetic clinical review snapshot inspection

**Changes:** Added a private read-only, per-draft, 50-review scan with page-local status filters and non-reflecting error recovery. It validates supported historical draft and supplementary-evidence snapshot structures, reports missing or invalid images and compares the snapshot draft hash/author ID to a technically consistent current version. It shows IDs and fixed statuses only. PostgreSQL tests and synthetic Chromium exercise access, tampering, pagination and selected accessibility checks.

**Limits:** Missing evidence is not proof of age. Actor existence/qualifications, current evidence, provenance, source rights and clinical correctness are not established. The scan is non-snapshot, JSON bytes and database work are not bounded, and this is not an audit or production feature. Axe contrast inconclusives require manual review.

## 2026-11-22 — synthetic clinical parent-path inspection

**Changes:** Added a private, permission-checked, read-only inspector for up to 20 immediate-parent links per section, including restartable, signed, time-limited continuation and a generic non-reflecting cursor error. It checks observed payloads and seams, stops on inconsistencies and shows IDs only. PostgreSQL and synthetic Chromium tests cover paths, boundaries, stale/malformed cursors, permissions, concurrent-change seams and selected accessibility checks.

**Limits:** The path is not a snapshot or complete history; earlier links, reviews, authors and references are not revalidated on continuation. Hash consistency is not authenticity, source rights or clinical approval. Tokens can appear in logs; this remains development-only and axe contrast inconclusives require manual review.

## 2026-11-22 — batch clinical technical inspection queries

**Changes:** Replaced per-draft reference and recorder lookups in the clinical scan with a per-draft PostgreSQL window and bulk recorder lookup, retaining the existing shared reference/cap checks and over-limit precedence. The diagnostic now runs at most three SELECTs for 50 drafts and fetches at most 11 assertions per valid draft; the write/review workflow retains its individual state and snapshots. Added boundary, reused-instance, missing-recorder and equivalence tests.

**Limits:** This is not a consistent snapshot, and fewer returned rows/queries do not bound database work or establish clinical, source or audit validity. PostgreSQL query performance on production data is unmeasured; this remains a synthetic development diagnostic.

## 2026-11-22 — synthetic clinical technical inspection

**Changes:** Added a private, view-permission-only, forward-only inspection of up to 50 draft versions per section with page-local status filtering. Reuses current draft/immediate-parent and bounded supplementary-reference checks, shows only IDs and fixed statuses, and offers non-reflecting invalid-input recovery. PostgreSQL and synthetic Chromium tests cover validation, permissions, bounded queries, paging, privacy and selected accessibility checks.

**Limits:** Not a snapshot or full lineage/review audit; no check proves authenticity, evidence quality, source rights, clinical validity or publication readiness. Query count is bounded, not database work or response size/time; this remains development-only. Axe contrast inconclusives require manual review.

## 2026-11-22 — private scan error recovery

**Changes:** Authorized staff now receive a generic Persian HTTP 400 page for invalid catalog-quality or source-date scan parameters, with a fixed local restart link and no reflected input. Restart clears position and filter. Existing authorization, validation, privacy headers and scan limits remain unchanged. Server and synthetic browser tests cover error handling, access checks and recovery.

**Limits:** Invalid URLs can still be logged; the page is not a production security or accessibility review. Automated axe checks have inconclusive contrast results requiring manual review.

## 2026-11-22 — localized staff inspection IDs

**Changes:** The source-date and catalog-quality starting-ID forms now accept Persian, Arabic-Indic and ASCII digits, including mixed scripts. A shared bounded parser maps only these digits before integer conversion; the unchanged upper limit and permissions still apply. Unit, PostgreSQL and synthetic Chromium tests cover localized values, equivalence, exact boundaries and invalid formats.

**Limits:** Other numeral sets, signs, separators and exponent notation are rejected. HTML validates syntax only; the server checks the exact maximum. Device keyboards, screen readers and all browser engines remain untested; this does not change source rights or clinical validity.

## 2026-11-22 — staff inspection ID entry

**Changes:** Replaced the two starting-ID number controls with required numeric-mode text controls and an ASCII digit syntax constraint, plus visible accessible guidance. This preserves large integer text exactly and prevents empty or exponent-form submissions that the server rejected. Existing server limits, query behavior, permissions and data remain unchanged. Synthetic Chromium checks syntax and invalid submission at four widths; PostgreSQL tests cover the boundaries.

**Limits:** HTML validates syntax, not the exact upper numeric bound; 19-digit values above the maximum still get HTTP 400 from the server. Browser keyboards and native validation messages vary; real-device and screen-reader validation remains necessary. Axe contrast inconclusives still need manual review.

## 2026-11-22 — focus failure diagnostics

**Changes:** Browser failure annotations can now identify focus checks by an exact, fixed allowlist of control labels, viewport widths and failure reasons. Tests reject unrecognized and injected messages; no arbitrary assertion text is copied. The focus criterion, application CSS and failure behavior are unchanged.

**Limits:** Five consecutive local synthetic Chromium runs passed; the previous CI focus failure was not reproduced or explained. The annotation is heuristic, covers selected checks only, and does not replace logs or a manual accessibility review.

## 2026-11-22 — browser failure call-site diagnostics

**Changes:** Include up to two additional JavaScript call-site line numbers in browser-failure annotations, without copying arbitrary stack text or paths. A synthetic multi-frame test checks both the bound and redaction.

**Limits:** CI for the public-read header change failed at a focus-outline assertion; the failing control and root cause could not be determined from the available annotation, and the full job log was inaccessible. The additional lines can help diagnose a future failure but do not fix or explain this one.

## 2026-11-22 — public-read error privacy headers

**Changes:** A narrowly scoped response middleware applies `no-store`, `no-referrer` and `noindex` to resolved search, presentation detail and OpenAPI views, including Django's 405 and CSRF 403 responses. Existing view-level headers and allowed methods remain unchanged. PostgreSQL-backed tests cover GET/HEAD, selected 400/404/500 errors, unsafe methods with and without CSRF, method `Allow`, and unrelated staff/public policy isolation.

**Limits:** The policy does not cover unresolved requests, redirects before URL resolution or upstream responses; URLs can still appear in access logs. Debug error pages can expose request data. No rate limiting, logging redaction or production security review is added.

## 2026-11-22 — synthetic browser CI diagnostics

**Changes:** Failed isolated Chromium subprocesses in GitHub Actions now add a compact error annotation with an exit outcome, fixed heuristic category and optional smoke-test source line; timeouts are also noted. Offline tests check the summary and exclusion of arbitrary sample error text. Existing failure output and failure status are unchanged; no automatic retry is added.

**Limits:** The annotation does not explain every failure or replace full logs, and ordinary test logs can still contain synthetic values. A previous browser CI failure remained unexplained because its job log was inaccessible and rerun permission was denied; this diagnostic is for future failures, not a claim about that cause.

## 2026-11-22 — public-search cursor recovery coverage

**Changes:** Added server and synthetic Chromium regression tests for the existing invalid-cursor recovery: valid query retained, invalid cursor not echoed or resubmitted, and restart by Enter. Tests cover selected malformed Unicode, NUL and overlong cursors, GET/HEAD and privacy headers, plus layout at four widths and axe at 390. No search behavior or medical data changed.

**Limits:** The checks are not exhaustive input, accessibility, privacy or security reviews; access logs can still contain search URLs, and pagination is not a snapshot. Axe's inconclusive contrast results require manual review.

## 2026-11-22 — invalid public-search query handling

**Changes:** A NUL in a public search previously caused a PostgreSQL text error. Search now rejects NUL or surrogate code points in the retained query prefix before a database query, returning HTTP 400 with a blank recovery form or an `invalid_query` API error; the invalid input is not echoed. Existing 120-character truncation and other search normalization remain unchanged. Added PostgreSQL, API contract and synthetic browser regression tests.

**Limits:** This narrow check is not general input sanitization, logging protection, rate limiting, clinical verification or production hardening. Search URLs can still appear in access logs; never enter personal data.

## 2026-11-22 — internal inspection keyboard and contrast checks

**Changes:** Styled numeric inspection filters consistently with the existing controls. Expanded synthetic Chromium coverage for keyboard focus and Enter submission on source-date and catalog-quality inspections, including forced-colors emulation for the source-date form. Added computed text contrast checks for selected workspace, source summary and scan elements; deliberate low-contrast, background-image and missing-focus mutations are rejected.

**Limits:** These checks cover selected text and controls on known opaque surfaces, not all pixels, pages, assistive technologies or devices. Axe still reports inconclusive contrast items needing manual review. The changes do not alter application data or authorization.

## 2026-11-22 — bounded source claim date inspection

**Changes:** Added a private read-only date inspection for source viewers: a 50-claim ascending-ID scan with an optional batch-local category filter and continuation even through empty batches. It shows IDs and date categories, not source names or URLs, and does not modify data. Synthetic tests cover bounded traversal, permissions, invalid inputs, live changes and browser navigation.

**Limits:** This is neither a fixed snapshot nor proof of source rights, coverage or authorization; dates and assertions are unverified. It is not an alert, a scheduler, or a production-scale monitoring system. See the [development guide](DEVELOPMENT_GUIDE.md#development-only-source-rights-assertions).

## 2026-11-22 — page-local source claim date summary

**Changes:** Added a read-only date-category summary for the currently displayed, review-filtered page of source claims, using one local date for all rows. Tests cover boundaries, invalid claims, permissions, pagination, no writes and synthetic Chromium layout/accessibility checks.

**Limits:** Counts are page-local, not a global inventory or a consistent snapshot. Dates and claims are unverified; the summary does not establish source rights or authorize use, and does not alert or calculate upcoming expiry. Database filtering/counting work is not bounded by the page size.

## 2026-11-22 — workspace landing and unreviewed queue shortcuts

**Changes:** Active staff now land on the permission-scoped workspace by default after login; Django's explicit safe `next` destination still takes precedence and its own permissions remain enforced. Added shortcuts to the existing unreviewed filters for product, price, source and clinical queues. They add no counts, data writes, new review states or permissions.

**Limits:** Unreviewed means no recorded review event, not all outstanding work or eligibility for this reviewer. Existing reviewed/deferred records are excluded. The portal remains development-only, synthetic-data-only and not a production dashboard.

## 2026-11-22 — permission-scoped staff workspace navigation

**Changes:** Added a private, read-only `/staff/` navigation page and return link from private staff pages. Active staff see only links corresponding to existing view permissions; the page does not show counts, records or operational status. Login landing behavior and destination authorization are unchanged. Synthetic role, permission revocation, privacy, CSRF logout and Chromium/axe checks cover the new page.

**Limits:** This is navigation, not a production dashboard or an authorization boundary; each destination independently enforces its permissions. No metrics, scheduler, approval, publication, audit, MFA or production security capability is added. The portal remains development-only and synthetic-data-only.

## 2026-11-22 — read-only lock metadata comparison

**Changes:** Added an optional standard-library tool to compare both checked-in Python hash locks with current PyPI release metadata, plus offline tests for mismatches, invalid input and registry failures. It does not change lock files, application logic or data. See the [maintenance procedure](DEVELOPMENT_GUIDE.md#maintaining-python-dependency-locks).

**Limits:** This compares metadata hash sets rather than downloading artifacts or independently authenticating them. Registry changes and intentional artifact subsets can cause mismatches; a match is not a safety or reproducibility guarantee.

## 2026-11-22 — Python artifact hash locks

**Changes:** Added a runtime artifact lock with transitive pins and SHA-256 hashes, a direct-pin consistency check, and a separate hash lock for the development image's pip/setuptools upgrade. CI and Docker require hash verification; direct runtime versions and application/database behavior remain unchanged. See the [maintenance procedure](DEVELOPMENT_GUIDE.md#maintaining-python-dependency-locks).

**Limits:** Hashes verify selected bytes against checked-in values, not publisher authenticity or package safety; image tags, initial image tooling and audit-tool dependencies remain outside these locks. This is not a fully reproducible or production-hardened build.

## 2026-11-22 — dependency advisory checks

**Changes:** Added isolated `pip-audit` checks for resolved Python requirements and Python packages in the development image, plus an npm audit for browser dependencies. The local requirements and npm audits found no known advisories at the time of review. Older pip/setuptools in the ignored local development venv were updated after retaining the old wheels and package list under ignored `.cache/`. The development image now installs pinned newer pip/setuptools before the unchanged application requirements; no database or business logic changed.

**Limits:** Advisory databases change; checks require external registries and do not scan operating-system packages, Chromium, bundled native libraries or the auditor's own dependencies. Version pins are not package hashes, image tags remain mutable and this is not a production security assessment. See [Testing strategy](TESTING_STRATEGY.md#known-dependency-vulnerability-checks).

## 2026-11-22 — CI action runtime and pin review

**Changes:** Updated official checkout, setup-python and setup-node actions to version-specific v7 commit SHAs using the Node 24 Actions runtime, and disabled checkout credential persistence. Preserved the Python 3.11 and browser Node 22 environments and the PostgreSQL, browser and Compose checks.

**Limits:** SHA pins need regular review and do not verify upstream code, package downloads or mutable container images. This is not a complete supply-chain or production security assessment. See [Deployment](DEPLOYMENT.md#development-ci-and-proposed-cicd).

## 2026-11-22 — development build-context and PostgreSQL readiness review

**Changes:** Excluded local environment variants and JavaScript dependencies from Git/build context while preserving `.env.example` templates; hardened Docker exclusion ordering for backups and local dependency/cache directories. Added synthetic CI probes for root/nested excluded files and template exceptions, real PostgreSQL readiness and nonexistent-database checks; no schema or data migration changed.

**Limits:** Ignore rules do not remove already tracked secrets or old image layers and are not comprehensive secret scanning. CI uses a disposable Compose volume; this is not production hardening or disaster recovery. See [Testing strategy](TESTING_STRATEGY.md#development-image-build-context-checks).

## 2026-11-22 — keyboard focus regression review

**Changes:** Removed a CSS reset that suppressed the search input's keyboard-focus outline. Extended isolated Chromium tests to check selected focus outlines and their computed contrast, submit search and staff login with Enter, and exercise search, login and a private synthetic form under emulated forced colors and reduced motion. Missing and low-contrast outline regressions were observed to fail. No business logic, data or layout changes.

**Limits:** These checks cover selected controls and computed container colors only; emulation is not an OS/device, screen-reader or complete accessibility assessment. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — browser startup investigation and contrast review

**Changes:** Investigated intermittent local headless Chromium startup failures. The isolated SSR smoke test now uses software rendering without the bundled GPU/SwiftShader flags, retaining normal web security. A local about:blank launch experiment recorded 4/30 failures with previous flags and 0/130 with GPU disabled; no automatic retry was added. Added computed-color contrast checks for selected home-page text and placeholder against the gradient endpoints and input background; a deliberately low-contrast mutation failed as expected. No product data or public layout were changed.

**Limits:** This local experiment does not prove the crash's root cause or guarantee other environments; GPU/WebGL rendering is untested. Axe continues to report other inconclusive contrast items; manual, screen-reader and device evaluation remains necessary. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — focused accessibility and CSRF regression review

**Changes:** Expanded the isolated synthetic Chromium workflow to public product detail, logout, invalid-form error associations, missing-token rejection and keyboard skip navigation. Added automated axe WCAG-tagged checks on ten representative page states, corrected three reported contrast issues and the home-link accessible name, and added same-origin, hostile/null Origin and HTTPS Referer CSRF regression cases with valid tokens. No clinical or published data were added.

**Limits:** Axe reports inconclusive contrast items for manual review. The local headless Chromium process intermittently crashed at startup on this lean container; no automatic retries hide the failure. No complete WCAG, screen-reader, device or security assessment is claimed. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — isolated Chromium checks and staff CSRF fix

**Changes:** Added opt-in, isolated synthetic PostgreSQL/Chromium smoke checks in CI. Chromium revealed that the staff `no-referrer` policy generated `Origin: null` on form submission and caused Django's CSRF protection to reject real logins. Staff responses now use `same-origin`: form requests retain a valid Origin while cross-origin requests omit referrers. Existing private cache and indexing headers are unchanged.

**Limits:** Same-origin requests and logs can contain staff URLs; never use sensitive data. The browser runs without an OS sandbox in trusted test environments. A few viewports and keyboard assertions are not full accessibility, device, security or clinical validation. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — synthetic correction ancestry inspection

**Changes:** Added permission-scoped, read-only, bounded parent-path inspection for the four private identity draft types, with signed, graph-bound continuation cursors. Invalid graphs/links stop inspection without rendering their details. Added synthetic pagination, corruption, stale/expired cursor, role, privacy, bounded-query and data-isolation tests. No schema, review or public behavior changed.

**Limits:** The path is not a snapshot, completeness or authenticity proof; earlier pages are not rechecked and parallel branches are not traversed. Hashes can be recomputed and direct writers can race. No browser/accessibility, clinical, legal or production security validation. See [ADR 0015](ARCHITECTURE_DECISIONS/0015-synthetic-lineage-inspection.md).

## 2026-11-22 — synthetic ingredient, formulation and product corrections

**Changes:** Added typed private immediate-parent correction links and forms for synthetic ingredients, formulations and products, with branch support, graph preconditions, transactional creation, scoped link navigation and validation. Existing dependants and package reviews are not rewired or transferred. Added populated migration, rollback, permission/CSRF, corruption, pagination and concurrent PostgreSQL tests.

**Limits:** Links are unverified assertions, not equivalence, whole-ancestry validation, clinical approval or audit. Formulation corrections preserve ordered ingredients; product corrections preserve formulation. Bulk/SQL and non-cooperative writers bypass guards and locks; hashes are not signatures. No real data, public changes, browser/accessibility, clinical or production assessment. See [ADR 0014](ARCHITECTURE_DECISIONS/0014-synthetic-component-revisions.md).

## 2026-11-22 — synthetic package correction branches

**Changes:** Added an additive PostgreSQL migration for private immediate-parent package correction links, fixed-product child creation, separate reason and graph hashes, latest-review and graph stale checks, atomic creation, and independent branch support. Staff can create corrections and browse validated links in bounded pages; old records and reviews remain unchanged. Synthetic migration, rollback, malformed data, permissions, CSRF, conflict and two-connection race tests included.

**Limits:** These are asserted links, not equivalence, authenticity, ancestry-wide checks or approval. Reviews cover the new graph only, not revision provenance or the parent, and do not transfer. No ingredient/formulation/product corrections, public changes or source verification. Bulk/SQL bypass guards; hashes are not signatures. No browser, clinical, legal or production security validation. See [ADR 0013](ARCHITECTURE_DECISIONS/0013-synthetic-package-revisions.md).

## 2026-11-22 — formulation formset validation

**Changes:** Ensure even an empty or malformed formulation component formset is validated and its errors rendered. The create-only form requires its fixed five management slots with no initial forms, rejects duplicate ingredient IDs before the service, and offers a fresh-form link if no component forms were rendered. The service retains its own bounds and uniqueness checks; no schema or public behavior changed.

**Limits:** The form structure check is not an authenticity or source validation mechanism. Only synthetic input is allowed. No browser/accessibility, clinical or production assessment was performed. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — identity graph read and migration checks

**Changes:** Reconstruct each formulation and its ingredient snapshots from one joined component read, reusing the result throughout the graph rather than repeatedly reading it; staff package/product queries join their direct dependencies. Payload hashes and stored graph format are unchanged. Added synthetic compatibility, query-count, PostgreSQL constraint and populated 0004-to-0005 catalog migration tests.

**Limits:** One component statement is not an isolated graph snapshot, a lock against uncooperative writers, or a production performance benchmark. Migration tests do not replace backups or restore drills. No database schema or publication behavior changed. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — identity review history navigation

**Changes:** Replaced the 25-review history cutoff with bounded descending-ID pages scoped to the selected package. The review form appears only on the newest page and uses the latest review actually shown as its optimistic precondition. A stale submission requires a reload and reassessment. Existing permissions, privacy, snapshot checks and public isolation remain in place; no schema change.

**Limits:** Pages are not a database snapshot or tamper-proof audit. Uncooperative writes and out-of-order IDs can change results; query plans and large datasets were not benchmarked. Historical content remains synthetic and unverified. No browser/accessibility or production validation. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — identity review history interpretation

**Changes:** Made the private identity graph human-readable with explicit source/actor fields and links; validate stored review graph shape, links, hashes, quantities and reviewer separation before display. Consistent reviews are labeled current or historical, with an expandable historical snapshot; invalid current graphs suppress history rather than claiming none exists. No schema or public changes.

**Limits:** Coherent snapshots can be fabricated by a database writer, and reason, decision and time are not integrity-protected. Historical comparison does not prove a real change. Bulk/SQL bypass guards; reads are not snapshots. No browser/accessibility, medical or production validation. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — private synthetic identity drafts

**Changes:** Added a private, permission-scoped draft chain from ingredients through ordered formulation components and products to packages, with asserted sources and preliminary independent package review. Bounded staff pages, conflict checks, PostgreSQL migration and synthetic tests are included. Public catalog records and eligibility are unchanged.

**Limits:** A development prototype, not a comprehensive identity model, verified source, clinical approval, equivalence or publication workflow. Hashes are not signatures; bulk ORM/SQL bypass guards, direct writes can race, and only cooperative reviews are serialized. No real patient or proprietary data, browser/accessibility, medical or production validation. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — cross-batch indexed IRC clues

**Changes:** Added a private, permission-scoped indexed IRC inspection page and local command anchored on a presentation ID. Forward signed cursors paginate bounded indexed clues across the catalog; inconsistent indexes are flagged, anchor drift or cursor tampering stops inspection, and raw names/URLs/codes are not deliberately output.

**Limits:** This is not a complete catalog-wide duplicate audit: stale indexes can hide rows and concurrent changes make pages non-snapshot. Codes and cursors are not proof of identity, rights or confidentiality; no repair or publication occurs. No browser accessibility, medical or production validation was performed.

## 2026-11-22 — PostgreSQL staging concurrency

**Changes:** Product and price committed CSV stages now take a transaction-level advisory lock for the exact source URL and domain, including direct services, CLI and web receipts. Added PostgreSQL two-connection tests for reversed import order, lock waiting, rollback, preview, receipt integrity and concurrent clinical evidence/triage. No schema or publication behavior changed.

**Limits:** The lock is cooperative, may wait without an application timeout and can be bypassed by other writers. Different URL spellings are distinct; collisions can serialize unrelated imports. It does not protect catalog matching from concurrent insertion or establish exactly-once receipts, source rights, complete concurrency safety or production readiness.

## 2026-11-22 — PostgreSQL-only database

**Changes:** Configured Django and psycopg for PostgreSQL exclusively, introduced environment-based connection settings, PostgreSQL-backed CI and a development Compose stack with persistent volume and readiness checks. Existing Django migrations and models remain in place. Replaced former database-specific backup tooling with PostgreSQL-native dump/restore guidance. Added PostgreSQL integration and concurrent stale-review tests.

**Limits:** Development Compose is not production deployment; no production backup retention, independent security or load review exists. Database locks protect selected rows only; concurrency is not universally proven. Hosted CI and Docker availability depend on the environment.

## 2026-11-22 — read-only catalog quality inspection

**Changes:** Added a permission-scoped debug staff page and local JSON command for bounded ID-ordered product-presentation inspection. Reports flag projection drift, stricter source URL warnings, published rows rejected by technical filters, invalid text and page-local IRC duplicates; no field values, automatic repairs or publication changes. Added synthetic permission, drift, pagination, corruption and read-only tests.

**Limits:** Duplicate checks only cover one batch, and scans are not snapshots. Passing checks is not clinical, identity, rights or publication approval; stricter URL hygiene is advisory and does not change existing public eligibility. CLI and service are outside the web gate; no production monitoring, browser, security, source or clinical validation was performed.

## 2026-11-22 — development CI

Basic GitHub Actions checks were added; the current workflow uses a PostgreSQL service. The former database-specific local snapshot utility has been retired; PostgreSQL-native backup and restore guidance supersedes it.

## 2026-11-22 — supplementary clinical reference assertions

**Changes:** Added up to ten unverified supplementary reference assertions per draft version, explicit asserted relationship labels, deduplication, separate-recorder review separation, sequential evidence-set stale checks and bounded review snapshots. Staff can inspect historical snapshot metadata and see whether its fingerprint differs from the current set; old reviews are explicitly marked without a snapshot. Added synthetic tests for role separation, caps, corruption, migration and public exclusion.

**Limits:** Claimed relationships, citations, dates, licences and reviewer qualifications are not verified; no clinical approval or publication occurs. The set fingerprint includes recorder IDs but omits timestamps, and hashes are not signatures. The limit and stale checks are not concurrency or audit guarantees; bulk ORM/SQL bypass guards. No real evidence, browser accessibility, medical, legal or production validation was performed.

## 2026-11-22 — private synthetic clinical statement drafts

**Changes:** Added a development-only clinical draft domain with separate view/add/review permissions, a Persian RTL queue, asserted citation metadata, branched parent-linked versions and independent preliminary triage snapshots. Integrated separately permissioned exact-URL source-claim hints and clinical-only login navigation. Added synthetic role, CSRF, input, version, stale and corruption tests; there is no approval or publication action.

**Limits:** Drafts, references, dates and reviewer qualifications are unverified; the text field cannot enforce one statement and is not linked to a real drug. Immediate-parent checks do not certify full ancestry. No seed clinical content, licensed evidence, clinical approval or public presentation was added. Hashes omit actor/time and are not signatures; bulk ORM/SQL bypass guards, concurrent behavior and production security remain unproven. No browser, medical, legal or production validation was performed.

## 2026-11-22 — intake row outcomes and receipt navigation

**Changes:** New receipt-backed product and price imports atomically record bounded per-data-row outcomes linking to candidates, including duplicates, content fingerprints and request-time price suggestions. Receipt details validate structure and candidate consistency, paginate rows and hide inconsistent links. Candidate pages show capped, domain-scoped recent receipt clues. Existing receipts are explicitly marked as lacking row details; no backfill is invented. Added synthetic rollback, permissions, corruption, replay, constraints and migration tests.

**Limits:** No raw file or file-level hash is kept; this cannot prove original contents, source permission or immutable audit. Hashes are not signatures and price payload hashes omit source URLs. CLI/direct imports, preview, failures and older receipts remain outside row manifests. FKs protect ordinary deletion, but bulk ORM/SQL bypass guards; retention and production concurrency/crash behavior are unresolved. No source, clinical, browser or production validation was performed.

## 2026-11-22 — web intake receipts

**Changes:** Added minimal successful-web-stage receipts for product/price CSV imports, written transactionally with candidates, plus permission-filtered Persian list/detail pages and links from uploads and queues. Stored counts distinguish created and duplicate rows; price match counts include duplicates and reflect that request's catalog. Added count constraints and synthetic rollback, permission, replay, CSRF and pagination tests.

**Limits:** Receipts are not source-rights proof, verified data, complete logs, batch manifests or immutable audit. No raw file, filename, file hash or row membership is retained; previews, failures, older imports and CLI/direct imports are absent. Replays create new receipts, without request idempotency. Model guards can be bypassed with bulk ORM/SQL, and concurrency/crash behavior and production security are unproven. No source, clinical, browser or production validation was performed.

## 2026-11-22 — offline ingestion-window inspection and input hardening

**Changes:** Added a pure offline current/next window calculator with configurable per-call IANA timezone and local HH:MM boundaries, default Tehran 23:00–01:00, a JSON management command and a permission-gated Persian debug-only staff view. Rejects ambiguous/nonexistent local boundaries and converts to UTC using timezone rules. Shared validators now reject unsafe source URL edge cases and invalid review text across product, price and source workflows. Added synthetic timezone, permission and validation tests.

**Limits:** No persisted schedule, scheduler, worker, rights check, network collection or publication. Clock and IANA data must be maintained; an open interval is not authorization or evidence of a run. Existing candidate records with newly invalid URLs fail review and require investigation, not silent rewriting. No concurrency, browser accessibility, penetration, source-rights or production testing.

## 2026-11-22 — source assertions and independent preliminary triage

**Changes:** Added a development-only internal ledger of source-rights assertions with explicit scopes, owner, evidence URL, claimed dates, recorder, duplicate detection and a separate preliminary reviewer. Added a paginated/filterable Persian staff queue and exact-URL, permission-gated, capped links from product and price candidate details. Validation and synthetic tests cover access boundaries, CSRF, sequential conflicts and integrity, date labels and no public writes.

**Limits:** Claims, evidence, dates and triage are unverified and do not authorize or gate intake, source use, crawling or publication. Source hints are not part of candidate review snapshots. Fingerprints omit actor/time and are not signatures; bulk ORM/SQL can bypass model guards; concurrency is unproven. Only synthetic local testing, not legal/source verification, browser accessibility, penetration or production testing.

## 2026-11-22 — price revision triage and safer suggestions

**Changes:** Added a staff price-queue filter for the latest preliminary review, combinable with the original match-status filter. Detail pages show up to 10 same-source/ID revisions and a conditional exact whole-Rial difference only when source name, unit/category and nonempty normalized identity fields match. Dates and original currencies remain explicit; no price or trend is approved/published. Hardened matching against invalid/normalization-empty identifiers and conservatively marks more than 100 same-IRC indexed presentations ambiguous. Malformed Unicode in stored JSON is not rendered as valid staff data. All 99 Django tests, system/migration checks, pip check and a synthetic price CSV dry run passed.

**Limits:** Comparisons are advisory and not captured/rechecked on review; normalized identity does not prove equivalence or rights, and the source URL is outside the existing price payload hash. Existing invalid rows fail current validation, but are not automatically corrected. DB work, stale indexes, concurrency, immutability and production security remain unresolved. No clinical/source verification, real data, browser/accessibility, penetration or production testing. Previous entries are historical snapshots.

## 2026-11-22 — advisory product comparisons

**Changes:** Added normalized candidate IRC index with historical backfill and controlled staging population; inconsistent indexes fail closed for preliminary review. Staff product details now show bounded source-record revision differences and normalized IRC comparison clues for other private candidates and eligible public presentations. The view explicitly excludes catalog drafts and warns about truncation, normalization uncertainty and absent IRC. No automatic match, merge or publication is performed. The full 85-test Django suite, historical migration test, local migration, system/migration checks and pip check passed.

**Limits:** Clues can be incomplete or stale, are neither identity nor rights verification, and are not snapshotted or rechecked on review. Bulk ORM/direct SQL can bypass index maintenance; production concurrency remains untested. Application row caps do not bound DB scan/sort costs. No real source data, clinical validation, browser/accessibility, penetration or production testing. Previous entries are historical snapshots.

## 2026-11-22 — private product candidate intake and triage

**Changes:** Added a separate development-only product candidate model, CSV preview/staging with explicit internal-storage attestation, submitter provenance and revision deduplication. Added Persian RTL queue, latest-review filtering, independent preliminary review and snapshot history with separate permissions. Product candidates never create or publish a catalog product. Added a fully synthetic CSV example and workflow/security tests. Local migrations, all 78 Django tests, system/migration checks and pip check passed.

**Limits:** Source rights and identity are not verified; reviews are triage only and no final approval, matching, clinical content or publication is implemented. Hashes are not signatures; bulk ORM/SQL can alter snapshots and row locking alone cannot guarantee all concurrent workflow correctness. Debug/preview, upload buffering and incomplete production controls make this suitable only for synthetic development data. No browser, penetration, concurrency or production test was performed. Previous entries are historical snapshots.

## 2026-11-22 — forward search pagination and API contract

**Changes:** Search and API now use query-bound, signed, expiring forward cursors, with a 30-result page limit and up to 150 validated candidates per request plus one lookahead. Empty pages can continue past ineligible rows. Persian UI includes continuation, clear empty and stale-cursor states. Added a bundled OpenAPI 3.0.3 document for actual public endpoints at `/api/v1/openapi.json` and automated response-shape checks. All 63 Django tests, checks, dependency checks and OpenAPI validator 0.7.2 passed; local HTTP smoke checks also passed.

**Limits:** Pagination is not snapshot-consistent; changes can skip/duplicate results or invalidate the anchor. Cursor signatures do not encrypt IDs and do not replace authorization; queries and tokens can appear in logs. the database may scan/sort more rows than the application validation limit; no public rate limiting or production load/security assessment. Source rights, clinical/price approval and real data remain absent. No browser or accessibility-device test was performed. Previous entries are historical snapshots.

## 2026-11-22 — presentation details and safer public reads

**Changes:** Added Persian RTL `/products/<id>/` and read-only `/api/v1/products/<id>/` with source, recorded review time, exact presentation fields and explicit clinical/price limitations. Search links to details; both surfaces share bounded eligibility checks, avoid invalid source URLs with embedded credentials, and omit drafts. Search inspects at most 150 candidates and returns at most 30; it cannot claim completeness. Missing, unpublished and invalid items produce the same generic 404; detail responses are noindex/no-store and excluded from the sitemap. Removed unsupported confirmation wording from the home page. Synthetic tests cover the contract and defensive cases. The full 51-test Django suite, system check, migration drift check and pip check passed; local HTTP smoke checks returned the expected search and missing-item responses.

**Limits:** Product flags and timestamps are not clinical approval or source-rights evidence; bulk database writes may bypass validation and make indexes stale. No real product data, browser/device accessibility test, security assessment or production deployment performed. Previous entries are historical snapshots.

## 2026-11-22 — development-only price staging and preliminary review

**Changes:** Added permission-gated CSV upload with preview or attested staging, authenticated submitter provenance, and a separate preliminary review permission. A different reviewer can record reasoned acceptance of a current unique match, rejection, or deferral. Records include a source snapshot and product fingerprint; sequential stale forms and inconsistent payloads fail closed. Existing/CLI candidates without a submitter cannot be reviewed here. No review publishes or approves prices. Added migrations, Persian UI and synthetic workflow tests. The full 45-test Django suite, local migration/check, migration drift check and pip check passed.

**Limits:** Source permission is only asserted; no real sources or prices were loaded. Review history is not database-immutable; direct SQL/bulk ORM bypass model guards, and the hash is not a signature. Matching can race with catalog changes without a stronger concurrency design. The staff portal remains debug-only and is not production-ready. No browser, penetration, concurrency or clinical validation was performed. Previous entries are historical snapshots.

## 2026-11-22 — development-only read-only staff queue

**Previous state:** staged price candidates were inspectable only by a local CLI; there was no session-based web access.

**Changes:** enabled Django auth and sessions; added a Persian RTL login and read-only candidate queue/detail views with scoped `pricing.view_pricecandidate` checks, status filtering, pagination and current match recalculation. Added private/no-store/noindex response headers, CSRF-protected POST logout and a hard feature gate disabling all `/staff/` endpoints outside debug mode. No accounts or passwords are seeded. Files: `daroobank/settings.py`, `daroobank/middleware.py`, `daroobank/urls.py`, `pricing/staff_views.py`, `templates/staff/`, `static/css/staff.css`, `pricing/test_staff.py` and documentation.

**Verification:** 23 existing tests passed before changes; 32 total tests passed after changes, including access control, CSRF, open redirect, escaped data, no-store, pagination and disabled-mode checks. Local Django auth/session migrations and HTTP checks were run. No external or production systems were tested. Browser/responsive accessibility tests and a penetration test were not performed.

**Limitations:** development-only; no MFA, login throttling, audited identity management, review decisions, protected approval/publishing, clinical validation or production deployment. No real source data was loaded. Debug mode and public preview URLs are unsuitable for real or sensitive data. All previous changelog entries are historical snapshots.

## 2026-11-22 — review-only price candidate staging

**Previous state:** the development application had no price ingestion or staging. It had an IRC search projection that could become inconsistent on partial model saves.

**Changes:** added an independent `pricing` Django app and migration; bounded, full-file-validated local CSV staging with explicit currency and exact Rial conversion; provenance and deduplicated candidate revisions; strict, review-only package suggestions; dry-run-by-default CLI and bounded, read-only local candidate listing. Improved and backfilled the normalized IRC index and synchronized derived search fields on partial saves. Files: `pricing/`, `catalog/models.py`, `catalog/migrations/0002_productpresentation_irc_normalized.py`, `examples/price_candidates.synthetic.csv`, settings and documentation.

**Verification:** the original 12 tests passed before changes; after changes 23 tests passed, including synthetic imports, mismatch/ambiguity, idempotency, exact conversion, rejected files and no public prices. Local migrations and a synthetic dry run were executed successfully. The example produced two unmatched records and stored none. Django system and migration checks are run separately in the final verification. No real data, source permission, clinical validation, network crawling, publication or production deployment was involved.

**Limitations:** candidates, permissions and matches are not independently verified; no authenticated admin, audit, approval, immutable database enforcement, scheduler, production data or public price/history exists. CSV storage is allowed only with appropriate rights. The initial suggestion may become stale; the listing recalculates a current suggestion but never approves it.

## 2026-11-22 — first development vertical slice

**Previous state:** repository contained architecture and research documentation only; no application, tests, database or UI existed. The prior documentation was preserved.

**Changes:**
- Added a Django 5.2 development application with migrations, `ProductPresentation`, bounded server-side Persian/Arabic/English/digit-normalized search, publication/source/date filtering, and a read-only `/api/v1/search/`. Files: `daroobank/`, `catalog/`, `manage.py`, `requirements.txt`.
- Added shared Persian RTL pages, local licensed font, responsive design tokens, honest empty/coming-soon states, no invented prices or clinical claims. Files: `templates/`, `static/`, [design system](DESIGN_SYSTEM.md).
- Added per-page metadata, home/about canonical URLs, sitemap, robots and noindex search/price pages. Website JSON-LD is descriptive, not a ranking guarantee. Files: `catalog/views.py`, `templates/base.html`.
- Added query bounding, HTML escaping, safe HTTPS source validation, GET-only views, no-store/no-referrer search responses, and a development-versus-production host/secret distinction. `ProductPresentation` does not implement reviewer approvals, audit, database-level tamper prevention or a full source-rights system; direct ORM/bulk writes can bypass model validation. Do not expose write access or treat the published flag as a governance workflow.
- Documented source usage and remaining gaps in [resource review](RESOURCE_REVIEW.md), [architecture](SYSTEM_ARCHITECTURE.md), [API](API_DESIGN.md), [security](SECURITY.md) and other existing docs.

**Verification:** `manage.py test` (12 tests), `manage.py check`, `manage.py makemigrations --check --dry-run` and local HTTP requests were run successfully. One initially incorrect test asserted that the echoed query was absent rather than inspecting results; corrected and rerun. `pip check` found no broken requirements. A 50-request single-client local empty-database development-server search smoke test measured median 8.70 ms and p95 10.52 ms; this is not representative of production or a browser performance benchmark. Django deployment checks initially found missing HSTS, HTTPS redirect and secure CSRF settings; redirect and secure cookies were added for non-debug mode, while HSTS remains deliberately unset pending a TLS/deployment policy. A browser test was attempted using temporary Playwright/Chromium, but Chromium could not start because `libnspr4.so` was unavailable; no browser, responsive-device or screen-reader test was completed. No representative load, vulnerability scanner, crawler or production tests were run. No external sites were security tested.

**Limits:** No production configuration or security sign-off; no user accounts, administration, pricing, provenance/review workflow, full relational drug model, interactions, crawler, consultation or AI. At that stage search used substring matching with a 30-result cap and no pagination, inappropriate for a large production catalog. Source records and verification flags require a future properly authorized workflow. Product identity and price publication are deliberately not automated. GET search terms can appear in server/access logs; avoid entering personal health details and implement log redaction before production.
