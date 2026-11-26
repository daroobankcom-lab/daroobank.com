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

- [0138: source deadlock victim](0138-source-deadlock-victim.md) — synthetic test correction, 24 November 2026.

- [0139: candidate review error summary](0139-candidate-review-error-summary.md) — development-only server-rendered usability, 24 November 2026.

- [0140: product-review snapshot clues](0140-product-review-snapshot-clues.md) — development-only defensive display.

- [0141: candidate-review inspection](0141-candidate-review-inspection.md) — development-only bounded inspection.

- [0142: raw multiline controls](0142-raw-multiline-controls.md) — development-only selected form validation.

- [0143: more review error summaries](0143-more-review-error-summaries.md) — development-only server-rendered usability.

- [0144: identity revision error navigation](0144-identity-revision-error-navigation.md) — development-only server-rendered usability.

- [0145: window form input and errors](0145-window-form-input-and-errors.md) — development-only offline calculation.

- [0146: raw concurrency-token controls](0146-raw-concurrency-token-controls.md) — development-only selected form validation.

- [0147: bounded candidate review scan content](0147-bounded-candidate-review-scan-content.md) — development-only defensive inspection.

- [0148: bounded recent review content](0148-bounded-recent-review-content.md) — development-only defensive display.

- [0149: bounded source and clinical review-scan content](0149-bounded-source-clinical-review-scan-content.md) — development-only defensive inspection.

- [0150: bounded review-scan parent fields](0150-bounded-review-scan-parent-fields.md) — development-only defensive inspection.

- [0151: hidden review-token recovery](0151-hidden-review-token-recovery.md) — development-only staff navigation.

- [0152: bounded identity review display](0152-bounded-identity-review-display.md) — development-only defensive display.

- [0153: bounded locked identity review](0153-bounded-locked-identity-review.md) — development-only defensive writer read.

- [0154: bounded identity revision-link reason](0154-bounded-identity-revision-reason.md) — development-only defensive inspection.

- [0155: bounded manifest candidate JSON](0155-bounded-manifest-candidate-json.md) — development-only defensive inspection.

- [0156: bounded comparison candidates](0156-bounded-comparison-candidates.md) — development-only defensive inspection.

- [0157: bounded candidate queue JSON](0157-bounded-candidate-queue-json.md) — development-only defensive display.

- [0158: bounded current candidate review](0158-bounded-current-candidate-review.md) — development-only defensive display and writer lock read.

- [0159: bounded staging replay JSON](0159-bounded-staging-replay-json.md) — development-only defensive staging reads.

- [0160: bounded source claim note reads](0160-bounded-source-claim-note-reads.md) — development-only defensive display and inspection.

- [0161: bounded locked source claim note](0161-bounded-locked-source-claim-note.md) — development-only defensive writer reads.

- [0162: bounded clinical scan text](0162-bounded-clinical-scan-text.md) — development-only defensive inspection.

- [0163: bounded clinical detail and lineage](0163-bounded-clinical-detail-lineage.md) — development-only defensive reads.

- [0164: bounded locked clinical draft text](0164-bounded-locked-clinical-draft-text.md) — development-only defensive writer reads.

- [0165: canonical new clinical revision reason](0165-canonical-new-clinical-revision-reason.md) — development-only write behavior.

- [0166: defer search projection in matching](0166-defer-search-projection-in-matching.md) — development-only defensive reads.

- [0167: omit old projection from partial save](0167-omit-old-projection-from-partial-save.md) — development-only defensive locked read.

- [0168: identity numeric raw controls](0168-identity-numeric-raw-controls.md) — development-only input validation.

- [0169: staff date raw controls](0169-staff-date-raw-controls.md) — development-only input validation.

- [0170: bounded price CLI candidate JSON](0170-bounded-price-cli-candidate-json.md) — development-only diagnostic reads.

- [0171: explicit staff checkbox values](0171-explicit-staff-checkbox-values.md) — development-only form validation.

- [0172: defensive bounded JSON decoding](0172-defensive-bounded-json-decoding.md) — development-only selected reads.

- [0173: checkbox bound rendering](0173-checkbox-bound-rendering.md) — development-only form rendering correction.

- [0174: clinical lock observation timing](0174-clinical-lock-observation-timing.md) — test-only coordination.

- [0175: formset management raw input](0175-formset-management-raw-input.md) — development-only selected form validation.

- [0176: staff single-value duplicates](0176-staff-single-value-duplicates.md) — development-only selected form validation.

