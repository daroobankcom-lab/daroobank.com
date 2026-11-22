# Proposed database schema and invariants

Current implementation: `catalog.ProductPresentation` and its SQLite development migration use Django integer IDs; this is a provisional narrow search record, not the complete schema below. `catalog.ProductCandidate` stores private product assertions, normalized IRC lookup and preliminary review events; current IRC/revision comparisons are bounded advisory reads, not identity reconciliation; `pricing.PriceCandidate` stores local price assertions and an optional suggested product. Neither provides publication or tamper-proof audit; no verified/public price, approval or monograph model exists. Proposed target IDs are internal opaque UUIDs; external identifiers are strings to preserve leading zeros. UTC timestamps use `timestamptz`, source local dates preserve their original value/calendar, and source records retain provenance. Table names below are logical, not executed SQL.

## Catalog

- `ingredient(id, inn, names)`; `generic_drug(id, canonical_name, status)`; `generic_ingredient(generic_id, ingredient_id, strength_numerator, numerator_unit, strength_denominator, denominator_unit)` supports combinations. A generic clinical formulation may reference a controlled `dosage_form` and route; do not collapse an ingredient into a formulation.
- `brand(id, name)`, `organization(id, names)`, `product(id, generic_id, brand_id, form_id, route, status)`; `product_ingredient` records explicit strengths when different formulations require it. `product_organization(product_id, organization_id, role, valid_from, valid_to, source_id)` distinguishes manufacturer, authorization holder and distributor.
- `package(id, product_id, quantity, unit, description, status)` denotes a commercial presentation. `identifier(id, scheme, value, scope_type, scope_id, source_id, valid_from, valid_to, verification)` links IRC/GTIN/other codes to the entity scope actually supported by evidence. Prefer typed foreign keys or a constrained association rather than unchecked polymorphic IDs. A source-specific identifier's uniqueness/scope must be verified before imposing a global unique constraint. Conflicting identifiers go to review, never silently merge.
- `name_variant(entity, language, original, normalized, kind, source)` permits synonyms and search indexes while retaining source spelling. Images have provenance/licence and package linkage.

## Clinical

`monograph(generic_id, audience)` → `content_version(status, author, reviewer, approved_at, effective_at, next_review_at, supersedes)` → `section_version(section_key, ordinal, text)` → `statement` → `statement_reference`. `reference(title, authors, publication, date, DOI, PMID, URL, type, evidence_level, accessed_at, source_version)`; references are independently reusable, while a specific claim is traceable to its source and precise relevant location. Clinical versions are immutable after publication; correction, withdrawal and review are new decisions/versions. Extensible section keys avoid schema changes; validated schema and editorial rules still apply.

## Price and insurance

`price_observation(package_id, source_id, source_record_id, source_amount, source_currency, canonical_rial, category, unit, effective_at, published_at, collected_at, verified_at, verification_status, source_revision)`; `price_decision(observation_id, status, reviewer, reason, decided_at)` and append-only `price_publication(package_id, category, unit, observation_id, effective_at, decision_id, published_at, supersedes)` form the audit/history. Multiple observations may disagree; approval is an explicit decision, not most-recent scrape. `insurance_plan` and `coverage_record` are independent, with eligibility, coverage type and validity, not a generic price field. See [price rules](PRICE_DATA_MODEL.md).

## Ingestion and audit

`source` (ownership, permission scope/expiry, allowed rates), `crawl_run` (window, status/counts/coverage), `raw_record` (source ID, source revision, payload hash, restricted object reference where allowed), `candidate`, `match_decision`, `validation_result`, `checkpoint`, `audit_event`. Stable source identifiers + revision or content hash support idempotency. Persist failures, approvals and reasons; restrict sensitive raw data and avoid PHI in logs.

## Identity and future consultation

`user`, `role`, `permission`, `user_role`, `professional_profile` with credential verification records; later `appointment`, `consultation_session`, `consent`, encrypted message/file metadata and access audit live in a separately governed domain. Do not populate or expose without legal/security review. A user may have multiple roles; status/ownership and object-level checks are mandatory.

## Indexes and constraints

- B-tree unique per authorized source identity/revision (where source guarantees it); index `(scheme, value)` plus scope and status for identifier lookups; conflicts go to review. Use constrained nonnegative numeric values and known currency/category/unit.
- Search normalized names using B-tree for exact/prefix and measured `pg_trgm` GIN for similarity; maintain a search projection for published content. Test normalized Arabic/Persian and half-space variants; avoid indexing raw PHI.
- Index price history `(package_id, category, unit, effective_at DESC, published_at DESC)`, source record/run, pending review state and content audience/status. Add FKs, constrained status transitions and transactional publication; do not derive identity from fuzzy similarity. Use query plans and realistic data before adding indexes.
- Effective date, collection time, verification time and publication time mean different things; never fill an unknown effective date with collection time. Soft withdrawal/history rather than destructive update, with retention exceptions documented and legally approved.


## Implemented development-only source assertions

The current Django models `SourceClaim` and `SourceClaimReview` are a limited local ledger, separate from the planned ingestion/audit schema above. A claim holds an exact source URL, asserted owner, evidence URL/note, claimed collection/storage/republication scopes, optional dates, fingerprint and recorder/time; a review holds a separate reviewer, non-approval decision, reason and assertion snapshot. Ordinary model saves/deletes are guarded but bulk operations and SQL bypass these guards; hashes are not signatures and omit recorder/time. They do not implement the planned `source` authorization, revocation, crawler or audit entities and are not a production compliance record.


## Implemented development-only web intake summaries

`ImportReceipt` records a successful web CSV staging operation's domain, asserted source, actor/time and counts; price summaries include match categories for all input rows. Basic count and domain consistency have database constraints, and a single transaction wraps candidate and receipt writes. New `ImportReceiptItem` records logical row ordinal, source ID, candidate hash/reference, created/duplicate flag and optional price suggestion; old receipts are not backfilled. There is no raw file, filename, file-level hash, failure record or CLI/history backfill. Protected FKs prevent ordinary deletion of referenced candidates/receipts; retention and repair policy remain unresolved. Ordinary model guards are not database immutability. This is not the planned `crawl_run`, `checkpoint` or durable audit schema.


## Implemented development-only clinical drafts

`ClinicalDraft` holds a free-text synthetic subject, audience, title, statement, one asserted citation with optional dates, author/time, payload hash and optional immediate parent/hash/change reason. `ClinicalDraftReview` records a separate reviewer, preliminary non-approval decision, reason and snapshot. These are not the planned approved content versions, statement/reference graph or publication/withdrawal records described above. Model-level mutation guards and fingerprints are not database immutability or signatures; actor/time are not hashed and full ancestry is not verified.
