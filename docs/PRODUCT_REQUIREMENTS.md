# Product requirements

All requirements below are **proposed**; none are implemented. P0 means a gate for the first data-bearing public release, not permission to publish without data.

## P0: catalog and public experience

- Search Persian/English synonyms, ingredients, brands, companies, IRC, dosage form and strength. Normalize ي/ی, ك/ک, Persian/Arabic/ASCII digits, whitespace and ZWNJ variants at index/query time without changing source names. Preserve text, handle bidi isolation; test names and codes. Fuzzy results are suggestions, not identity proofs.
- Results identify entity type; package pages disambiguate strength, form, maker and size. Do not assert therapeutic equivalence. An unavailable/unknown field must not appear as verified.
- Monographs have separate patient and professional views with section-level evidence, reviewer, published/last-reviewed time and a correction path. No published clinical claim without source and review.
- Public prices show product/package, category, amount and currency, effective date if known, verification time, source and freshness. Distinguish unavailable/stale/conflicting from a verified price. Preserve history.
- Mobile-first Persian RTL, semantic HTML, keyboard accessibility, legible fonts with fallback, Persian/Jalali display, English terms isolated LTR, discoverable navigation and safety disclaimers.

## P0: operations and administration

- Authenticated authorized staff can create/review/publish/withdraw versioned records; sensitive decisions require separation of duties, reasons and immutable audit.
- Source registry records permitted operations, source health and rights. Ingestion stages raw evidence where permitted, detects duplicates/conflicts/anomalies, flags candidates, requires approval and exposes per-run counts and errors. Partial runs cannot remove or supersede verified data.
- Dashboard tracks pending reviews, price changes, stale sources, last *successful complete* run, next schedule, failures and outstanding clinical reviews. Report missing data rather than inventing totals.
- Critical admin accounts use MFA and scoped roles; backups, restore verification and incident escalation are operational release gates.

## P1 and later

Comparisons disclose differences and avoid claims of interchangeability. Safety notices require sourced editorial review. Product image rights must be established; barcode lookup identifies product rather than validating authenticity. Price/insurance comparison requires source-defined category, plan, effective period and eligibility. Availability/shortages require an authorized, time-stamped source and cannot imply a particular pharmacy has stock without verification.

Interaction checker, dosing calculators, renal/pregnancy support and pill identification remain disabled until clinical validation, appropriate licensing, scope and coverage are reviewed. A verified negative interaction result is distinct from not assessed, incomplete coverage and service failure. Reminders/medication lists require consent and privacy design. Professional dashboard, company correction requests and institutional APIs are later, subject to role review and licensing.

## Future consultation

Separate verified professional enrollment, scheduling, messages and calls from catalog data. Default feature flag off; explicit consent, privacy/security review, verified credentials, local regulatory assessment, emergency escalation and an incident process are prerequisites. Audio/video is not recorded by default. AI is optional retrieval over approved sources with citations and uncertainty, never diagnosis, prescription or unsupervised publishing.

## Acceptance examples

1. Two packages differing only in count never share a price solely by name.
2. A source outage preserves the last approved observation, clearly dated and marked stale if policy says so.
3. A reviewer can identify source, version and decision for each published clinical claim.
4. An unassessed interaction produces “not assessed”, not “safe”.
5. Search equivalent Persian/Arabic letter and digit forms returns the same approved concept without changing original display strings.

## Navigation and SEO acceptance

Planned public navigation: home, drug database, price finder, manufacturers, products, interactions, comparison, knowledge/articles, safety alerts, consultation, professionals, about and support. Interaction and consultation routes must clearly say unavailable/coming soon until their gates are met; no placeholder should imply a live service. Navigation must remain usable without JavaScript and on small screens.

Create stable, human-readable, unique URLs for reviewed monographs and sufficiently informative package pages. SSR should emit Persian titles, descriptions, canonical links, correct language and breadcrumbs; sitemap only approved indexable pages. Noindex administrative, draft, empty, duplicate, filtered and unhelpful search pages; constrain crawlable pagination and link to meaningful parent/child pages. Provide accurate organization/article/breadcrumb structured data only where applicable and currently supported, with no invented ratings, product availability or clinical claims. Avoid thousands of thin automatic pages. Verify rendering, metadata and index rules in real search-engine tests and maintain an editorial correction channel.