- [0177: deferred presentation save intent](0177-deferred-presentation-save-intent.md) — development data-integrity fix.

- [0178: clinical child author status](0178-clinical-child-author-status.md) — development-only bounded preview.

- [0179: disabled raw inputs](0179-disabled-raw-inputs.md) — shared form compatibility.

- [0180: opt-in process and database probes](0180-opt-in-process-database-probes.md) — narrow operational foundation.

- [0181: development staff-login throttle](0181-development-staff-login-throttle.md) — opt-in synthetic defense in depth.

- [0182: repeated staff-login credentials](0182-repeated-staff-login-credentials.md) — narrow form hardening.

- [0183: non-debug config guards](0183-nondebug-config-guards.md) — explicit secret and host configuration.

- [0184: trusted proxy scheme](0184-trusted-proxy-scheme.md) — explicit, default-off configuration.

- [0185: opt-in HSTS](0185-opt-in-hsts.md) — explicit header duration, not a TLS deployment.

- [0186: staff password input bound](0186-staff-password-input-bound.md) — development form limit before authentication.

- [0187: bounded login-window maintenance](0187-bounded-login-window-maintenance.md) — selected server-side timeouts, not a scheduler or full deadline.

- [0188: non-debug frame guard order](0188-nondebug-frame-guard-order.md) — covers selected early Django responses.

- [0189: known-path early error privacy](0189-known-path-early-error-privacy.md) — selected early Django errors receive existing privacy headers.

- [0190: synthetic repair token via stdin](0190-synthetic-repair-token-stdin.md) — avoid one command's token argument exposure.

- [0191: staff session revocation gap](0191-staff-session-revocation-gap.md) — unresolved reactivation/regrant behavior.

- [0192: source-claim account-status serialization](0192-source-claim-account-status-serialization.md) — narrow PostgreSQL write ordering, not general revocation.

- [0193: source-claim session hash binding](0193-source-claim-session-hash-binding.md) — one guarded write rechecks the session's password hash; still not revocation.

- [0194: source-review actor and session recheck](0194-source-review-actor-session-recheck.md) — unlocked reviewer recheck preserving one lock order; still not revocation.

- [0195: shared write-actor recheck](0195-shared-write-actor-recheck.md) — one helper reused by guarded review services; unlocked rechecks still race.

- [0196: staging write actor recheck](0196-staging-write-actor-recheck.md) — the same helper on the bulk staging paths, plus corrected stale-cache evidence.

- [0197: clinical write actor recheck](0197-clinical-write-actor-recheck.md) — draft create/revise and reference create rechecked before their locks.

- [0198: identity write actor recheck](0198-identity-write-actor-recheck.md) — the seven identity workspace writes rechecked before their row locks.

- [0199: staff write route guard inventory](0199-staff-write-route-guard-inventory.md) — in-flight tests for all fourteen write routes plus a drift guard.

- [0200: staff authorization matrix](0200-staff-authorization-matrix.md) — every staff route against six synthetic account shapes.

- [0201: staff authorization against existing rows](0201-staff-authorization-existing-rows.md) — the same matrix over real rows, so denials do not become an existence oracle.

- [0202: public-route privacy matrix](0202-public-route-privacy-matrix.md) — every non-staff route inventoried and checked for private-data leakage.

- [0203: staff grant paths](0203-staff-grant-paths.md) — group grants, the superuser bypass, an alternate backend and stale in-memory actors.

- [0204: staff denial parity](0204-staff-denial-parity.md) — denials for existing and missing rows are byte-identical, so existence is not an oracle.

- [0205: identifier and method parity](0205-staff-identifier-and-method-parity.md) — thirteen identifier shapes and both method directions across five account shapes.

- [0206: query-parameter parity](0206-staff-query-parameter-parity.md) — nine caller-controlled query shapes across all 41 staff routes.

- [0207: the staff CSRF gate](0207-staff-csrf-gate-parity.md) — one canonical rejection across all 43 routes, and the method classification read from the decorators.

- [0208: session lifecycle](0208-staff-session-lifecycle.md) — logout, cookie replay, password change and expiry walked across all 41 routes.

- [0209: staff method sweep](0209-staff-method-sweep.md) — six HTTP methods across all 43 routes, with no destructive method accepted.

- [0210: staff header inventory](0210-staff-header-inventory.md) — one closed header inventory across 1 204 staff responses, for every account shape.

- [0211: staff redirect targets](0211-staff-redirect-targets.md) — a caller-supplied `next` cannot aim login, logout or an anonymous redirect off-host.

