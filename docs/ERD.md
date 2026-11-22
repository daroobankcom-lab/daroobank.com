# Proposed entity relationships

Illustrative conceptual ERD, not an implemented schema. Junctions represent many-to-many, not copies of entities. See [schema](DATABASE_SCHEMA.md) for optional fields and constraints.

```mermaid
erDiagram
  INGREDIENT ||--o{ GENERIC_INGREDIENT : contains
  GENERIC_DRUG ||--|{ GENERIC_INGREDIENT : composition
  GENERIC_DRUG ||--o{ PRODUCT : formulated_as
  BRAND o|--o{ PRODUCT : labels
  PRODUCT ||--o{ PACKAGE : presented_as
  PRODUCT ||--o{ PRODUCT_ORGANIZATION : has
  ORGANIZATION ||--o{ PRODUCT_ORGANIZATION : participates
  DOSAGE_FORM ||--o{ PRODUCT : describes
  PACKAGE ||--o{ PRICE_OBSERVATION : observed_for
  SOURCE ||--o{ PRICE_OBSERVATION : supplies
  PRICE_OBSERVATION ||--o{ PRICE_DECISION : reviewed_by
  PRICE_OBSERVATION ||--o{ PRICE_PUBLICATION : published_as
  GENERIC_DRUG ||--o{ MONOGRAPH : describes
  MONOGRAPH ||--o{ CONTENT_VERSION : versioned
  CONTENT_VERSION ||--o{ SECTION_VERSION : contains
  SECTION_VERSION ||--o{ STATEMENT : contains
  STATEMENT ||--o{ STATEMENT_REFERENCE : supported_by
  REFERENCE ||--o{ STATEMENT_REFERENCE : cites
  SOURCE ||--o{ CRAWL_RUN : executed
  CRAWL_RUN ||--o{ RAW_RECORD : collects
  RAW_RECORD ||--o{ CANDIDATE : proposes
  CANDIDATE ||--o{ MATCH_DECISION : reviewed
  USER ||--o{ MATCH_DECISION : makes
  USER ||--o{ USER_ROLE : assigned
  ROLE ||--o{ USER_ROLE : grants
  USER ||--o| PROFESSIONAL_PROFILE : may_have
  USER ||--o{ APPOINTMENT : books
  APPOINTMENT o|--o| CONSULTATION_SESSION : may_create
  INSURANCE_PLAN ||--o{ COVERAGE_RECORD : provides
  PACKAGE ||--o{ COVERAGE_RECORD : covered_by
```

Identifiers can refer to different evidence-supported scopes; a package may have several identifiers and the same scheme may have conflicting source assertions. `professional_profile` is at most one per user here; professional verification records may be many. Consultations and insurance are future concepts, not active services.
