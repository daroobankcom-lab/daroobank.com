# Roadmap and release gates

The local RTL web and product-search slice has started Phase 1. Local CSV candidate staging and a synthetic private clinical drafting slice support later pricing and knowledge work, but Phase 2, Phase 3 and the remaining phases are not complete. Work is iterative; no production deployment without explicit authorization.

| Phase | Deliverables and exit gates | Dependencies / risk |
|---|---|---|
| 0 Audit and research | Repository audit, benchmark and source access log; facts separated from gaps. This documentation records initial research, not completed legal/source discovery. | Iranian sites inaccessible in this environment; permission and technical discovery outstanding. |
| 1 Foundation | Agree ADRs, create tested modular Django skeleton and local dev stack, DB migrations, versioned OpenAPI, auth/admin baseline, CI and backups. No clinical/price claims. | Staffing, security setup and approved hosting policy. |
| 2 Knowledge | Catalog, separate generic/product/package, referenced versioned monographs, reviewer workflow, Persian search and SSR pages; release only reviewed original content. | Clinical team, source licences and accessible UX. |
| 3 Pricing | Package-level observations, approved histories, pricing admin and manually authorized imports; verify currency/units and timestamps. | Source data contracts, source meanings, identity verification and pricing reviewers. |
| 4 Ingestion | Source discovery and permitted adapters, independent scheduler, staged runs, operational dashboard and safe approval workflow; initial manual review. | Written authorization, source samples and rate policy, safe failure tests. Automatic public updates remain off until validated. |
| 5 Tools | Comparison and sourced safety alerts first; interactions/calculators/AI only with licensed coverage, safety review and independent validation. | Clinical governance, evidence licences, meaningful test data. |
| 6 Consultation | Separate domain, verified professionals, consent, privacy/security and legal review; gradual messaging/scheduling/call rollout under flags. | Qualified Iranian counsel, professional verification and incident operations; no default recordings. |
| 7 Expansion | Mobile, institutional scoped APIs, integrations and analytics as justified by usage. | Data rights, SLAs, privacy and measured scale. |

## Resource estimate and decisions

Indicative engineering effort: foundation 4–8 engineer-weeks, catalog/editorial 12–24, pricing 8–16, ingestion 10–20 after access. These are broad estimates, not schedules, and exclude clinical content production, legal/licensing, UX, operations, QA and external waiting. A multidisciplinary team and a few reviewed pilot drugs should validate workflows before catalog expansion. Consultation/AI are not included and require separate sizing. Obtain decisions on clinical governance, source agreements, operating budget, hosting/privacy policy and production authorization at their respective gates.