- [0212: `Expires` parity exclusion](0212-expires-parity-exclusion.md) — the per-second `never_cache` stamp on the two auth endpoints, excluded from byte-parity comparisons.

- [0213: durable session invalidation](0213-durable-session-invalidation.md) — a session bound to its account's state, ended by any change to it; closes the ADR 0191 revival scenario.

- [0214: session inventory](0214-session-inventory.md) — a read-only report of which sessions exist and which the guard would end, with no session material in it.

- [0215: the generated authorization review](0215-generated-authorization-review.md) — the endpoint inventory the Phase 1 review asks for, derived from the resolver and drift-checked; its judgement stays unsigned.

- [0216: migration reversibility](0216-migration-reversibility.md) — rollback and reapply measured on throwaway PostgreSQL databases, with the dependent-app cascade derived from the migration graph.

- [0217: the deployment readiness report](0217-deployment-readiness-report.md) — ten required settings and database checks plus the undecided conditions, in one read-only JSON report; a zero exit status is not an authorization.

- [0218: no `django.contrib.admin`](0218-no-django-admin.md) — the staff portal is the only administrative surface, and the absence is pinned by seven tests.

- [0219: every management command is documented where an operator looks](0219-documented-command-surface.md) — the twelve commands and their options are held to the development guide, the operations runbook and the deployment guide; naming is checked, correctness of the prose is not.

- [0220: actor attribution is a schema property](0220-actor-attribution-inventory.md) — 19 of the 23 project models name the account that wrote them behind a protected foreign key and a creation timestamp; the published catalog record names nobody, and a candidate staged from the command line can never be reviewed in the portal.

- [0221: nothing records that a read happened](0221-no-read-audit.md) — `LOGGING` is empty, no module imports `logging`, no middleware records a request, no table can hold an access record, and sweeping all 55 routes creates no row; the absence is pinned, not fixed.

- [0222: the environment is documented in one place per audience](0222-documented-environment.md) — fifteen variables, four opt-in test switches and one default, pinned from an AST inventory and held to the template, the Compose stack, the development guide and a new deployment configuration reference.

- [0223: abuse protection is external](0223-no-abuse-protection.md) — the only rate limit is the opt-in debug-only login window, 48 sequential public reads all answer 200, no request-size ceiling is configured, and the deployment guide now assigns rate and size limits to the edge.

- [0224: the documentation graph resolves](0224-documentation-graph.md) — 251 markdown documents, 224 numbered decision records, every link, anchor, index entry and named suite resolves, and no document is orphaned.

- [0225: rollback with data in it](0225-populated-rollback-drill.md) — a populated throwaway database loses 23 of its 30 rows to a single-app rollback and all of them to a full one, a reapply returns an identical schema and zero rows, only a copy taken beforehand brings rows back and only after the identity sequences are advanced, and a rollback blocked by one locked row leaves the database half undone.

- [0226: CI verifies every dependency and produces no artifact](0226-ci-artifact-gate.md) — one workflow, two jobs, 22 steps, five actions pinned to commit SHAs, both lock files hash-pinned with a negative control, and zero artifact uploads, image pushes, SBOMs, signatures, digests, staging environments or exported outputs.

- [0227: the read-audit decision and its measured price](0227-read-audit-plan.md) — a proposal names the six decisions that block read auditing, and a reverted prototype of the in-application option measures 20 pin failures across 7 suites and a 33-table schema.

- [0228: an opt-in limit on public reads](0228-public-read-limit.md) — a second opt-in limiter counts 120 public reads per keyed client in a rolling minute and refuses an over-limit one with 429 and a `Retry-After`, storing a keyed digest, a window start and a count, failing open when the counter is unreachable, and moving 19 pins and the schema to 33 tables.

- [0229: the two write paths that name nobody](0229-attribution-gap-plan.md) — the published catalog record and command-line price staging are measured again, three facts ADR 0220 did not measure are added, and a proposal with no owner prices six options and lists seven decisions.

- [0230: the MFA plan and the measured price of a second factor](0230-mfa-implementation-plan.md) — the authentication surface is measured instead of described: one login view rendering two credential fields, no factor state in any model or module, a stock `auth.User`, nothing between the password and the session, two address-keyed opt-in limiters that are not lockouts, no cryptographic library, a hash-pinned audited lock and a 33-table schema; an unowned proposal prices six options and lists seven decisions, and no factor is implemented.

Record future decisions with context, alternatives, consequences and status. Supersede rather than silently delete decisions.
