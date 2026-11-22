# Implementation changelog

## 2026-11-22 — advisory product comparisons

**Changes:** Added normalized candidate IRC index with historical backfill and controlled staging population; inconsistent indexes fail closed for preliminary review. Staff product details now show bounded source-record revision differences and normalized IRC comparison clues for other private candidates and eligible public presentations. The view explicitly excludes catalog drafts and warns about truncation, normalization uncertainty and absent IRC. No automatic match, merge or publication is performed. The full 85-test Django suite, historical migration test, local migration, system/migration checks and pip check passed.

**Limits:** Clues can be incomplete or stale, are neither identity nor rights verification, and are not snapshotted or rechecked on review. Bulk ORM/direct SQL can bypass index maintenance; SQLite concurrency and the real production DB remain untested. Application row caps do not bound DB scan/sort costs. No real source data, clinical validation, browser/accessibility, penetration or production testing. Previous entries are historical snapshots.

## 2026-11-22 — private product candidate intake and triage

**Changes:** Added a separate development-only product candidate model, CSV preview/staging with explicit internal-storage attestation, submitter provenance and revision deduplication. Added Persian RTL queue, latest-review filtering, independent preliminary review and snapshot history with separate permissions. Product candidates never create or publish a catalog product. Added a fully synthetic CSV example and workflow/security tests. Local migrations, all 78 Django tests, system/migration checks and pip check passed.

**Limits:** Source rights and identity are not verified; reviews are triage only and no final approval, matching, clinical content or publication is implemented. Hashes are not signatures; bulk ORM/SQL can alter snapshots and SQLite cannot guarantee concurrent review serialization via `select_for_update`. Debug/preview, upload buffering and incomplete production controls make this suitable only for synthetic development data. No browser, penetration, concurrency or production test was performed. Previous entries are historical snapshots.

## 2026-11-22 — forward search pagination and API contract

**Changes:** Search and API now use query-bound, signed, expiring forward cursors, with a 30-result page limit and up to 150 validated candidates per request plus one lookahead. Empty pages can continue past ineligible rows. Persian UI includes continuation, clear empty and stale-cursor states. Added a bundled OpenAPI 3.0.3 document for actual public endpoints at `/api/v1/openapi.json` and automated response-shape checks. All 63 Django tests, checks, dependency checks and OpenAPI validator 0.7.2 passed; local HTTP smoke checks also passed.

**Limits:** Pagination is not snapshot-consistent; changes can skip/duplicate results or invalidate the anchor. Cursor signatures do not encrypt IDs and do not replace authorization; queries and tokens can appear in logs. SQLite may scan/sort more rows than the application validation limit; no public rate limiting or production load/security assessment. Source rights, clinical/price approval and real data remain absent. No browser or accessibility-device test was performed. Previous entries are historical snapshots.

## 2026-11-22 — presentation details and safer public reads

**Changes:** Added Persian RTL `/products/<id>/` and read-only `/api/v1/products/<id>/` with source, recorded review time, exact presentation fields and explicit clinical/price limitations. Search links to details; both surfaces share bounded eligibility checks, avoid invalid source URLs with embedded credentials, and omit drafts. Search inspects at most 150 candidates and returns at most 30; it cannot claim completeness. Missing, unpublished and invalid items produce the same generic 404; detail responses are noindex/no-store and excluded from the sitemap. Removed unsupported confirmation wording from the home page. Synthetic tests cover the contract and defensive cases. The full 51-test Django suite, system check, migration drift check and pip check passed; local HTTP smoke checks returned the expected search and missing-item responses.

**Limits:** Product flags and timestamps are not clinical approval or source-rights evidence; bulk database writes may bypass validation and make indexes stale. No real product data, browser/device accessibility test, security assessment or production deployment performed. Previous entries are historical snapshots.

## 2026-11-22 — development-only price staging and preliminary review

**Changes:** Added permission-gated CSV upload with preview or attested staging, authenticated submitter provenance, and a separate preliminary review permission. A different reviewer can record reasoned acceptance of a current unique match, rejection, or deferral. Records include a source snapshot and product fingerprint; sequential stale forms and inconsistent payloads fail closed. Existing/CLI candidates without a submitter cannot be reviewed here. No review publishes or approves prices. Added migrations, Persian UI and synthetic workflow tests. The full 45-test Django suite, local migration/check, migration drift check and pip check passed.

**Limits:** Source permission is only asserted; no real sources or prices were loaded. Review history is not database-immutable; direct SQL/bulk ORM bypass model guards, and the hash is not a signature. SQLite does not support effective row-level `select_for_update`; matching can race with catalog changes on any DB without a stronger concurrency design. The staff portal remains debug-only and is not production-ready. No browser, penetration, concurrency or clinical validation was performed. Previous entries are historical snapshots.

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
- Added a Django 5.2 development application with SQLite migrations, `ProductPresentation`, bounded server-side Persian/Arabic/English/digit-normalized search, publication/source/date filtering, and a read-only `/api/v1/search/`. Files: `daroobank/`, `catalog/`, `manage.py`, `requirements.txt`.
- Added shared Persian RTL pages, local licensed font, responsive design tokens, honest empty/coming-soon states, no invented prices or clinical claims. Files: `templates/`, `static/`, [design system](DESIGN_SYSTEM.md).
- Added per-page metadata, home/about canonical URLs, sitemap, robots and noindex search/price pages. Website JSON-LD is descriptive, not a ranking guarantee. Files: `catalog/views.py`, `templates/base.html`.
- Added query bounding, HTML escaping, safe HTTPS source validation, GET-only views, no-store/no-referrer search responses, and a development-versus-production host/secret distinction. `ProductPresentation` does not implement reviewer approvals, audit, database-level tamper prevention or a full source-rights system; direct ORM/bulk writes can bypass model validation. Do not expose write access or treat the published flag as a governance workflow.
- Documented source usage and remaining gaps in [resource review](RESOURCE_REVIEW.md), [architecture](SYSTEM_ARCHITECTURE.md), [API](API_DESIGN.md), [security](SECURITY.md) and other existing docs.

**Verification:** `manage.py test` (12 tests), `manage.py check`, `manage.py makemigrations --check --dry-run` and local HTTP requests were run successfully. One initially incorrect test asserted that the echoed query was absent rather than inspecting results; corrected and rerun. `pip check` found no broken requirements. A 50-request single-client local empty-SQLite development-server search smoke test measured median 8.70 ms and p95 10.52 ms; this is not representative of production or a browser performance benchmark. Django deployment checks initially found missing HSTS, HTTPS redirect and secure CSRF settings; redirect and secure cookies were added for non-debug mode, while HSTS remains deliberately unset pending a TLS/deployment policy. A browser test was attempted using temporary Playwright/Chromium, but Chromium could not start because `libnspr4.so` was unavailable; no browser, responsive-device or screen-reader test was completed. No representative load, vulnerability scanner, crawler or production tests were run. No external sites were security tested.

**Limits:** No production configuration or security sign-off; no user accounts, administration, pricing, provenance/review workflow, full relational drug model, interactions, crawler, consultation or AI. Search currently uses SQLite substring matching with a 30-result cap and no pagination, inappropriate for a large production catalog. Source records and verification flags require a future properly authorized workflow. Product identity and price publication are deliberately not automated. GET search terms can appear in server/access logs; avoid entering personal health details and implement log redaction before production.
