# Implementation changelog

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
