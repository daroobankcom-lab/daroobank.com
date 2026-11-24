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

- [0012: Private synthetic catalog identity assertions](0012-synthetic-identity-drafts.md) — development-only, 22 November 2026.

- [0013: Private package correction branches](0013-synthetic-package-revisions.md) — development-only, 22 November 2026.

- [0014: Private ingredient, formulation and product correction branches](0014-synthetic-component-revisions.md) — development-only, 22 November 2026.

- [0015: Bounded inspection of synthetic correction ancestry](0015-synthetic-lineage-inspection.md) — development-only, 22 November 2026.

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

- [0026: receipt candidate validation reuse and product triage boundaries](0026-receipt-validation-reuse-and-product-review.md) — development-only, 22 November 2026.

- [0027: keyboard skip navigation and browser diagnostics](0027-keyboard-skip-navigation.md) — development-only, 22 November 2026.

- [0028: source and clinical triage input and concurrency boundaries](0028-source-clinical-triage-boundaries.md) — development-only, 22 November 2026.

- [0029: lock existing clinical reference rows during writes](0029-clinical-reference-row-locks.md) — development-only, 22 November 2026.

- [0030: lock the immediate clinical draft parent during selected writes](0030-clinical-immediate-parent-locks.md) — development-only, 22 November 2026.

- [0031: distinguish clinical draft and reference comparisons in review detail](0031-clinical-detail-review-comparisons.md) — development-only, 22 November 2026.

- [0032: bounded reviewer lookup for private triage histories](0032-reviewer-lookup-in-intake-history.md) — development-only, 22 November 2026.

- [0033: current creator-account presence in source and clinical workflows](0033-missing-source-and-clinical-creators.md) — development-only, 22 November 2026.

- [0034: current product and price stager-account presence](0034-missing-product-and-price-stagers.md) — development-only, 22 November 2026.

- [0035: retaining receipts with missing actor accounts](0035-missing-receipt-actors.md) — development-only, 22 November 2026.

- [0036: current identity package reviewer lookup](0036-identity-reviewer-lookup.md) — development-only, 22 November 2026.

- [0037: current creator presence for identity graph writes](0037-identity-graph-creator-presence.md) — development-only, 22 November 2026.

- [0038: immediate product row lock for identity package review and correction](0038-identity-package-product-lock.md) — development-only, 22 November 2026.

- [0039: formulation row lock for identity package review and correction](0039-identity-package-formulation-lock.md) — development-only, 22 November 2026.

- [0040: bounded identity component and ingredient row locks](0040-identity-components-and-ingredients-locks.md) — development-only, 22 November 2026.

- [0041: lock the existing latest identity package review](0041-identity-latest-review-lock.md) — development-only, 23 November 2026.

- [0042: translate selected identity writer concurrency errors](0042-identity-write-concurrency-errors.md) — development-only, 23 November 2026.

- [0043: isolated synthetic PostgreSQL restore drill](0043-synthetic-postgresql-restore-drill.md) — development-only, 23 November 2026.

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

- [0107: partial presentation validation](0107-partial-presentation-validation.md) — development-only implementation, 24 November 2026.

- [0108: price conversion input bound](0108-price-conversion-input-bound.md) — development-only implementation, 24 November 2026.

- [0109: isolated test-database collision](0109-isolated-test-database-collision.md) — development-only implementation, 24 November 2026.

- [0110: PostgreSQL session-access clues](0110-postgresql-session-access-clues.md) — development-only implementation, 24 November 2026.

- [0111: legacy receipt and clinical migrations](0111-legacy-receipt-clinical-migrations.md) — development-only tests, 24 November 2026.

- [0112: presentation projection migration test](0112-presentation-projection-migration-test.md) — development-only test, 24 November 2026.

- [0113: historical test setup cleanup](0113-historical-test-setup-cleanup.md) — development-only test reliability, 24 November 2026.

- [0114: isolated teardown name guard](0114-isolated-teardown-name-guard.md) — development-only safeguard, 24 November 2026.

- [0115: public-read role probe](0115-public-read-role-probe.md) — development-only test, 24 November 2026.

- [0116: synthetic encrypted restore drill](0116-synthetic-encrypted-restore-drill.md) — development-only test, 24 November 2026.

- [0117: price amount invisible characters](0117-price-amount-invisible-characters.md) — development-only validation, 24 November 2026.

- [0118: intake raw control characters](0118-intake-raw-control-characters.md) — development-only validation, 24 November 2026.

- [0119: explicit intake commit mode](0119-explicit-intake-commit-mode.md) — development-only validation, 24 November 2026.

- [0120: synthetic search-index experiment](0120-synthetic-search-index-experiment.md) — opt-in experiment, 24 November 2026; no index migration.

- [0121: development content-security policy](0121-development-content-security-policy.md) — baseline only, 24 November 2026.

- [0122: publication verification-date constraint](0122-publication-verification-date-constraint.md) — development migration, 24 November 2026.

- [0123: defer public search projections](0123-defer-public-search-projection.md) — development read optimization, 24 November 2026.

- [0124: search query controls](0124-search-query-controls.md) — development input validation, 24 November 2026.

- [0125: public detail ID type](0125-public-detail-id-type.md) — development input validation, 24 November 2026.

- [0126: bounded repair projection fetch](0126-bounded-repair-projection-fetch.md) — development-only safeguard, 24 November 2026.

- [0127: bounded quality projection](0127-bounded-quality-projection.md) — development-only diagnostic change, 24 November 2026.

- [0128: suppress inconsistent detail values](0128-suppress-inconsistent-detail-values.md) — development-only presentation change, 24 November 2026.

- [0129: queue candidate consistency](0129-queue-candidate-consistency.md) — development-only presentation change, 24 November 2026.

- [0130: unknown candidate status labels](0130-unknown-candidate-status-labels.md) — development-only defensive display, 24 November 2026.

- [0131: unknown source and clinical status labels](0131-unknown-source-clinical-status-labels.md) — development-only defensive display, 24 November 2026.

- [0132: deadlock-test coordination](0132-deadlock-test-coordination.md) — synthetic test reliability, 24 November 2026.

- [0133: staff form raw controls](0133-staff-form-raw-controls.md) — development-only input hardening, 24 November 2026.

- [0134: bound empty staff POSTs](0134-bound-empty-staff-posts.md) — development-only form feedback, 24 November 2026.

- [0135: selected staff form error summaries](0135-selected-staff-form-error-summary.md) — development-only accessibility improvement, 24 November 2026.

- [0136: synthetic CSV downloads](0136-synthetic-csv-downloads.md) — development-only staff workflow, 24 November 2026.

- [0137: price-review snapshot clues](0137-price-review-snapshot-clues.md) — development-only defensive display, 24 November 2026.

Record future decisions with context, alternatives, consequences and status. Supersede rather than silently delete decisions.
