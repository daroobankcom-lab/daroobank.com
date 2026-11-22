# Current gap and improvement matrix

Audit baseline was `045637b`: documentation only, with no existing application, tests or production deployment. Current scope is the first development slice, not a completed platform.

| Priority | Area | Current implementation / files | Remaining gap |
|---|---|---|---|
| P0 | Data safety | `catalog/models.py`, `catalog/services.py`: source-backed presentation records; no clinical or price claims | Full generic/ingredient/product/package model, provenance, rights, separate approval and audit remain missing; publication flag alone is not verification. |
| P0 | Security | `daroobank/settings.py`, `pricing/staff_views.py`: development-only staff authentication and view permission, CSRF, private responses; portal disabled outside debug | No MFA, login throttling, audit, CSP, security monitoring, production hardening or assessment. |
| P0 | Clinical and prices | `templates/prices.html` transparently unavailable; `pricing/` stages candidate assertions only | Preliminary independent review exists, but no licensed sources, clinical content, references, approved price history or approval/publishing workflow. |
| P0 | Ingestion | `pricing/` offers local review-only CSV staging and reinspection | No source permissions, network adapters, schedule, source monitoring or recovery. |
| P1 | UX / RTL | `templates/`, shared CSS and development-only staff staging and preliminary-review portal, local font, normalization | Browser, screen-reader, keyboard and mobile device validation pending; no full admin or clinical drug-monograph pages; presentation detail is a limited package-like view. |
| P1 | SEO | `catalog/views.py`, `templates/base.html`: canonicals, robots, sitemap, noindex, basic schema | Search-engine rendering, validation, performance and content credibility cannot be established without real reviewed content and deployment. GEO effects unmeasured. |
| P1 | API/search | `catalog/services.py`, `/api/v1/search/` | SQLite `contains`, 150-candidate scan and 30-result cap are development only; no pagination, OpenAPI, full coverage or scalable Persian search index. |
| P2 | AI, consultation | `docs/SYSTEM_ARCHITECTURE.md` | No retrieval, professional verification, appointments, chat/audio/video or consent features. |
