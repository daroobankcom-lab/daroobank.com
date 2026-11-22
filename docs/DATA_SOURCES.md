# Data sources, discovery and permissions

Research performed 22 November 2026. Evidence below is not authorization for automated collection or commercial republication. Source rights, terms, robots, rate limits and current accessibility must be rechecked with the owner before ingestion. No credentials or data partnerships are in place.

| Source | Observed/reported capability | Access findings and restrictions | Proposed use |
|---|---|---|---|
| [Iran FDA NFI](https://irc.fda.gov.ir/nfi) | An FDA [systems directory](https://www.fda.gov.ir/fa/ارشیو-مخفی-معاونت-توسعه/اداره-امار-و-فناوری-اطلاعات/سامانه-ها), accessible to search indexing but not directly fetched, lists NFI; a historical [FDA notice](https://www.fda.gov.ir/fa/جزییات-خبر?id=12347) describes a searchable list and approved prices. | Direct fetch and `/robots.txt` returned tool HTTP 500 errors; origin status is unconfirmed. Pagination, API, fields, auth, terms, reuse and current operation unknown. | Seek an official approved feed/export and written publication/retention rights; no connector until verified. |
| [TTAC](https://ttac.ir/) | Same indexed directory identifies TTAC systems; historical FDA notice describes TTAC drug information. | Direct homepage and robots fetch returned tool HTTP 500 errors. APIs, availability/shortage claims, terms and permissions unverified. | Seek official information and authorization; do not imply stock or rely on third-party claims. |
| [Payam Daroosaz](https://payamdaroosaz.com/) | Direct homepage requests Persian/English name or code and advertises price update files; [vendor page](https://payamdaroosaz.com/payam-landing/) describes price and insurance updates. | Private benchmark, not a regulator; results/download contents, API, licence, reuse and gated functions not checked. | Competitive product research; commercial data only under explicit rights and source verification. |
| [Medscape](https://reference.medscape.com/public/about) | Public description covers professional monographs, interaction checker and licensed third-party data. | Proprietary content; no reuse licence obtained. | Functional benchmark only, no copying. |
| [DailyMed](https://dailymed.nlm.nih.gov/dailymed/about-dailymed.cfm) | NLM describes submitted in-use US labels and warns they may not match FDA-approved labels, are not reviewed by NLM before publication and coverage is incomplete. | US-specific, not Iranian regulatory status. Check terms per data/media before reuse. | Potential evidence input under clinical review, never automatic local approval. |
| [RxNorm](https://www.nlm.nih.gov/research/umls/rxnorm/overview.html) | NLM describes normalized US drug concepts and relationships. | Some source vocabularies have additional licensing; US scope excludes many product categories. | Optional terminology mapping, not an Iranian price/product registry. |
| [NHS Medicines A–Z](https://www.nhs.uk/medicines/) | Public patient-oriented medicine index. | UK context and content rights need independent assessment. | UX and editorial benchmark, not copied clinical content. |

## Acquisition checklist

1. Record owner, contact, official status evidence, specific licence/permission, allowed uses/fields, attribution, redistribution, geography, duration and renewal.
2. Verify API/exports, robots, terms, authentication, permitted collection frequency and limits; retain date and evidence of approval. Rights can be revoked, so expiry disables new collection/publishing pending review.
3. Obtain representative authorized samples and record identifier semantics, unit/currency and effective date definitions; resolve ambiguous IRC scope and packaging.
4. Assess accuracy, completeness, latency, update cadence, historical coverage, conflict resolution and access constraints. Never assume registration implies availability.
5. Perform legal and clinical review; test adapter with sanitized permitted fixtures; enable manual approval first. Keep source ownership and permissions distinct from source claim accuracy.
