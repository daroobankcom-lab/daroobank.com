# Implementation changelog

Entries describe the state at each change; later entries can supersede earlier limitations.

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
