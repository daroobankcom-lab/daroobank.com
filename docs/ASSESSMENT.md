# Initial product and technical assessment

Status: planning, 22 November 2026. Direct observations, reported claims and recommendations are distinguished below. No production implementation is implied.

## 1. Repository audit

At base commit `538ed9624e14ba36365b75741ba2ec1a31071d81`, the only tracked file was a one-line README; the complete tracked tree and commit history were inspected. There was no source code, package manifest, schema, deployment, tests, integration or existing functionality. Local branches were `main` and the active Arena feature branch; `origin/main` was the visible remote branch. This does not establish the absence of external infrastructure or unadvertised remote branches. Node 22 and Python 3.11 are available in the inspection environment; Docker was not found. No production environment was inspected.

## 2. Vision and differentiation

Four linked but independently governed pillars: evidence-backed Persian patient and professional education; Iranian commercial presentation and price intelligence; independently operated, auditable ingestion; and later privacy-preserving professional consultation. Differentiate by linking an editorially reviewed generic monograph to *specific* locally identified packages and a sourced, dated price timeline, never asserting interchangeability or pharmacy availability from similar names. Clearly label sponsorship and separate it from clinical editorial decisions.

## 3. Benchmarks and other ideas

- **Medscape**: its [About page](https://reference.medscape.com/public/about) describes clinician monographs, drug/condition/procedure references, interaction checking, regular professional updates and licensed First DataBank inputs. Useful models for structured navigation, references and review, not sources to copy. Its counts are vendor claims; dataset completeness, licence and all interactive workflows were not verified.
- **Payam Daroosaz**: its [public homepage](https://payamdaroosaz.com/) requests a Persian/English drug name or code and displays price-update download headings. Its [software page](https://payamdaroosaz.com/payam-landing/) advertises product search and price/insurance updates, barcode and pharmacy workflows. These are vendor claims, not verified API availability, accuracy or republication rights. Search results, downloads, login-only features and insurance workflows were not exercised. It is a private benchmark, not an official regulator.
- **NHS** [Medicines A–Z](https://www.nhs.uk/medicines/) suggests patient-oriented, accessible navigation; **DailyMed** provides label context with material limitations ([NLM](https://dailymed.nlm.nih.gov/dailymed/about-dailymed.cfm)); **RxNorm** illustrates normalized terminology and ingredient/form/strength identity ([NLM](https://www.nlm.nih.gov/research/umls/rxnorm/overview.html)). These are not Iranian registration or price sources. Adapt concepts, not copyrighted text or US market assumptions.

## 4. Iranian sources and evidence limits

A search-indexed [Iran FDA systems listing](https://www.fda.gov.ir/fa/ارشیو-مخفی-معاونت-توسعه/اداره-امار-و-فناوری-اطلاعات/سامانه-ها) identifies `irc.fda.gov.ir/nfi` as the national drug information system and `ttac.ir` among official systems; a historical [FDA notice](https://www.fda.gov.ir/fa/جزییات-خبر?id=12347) describes searching products and approved prices and TTAC drug information. These are historical descriptions, not proof of present operations or reuse permission. Direct fetch attempts for NFI, TTAC and their robots.txt returned tool errors reported as HTTP 500; this may be an intermediary/environment failure rather than the remote site's own response. The FDA systems page also could not be directly fetched; its search-indexed excerpt was used. No source pagination, APIs, network requests, current fields, terms, actual robots rules, authentication or rate limits were verified. No access controls were bypassed. Obtain a documented approved feed/licence or permission before collection and republication; otherwise use authorized manual imports. See [data source registry](DATA_SOURCES.md).

## 5. Recommended stack and alternatives

Propose a modular monolith in Python/Django + Django REST Framework, PostgreSQL, server-rendered Django templates with limited progressive enhancement, Redis only for background jobs/cache once needed, and separate Celery workers/beat for permitted ingestion. This leverages built-in admin and relational transactions while retaining versioned HTTP interfaces for independently developed clients and services. TypeScript/NestJS and ASP.NET Core are credible backend alternatives; Next.js and server-rendered ASP.NET are credible frontend alternatives. Trade-offs and adoption triggers are in [technology decisions](TECH_STACK_DECISIONS.md). These are proposals, not installed components or proven benchmark results.

## 6. Architecture and data

Maintain domain modules for catalog, clinical content/evidence, pricing, ingestion, identity/audit and a disabled consultation boundary. Public read APIs return only approved versions. Keep source-specific code in worker adapters, not request handlers. Model ingredient, generic formulation, branded product and package separately; references attach to individual clinical statements/versions. Append price observations and publication decisions, not mutable single prices. See [architecture](SYSTEM_ARCHITECTURE.md), [schema](DATABASE_SCHEMA.md), [ERD](ERD.md), [API](API_DESIGN.md) and [price model](PRICE_DATA_MODEL.md).

## 7. Ingestion and prices

An independent worker runs a configurable, bounded 23:00–01:00 Asia/Tehran window; collection rights, operational access, reliable identifiers and fixtures are prerequisites. Staging, idempotent source snapshots, exact identifier and presentation checks, exception queues, human approval and atomic publication protect current verified data. Missing from a failed/partial run is not discontinuation. Prices need an explicit source currency, category, package/unit, effective date when known and history. [Crawler](CRAWLER_ARCHITECTURE.md) and [pricing](PRICE_DATA_MODEL.md) detail stop conditions.

## 8. Clinical and consultation safety

Original sourced text is independently reviewed and approved; publish dates and review status, link statement-level references, correct/withdraw through version history. The interaction tool remains disabled until licensed structured evidence and clinical validation exist; unknown is not no interaction. Consultation is a future isolated domain behind a disabled flag, with verified professionals, consent, audit and legal approval; no audio/video recording by default. AI cannot autonomously publish, prescribe or substitute for a clinician. See [clinical standards](CLINICAL_CONTENT_STANDARDS.md) and [security](SECURITY.md).

## 9. Frontend, SEO and performance

Persian-first RTL server-rendered HTML with semantic headings, accessible controls, mixed-direction isolation and low-JS search; canonical, sitemap and index rules apply only to unique reviewed pages. Jalali dates and Rial/Toman formatting are presentation concerns; raw amounts and dates remain unambiguous. Define budgets and measure on representative network, data and hardware; no performance has yet been measured. See [testing](TESTING_STRATEGY.md).

## 10. Directory and documentation plan

Proposed—not yet present—`server/` (Django project and domain apps), `templates/`, `static/`, `tests/`, `infra/`, `docs/`, and separate worker entrypoints. Keep dependencies within the modular monolith and use documented APIs for outside clients; exact layout is in [development guide](DEVELOPMENT_GUIDE.md). The README indexes the documentation set and ADRs.

## 11. Roadmap, complexity and dependencies

A safe MVP is **high complexity**: product identity, authorized data, clinical authorship/review and operational controls dominate UI implementation. Indicative engineering estimates (not commitments): foundation 4–8 engineer-weeks; catalog/editorial 12–24; pricing 8–16; authorized ingestion 10–20 after source access. Clinical review, licensing, Iranian legal advice, QA and operations are additional; duration depends heavily on source quality and staffing. Consultation and AI are separate major programs. [Roadmap](ROADMAP.md) provides gates and dependencies.

## 12. Principal risks and open decisions

1. No demonstrated rights or technical access to Iranian data; no legal basis for claiming current prices.
2. Incorrect match or currency/unit can harm users; require explicit identifiers, checks and review.
3. Unreviewed content, missing interaction coverage and stale evidence are clinical safety risks.
4. Professional verification, privacy, retention, hosting and telehealth regulation require qualified Iranian legal and professional review; do not assume compliance.
5. Search quality, scale, traffic, budget, licensing and infrastructure location are unmeasured. Business owners must authorize source agreements, hosting/legal policy, clinical governance and production deployment. None is presumed approved.
