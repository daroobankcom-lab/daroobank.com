# Architecture decision records

- [0001: initial modular monolith and technology selection](0001-initial-stack.md) — proposed, 22 November 2026.
- [0002: offline ingestion-window inspection](0002-offline-ingestion-window.md) — development-only implementation, 22 November 2026.
- [0003: development-only web intake receipts](0003-web-intake-receipts.md) — partially superseded by 0004, 22 November 2026.
- [0004: development intake row-outcome manifest](0004-intake-row-manifest.md) — development-only implementation, 22 November 2026.

- [0005: private clinical statement drafts](0005-clinical-draft-triage.md) — development-only implementation, 22 November 2026.

- [0006: bounded clinical reference assertions](0006-clinical-evidence-assertions.md) — development-only implementation, 22 November 2026.

- [0007: development database backups](0007-backup-policy.md) — superseded by 0009, 22 November 2026.

- [0008: bounded catalog quality inspection](0008-catalog-quality-inspection.md) — development-only implementation, 22 November 2026.

- [0009: PostgreSQL-only database](0009-postgresql-only.md) — development implementation, 22 November 2026.

- [0010: per-source staging concurrency](0010-staging-concurrency.md) — development implementation, 22 November 2026.

- [0011: indexed IRC inspection across batches](0011-indexed-irc-inspection.md) — development implementation, 22 November 2026.

Record future decisions with context, alternatives, consequences and status. Supersede rather than silently delete decisions.

- [0044: slashless privacy boundaries](0044-slashless-privacy-boundaries.md) — development implementation, 23 November 2026.

- [0045: public display control characters](0045-public-display-control-characters.md) — development implementation, 23 November 2026.

- [0046: current-field search recheck](0046-current-field-search-recheck.md) — development implementation, 23 November 2026.

- [0047: reject future-dated signed cursors](0047-reject-future-signed-cursors.md) — development implementation, 23 November 2026.

- [0048: development staff login policy](0048-development-staff-login-policy.md) — development implementation, 23 November 2026.

- [0049: clinical latest-review lock](0049-clinical-latest-review-lock.md) — development-only implementation, 23 November 2026.

- [0050: source latest-review lock](0050-source-latest-review-lock.md) — development-only implementation, 23 November 2026.

- [0051: price latest-review lock](0051-price-latest-review-lock.md) — development-only implementation, 23 November 2026.

- [0052: product-candidate latest-review lock](0052-product-latest-review-lock.md) — development-only implementation, 23 November 2026.

- [0053: triage write conflict boundary](0053-triage-write-conflict-boundary.md) — development-only implementation, 23 November 2026.

- [0054: clinical draft and reference write conflicts](0054-clinical-draft-write-conflicts.md) — development-only implementation, 23 November 2026.

- [0055: staging conflict boundary](0055-staging-conflict-boundary.md) — development-only implementation, 23 November 2026.

- [0056: clinical inspection author presence](0056-clinical-inspection-author-presence.md) — development-only implementation, 23 November 2026.

- [0057: source queue recorder presence](0057-source-queue-recorder-presence.md) — development-only implementation, 23 November 2026.

- [0058: ID-only account observations](0058-id-only-account-observations.md) — development-only implementation, 23 November 2026.

- [0059: CSV short-read boundary](0059-csv-short-read-boundary.md) — development-only implementation, 23 November 2026.

- [0060: inactive backend staff login](0060-inactive-backend-staff-login.md) — development-only implementation, 23 November 2026.

- [0061: identity lineage depth bound](0061-identity-lineage-depth-bound.md) — development-only implementation, 23 November 2026.

- [0062: price CLI payload check](0062-price-cli-payload-check.md) — development-only implementation, 23 November 2026.

- [0063: projection repair conflict boundary](0063-projection-repair-conflict-boundary.md) — development-only implementation, 23 November 2026.

- [0064: unsafe presentation price matching](0064-price-matching-unsafe-presentation.md) — development-only implementation, 23 November 2026.

- [0065: price detail payload gate](0065-price-detail-payload-gate.md) — development-only implementation, 23 November 2026.

- [0066: source claim write conflicts](0066-source-claim-write-conflicts.md) — development-only implementation, 23 November 2026.

- [0067: source review snapshot inspection](0067-source-review-inspection.md) — development-only implementation, 23 November 2026.

- [0068: source detail review comparisons](0068-source-detail-review-comparisons.md) — development-only implementation, 23 November 2026.

- [0069: product detail consistency gate](0069-product-detail-consistency-gate.md) — development-only implementation, 23 November 2026.

- [0070: PostgreSQL catalog clues](0070-postgresql-catalog-clues.md) — development-only implementation, 23 November 2026.

- [0071: isolated general PostgreSQL tests](0071-isolated-general-tests.md) — development-only implementation, 23 November 2026.

- [0072: PostgreSQL foreign-key behavior clues](0072-postgresql-foreign-key-behavior.md) — development-only implementation, 23 November 2026.

- [0073: PostgreSQL unique-key clues](0073-postgresql-unique-key-clues.md) — development-only implementation, 23 November 2026.

- [0016: bounded clinical technical inspection](0016-clinical-technical-inspection.md) — development-only implementation, 22 November 2026.

- [0017: batched clinical technical inspection](0017-batched-clinical-inspection.md) — development-only implementation, 22 November 2026.

- [0018: synthetic clinical draft parent-path inspection](0018-clinical-draft-lineage.md) — development-only implementation, 22 November 2026.

- [0019: synthetic clinical review snapshot inspection](0019-clinical-review-inspection.md) — development-only implementation, 22 November 2026.

- [0020: request-local price staging match observations](0020-price-staging-match-cache.md) — development-only implementation, 22 November 2026.

- [0021: bounded request-local price IRC candidate indexes](0021-price-irc-candidate-cache.md) — development-only implementation, 22 November 2026.

- [0022: price-review concurrency boundaries](0022-price-review-concurrency.md) — development-only tests and input hardening, 22 November 2026.

- [0023: serialize partial presentation projection writes](0023-presentation-partial-save-projections.md) — development implementation, 22 November 2026.

- [0024: explicit one-row synthetic projection repair](0024-synthetic-projection-repair.md) — development-only local command, 22 November 2026.

- [0025: bounded receipt-row consistency inspection](0025-manifest-consistency-inspection.md) — development-only, read-only inspection, 22 November 2026.
