# Current gap and improvement matrix

Audit baseline was `045637b`: documentation only, with no existing application, tests or production deployment. Current scope is the first development slice, not a completed platform.

| Priority | Area | Current implementation / files | Remaining gap |
|---|---|---|---|
| P0 | Data safety | `catalog/models.py`, `catalog/services.py`: source-backed presentation records; no clinical or price claims | Full generic/ingredient/product/package model, provenance, rights, separate approval and audit remain missing; publication flag alone is not verification. |
| P0 | Security | `daroobank/settings.py`, `catalog/tests.py`: dev secret/hosts, escaping, GET-only views, input bounds | No authentication, MFA, rate limiting, CSP, security monitoring, production hardening or assessment. |
| P0 | Clinical and prices | `templates/prices.html` transparently unavailable | No sources, clinical content, references, price observations/history, calculations or review workflow. |
| P0 | Ingestion | `docs/CRAWLER_ARCHITECTURE.md` proposal only | No permissions, source adapters, schedule, data import, monitoring or recovery. |
| P1 | UX / RTL | `templates/`, `static/css/site.css`, local font, normalization | Browser, screen-reader, keyboard and mobile device validation pending; no tables/admin or individual drug/product pages. |
| P1 | SEO | `catalog/views.py`, `templates/base.html`: canonicals, robots, sitemap, noindex, basic schema | Search-engine rendering, validation, performance and content credibility cannot be established without real reviewed content and deployment. GEO effects unmeasured. |
| P1 | API/search | `catalog/services.py`, `/api/v1/search/` | SQLite `contains` and 30-result cap are development only; no pagination, OpenAPI, full coverage or scalable Persian search index. |
| P2 | AI, consultation | `docs/SYSTEM_ARCHITECTURE.md` | No retrieval, professional verification, appointments, chat/audio/video or consent features. |
