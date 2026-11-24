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

- [0074: PostgreSQL named check-constraint clues](0074-postgresql-check-constraint-names.md) — development-only implementation, 23 November 2026.

- [0075: PostgreSQL managed-column clues](0075-postgresql-column-clues.md) — development-only implementation, 23 November 2026.

- [0076: PostgreSQL readiness retry window](0076-postgresql-readiness-window.md) — development-only implementation, 23 November 2026.

- [0077: cross-domain synthetic restore drill](0077-cross-domain-restore-drill.md) — development-only implementation, 23 November 2026.

- [0078: PostgreSQL column type clues](0078-postgresql-column-type-clues.md) — development-only implementation, 24 November 2026.

- [0079: restored synthetic sequence probes](0079-restored-sequence-probes.md) — development-only implementation, 24 November 2026.

- [0080: PostgreSQL model-index presence](0080-postgresql-index-presence.md) — development-only implementation, 24 November 2026.

- [0081: PostgreSQL named-index directions](0081-postgresql-index-directions.md) — development-only implementation, 24 November 2026.

- [0082: PostgreSQL named-index null order](0082-postgresql-index-null-order.md) — development-only implementation, 24 November 2026.

- [0083: PostgreSQL named-index operator class](0083-postgresql-index-operator-class.md) — development-only implementation, 24 November 2026.

- [0084: PostgreSQL named-index collation and included columns](0084-postgresql-index-collation-and-include.md) — development-only implementation, 24 November 2026.

- [0085: PostgreSQL unique-key null semantics](0085-postgresql-unique-null-semantics.md) — development-only implementation, 24 November 2026.

- [0086: unsupported unique declarations](0086-unsupported-unique-declarations.md) — development-only implementation, 24 November 2026.

- [0087: PostgreSQL unique-key enforcement timing](0087-postgresql-unique-enforcement.md) — development-only implementation, 24 November 2026.

- [0088: PostgreSQL unique-key operator and collation clues](0088-postgresql-unique-operator-collation.md) — development-only implementation, 24 November 2026.

- [0089: PostgreSQL migration-recorder columns](0089-postgresql-migration-recorder-columns.md) — development-only implementation, 24 November 2026.

- [0090: optimization-safe synthetic restore verification](0090-optimized-synthetic-restore-verification.md) — development-only implementation, 24 November 2026.

- [0091: fail-stop synthetic backup example](0091-synthetic-backup-guide-fail-stop.md) — development-only documentation and tests, 24 November 2026.

- [0092: PostgreSQL migration-recorder primary key](0092-postgresql-migration-recorder-primary-key.md) — development-only implementation, 24 November 2026.

- [0093: PostgreSQL auto-field generation clues](0093-postgresql-auto-field-generation.md) — development-only implementation, 24 November 2026.

- [0094: PostgreSQL legacy serial default clue](0094-postgresql-serial-default-clue.md) — development-only implementation, 24 November 2026.

- [0095: source-claim replay integrity](0095-source-claim-replay-integrity.md) — development-only implementation, 24 November 2026.

- [0096: product staging replay integrity](0096-product-staging-replay-integrity.md) — development-only implementation, 24 November 2026.

- [0097: price staging replay integrity](0097-price-staging-replay-integrity.md) — development-only implementation, 24 November 2026.

- [0098: failed-restore relation counts](0098-failed-restore-relation-counts.md) — development-only implementation, 24 November 2026.

- [0099: manifest ordinal distinctness](0099-manifest-ordinal-distinctness.md) — development-only implementation, 24 November 2026.

- [0100: manifest header consistency](0100-manifest-header-consistency.md) — development-only implementation, 24 November 2026.

- [0101: PostgreSQL trigger session clues](0101-postgresql-trigger-session-clues.md) — development-only implementation, 24 November 2026.

- [0102: synthetic backup argument guards](0102-synthetic-backup-argument-guards.md) — development-only guide, 24 November 2026.

- [0103: selected PostgreSQL auto-sequence settings](0103-postgresql-auto-sequence-sign-cycle.md) — development-only implementation, 24 November 2026.

- [0104: selected constant check-constraint clues](0104-postgresql-constant-check-clues.md) — development-only implementation, 24 November 2026.

- [0105: selected constant-false check clues](0105-postgresql-false-check-clues.md) — development-only implementation, 24 November 2026.

- [0106: check expression reuse](0106-check-expression-reuse.md) — development-only implementation, 24 November 2026.

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
