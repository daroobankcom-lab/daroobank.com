# Implementation changelog

Entries describe the state at each change; later entries can supersede earlier limitations.

## 2026-11-26 — extend the actor recheck to the clinical write paths

**Changes:** `clinical.services.create_draft` and `clinical.evidence.add_reference` accept an optional `session_auth_hash` and call the shared `recheck_actor` as the first statement inside their writer transactions, before the draft lock, so no row is written against a stale actor. The clinical create, revise and reference-create views pass the request session's password hash. `clinical/test_write_actor_recheck.py` and `daroobank/test_staff_inflight_clinical_writes.py` cover matching/omitted/stale hashes, password rotation, disabled/destaffed/deleted writers, a permission removed through a second instance, parked races and the CSRF negative control. See ADR 0197.

**Limits:** The rechecks are unlocked point-in-time reads, so parked-writer tests still create a draft and a reference after disable, password invalidation and reactivation; a flag-only disable/reactivate still permits a parked HTTP create. Nine services across ten staff routes are covered, identity/revision services and reads are untouched, permission changes remain unserialized and durable session revocation is still absent. ADR 0191 remains a release blocker.

## 2026-11-26 — extend the actor recheck to staging and correct stale-cache evidence

**Changes:** `catalog.intake.stage_products` and `pricing.importer.stage_csv` recheck their stager through the shared helper in commit mode, after the source-stage lock and before any row is written; the receipt wrappers forward the hash and both upload views supply it from the session. Permission-removal tests across the ADR 0192–0196 suites now remove permissions, group membership or group permissions through a second user instance, because Django clears an instance's own permission cache and the earlier tests could pass without exercising the recheck. A near-miss session hash in `daroobank/test_actor_recheck.py` is now derived by flipping one character; a fixed digit made that case fail in one optimized-mode run when it coincided with the real hash. See ADR 0196.

**Limits:** The staging rechecks are unlocked point-in-time reads, so parked-writer tests still stage rows and receipts after disable, password invalidation and reactivation; preview mode and actor-less price staging are not rechecked. Seven services on seven staff routes are covered, permission changes remain unserialized and durable session revocation is still absent. ADR 0191 remains a release blocker.

## 2026-11-26 — extend the shared actor recheck to catalog product review

**Changes:** `catalog.intake.review_product` now rechecks its reviewer through the shared helper after locking the candidate row, and the staff product review view passes the request session's password hash. `catalog/test_review_actor_recheck.py` and two HTTP cases in `daroobank/test_staff_inflight_review_writes.py` cover stale/disabled/destaffed/deleted reviewers, removed permissions behind a primed cache, stale and malformed hashes, password rotation, a parked race and the CSRF negative control.

**Limits:** The reviewer read is unlocked to preserve one lock order, so a credential change committed after it still races and a flag-only disable/reactivate still lets a parked review commit. Five services on five routes are covered; staging paths, other writes, permission serialization and durable session revocation remain open. ADR 0191 remains a release blocker.

## 2026-11-26 — cover the price and clinical review guards over HTTP

**Changes:** `daroobank/test_staff_inflight_review_writes.py` parks CSRF-valid price and clinical review POSTs inside service input validation. Disable plus password invalidation plus reactivation before the guard now provably yields 403 with no review and a login redirect for the next request from that session; a flag-only disable/reactivate still commits, and a missing CSRF token is rejected.

**Limits:** Two routes and selected orderings. These tests assert the views pass the session hash; they do not make revocation durable or race-free, and ADR 0191 remains a release blocker.

## 2026-11-26 — share one write-actor recheck across four guarded services

**Changes:** A new `daroobank/actor_recheck.py` helper reloads a write actor, repeats its active/staff/permission checks on the fresh instance and optionally binds the write to the session password hash, with an opt-in account-row lock. Source-claim creation and review now use it, and `pricing.reviews.record_preliminary_review` and `clinical.services.review_draft` gain the unlocked recheck plus session-hash binding, supplied by their staff views. See ADR 0195.

**Limits:** Only `record_claim` locks the account row; the other three rechecks are unlocked point-in-time reads, so selected parked-writer tests still commit a review after disable, password invalidation and reactivation. Four services on four routes are covered, the hash reflects the password only, permission changes are still not serialized, and durable session revocation remains absent. ADR 0191 remains a release blocker.

## 2026-11-26 — recheck the source reviewer and bind review to the session hash

**Changes:** `review_claim` accepts an optional `session_auth_hash`, which the staff review view supplies from the request session. After locking the claim row and before creating a review, the service rejects an invalid actor key, reloads the reviewer without a row lock, repeats the active/staff/permission checks on that fresh instance and compares the supplied hash in constant time, denying with 403. Synchronized synthetic tests now show disable plus password invalidation plus reactivation before the guard are denied. See ADR 0194.

**Limits:** The reviewer read is unlocked to preserve the single account-then-claim lock order, so a credential change after that read still races; a parked review commits in a selected test, as does a flag-only disable/reactivate. One service and route are covered, the hash reflects the password only, and durable session revocation remains absent. ADR 0191 remains a release blocker.

## 2026-11-26 — bind the source-claim write to the session password hash

**Changes:** `record_claim` accepts an optional `session_auth_hash`; the development staff create view passes the request session's authentication hash, and the guarded transaction compares it in constant time with the freshly locked account's current hash, denying a mismatch or non-string value with 403. A synchronized synthetic test now shows disable, password invalidation and reactivation committing before the guard are denied. See ADR 0193.

**Limits:** One service and one route are covered; review and other writes are untouched. The hash reflects the password only, so a flag-only disable/reactivate still lets the parked write commit, permission/group changes still race, and there is no durable session revocation. ADR 0191 remains a release blocker.

## 2026-11-26 — document reactivation race around the source-claim guard

**Finding:** A synchronized synthetic HTTP test shows that when account disable, password invalidation and reactivation all commit before the guarded source-claim write, the in-flight already-authorized old session still creates the claim; its next request is denied and the CSRF negative control stays intact.

**Limits:** One route and one ordering are covered. The guard checks current account state, not the requesting session's authentication hash, so there is still no race-free revocation; ADR 0191 remains a release blocker.

## 2026-11-26 — recheck source-claim permissions on a fresh actor

**Changes:** The selected source-claim transaction rechecks required permissions on its freshly loaded actor, rather than relying only on a possibly cached request actor.

**Limits:** Permission or group removal after the recheck can still race and allow the write. This is not durable permission revocation; see ADR 0192.

## 2026-11-26 — serialize source-claim account status with selected writes

**Changes:** The PostgreSQL source-claim recording transaction locks and checks its actor's current active/staff flags before creating or replaying a claim. Synthetic tests cover both account-update orderings and key-share compatibility.

**Limits:** This orders only one service and cannot cancel an earlier writer; session reactivation, cached permissions, other writes, lock waits and broader account lifecycle remain open. See ADR 0192.

## 2026-11-26 — document selected in-flight staff write race

**Finding:** A CSRF-valid synthetic source-claim POST already past its authorization checks can commit after account disable and password invalidation; a new request while disabled does not create another claim.

**Limits:** One route and one ordering are tested. No race-free revocation control or production procedure is implemented; ADR 0191 remains a release blocker.

## 2026-11-26 — document in-flight staff read boundary

**Finding:** A synchronized synthetic workspace request can finish successfully after the account is disabled and its password invalidated; two selected old sessions fail on later requests after the password change, while another account remains unaffected.

**Limits:** These are selected observations, not a revocation implementation, an in-flight write test, or a production procedure. The production blocker in ADR 0191 remains open.

## 2026-11-26 — document unresolved staff-session revocation gap

**Finding:** Synthetic tests show that reactivating an account or restoring its staff flag can make an existing unexpired session usable again. A selected password-change test invalidates an old session on a later request but is not a complete incident or revocation procedure.

**Status:** Durable session revocation remains a production blocker; see ADR 0191.

## 2026-11-26 — revoked-staff boundary regression

**Changes:** A synthetic existing-session test exercises named staff routes after the staff flag is revoked, including an account that retains superuser permissions.

**Limits:** This does not establish concurrent revocation, production security or complete authorization coverage; see Testing strategy.

## 2026-11-26 — optional stdin for synthetic projection repair token

**Changes:** The one-row repair command accepts a bounded token via non-terminal stdin as an alternative to the legacy argument. Invalid combinations and non-debug use fail before reading.

**Limits:** Preview output, token files, other processes, pipes and logs still need protection; this is not authorization or a production tool. See ADR 0190.

## 2026-11-26 — privacy headers on selected early errors

**Changes:** The existing outer known-path middleware now applies staff/public privacy headers to selected early errors as well as redirects, including invalid-host 400 responses.

**Limits:** Unknown routes, infrastructure responses and logs are not covered; see ADR 0189.

## 2026-11-26 — frame protection on early non-debug responses

**Changes:** Non-debug frame middleware now wraps the HTTPS redirect and disabled-staff gate; fresh-process tests cover early and ordinary responses and Django's explicit exemptions.

**Limits:** Debug previews remain embeddable, view exemptions remain effective, and upstream/static responses are outside this Django header policy; see ADR 0188.

## 2026-11-26 — suppress selected catalog command traceback chains

**Changes:** Catalog IRC inspection and synthetic projection repair no longer chain selected cursor/token errors into their command tracebacks. Synthetic canaries test both commands, including one real CLI invocation.

**Limits:** Command-line arguments may remain visible to the operating system and shell; service exceptions, other errors and logs are not sanitized by this change.

## 2026-11-26 — bound selected login-window maintenance waits

**Changes:** Synthetic cleanup now refuses outer/non-autocommit transactions and runs with PostgreSQL-local lock and statement timeouts. Timeout and connection-reuse tests exercise selected failures and the refreshed-row race remains covered.

**Limits:** These are server-side statement/lock limits, not full request/network deadlines or a scheduler; see ADR 0187.

## 2026-11-26 — disabled staff boundary regression tests

**Changes:** Tests enumerate currently named staff routes, verify the shared gated path, and exercise private 404 responses for GET, HEAD and POST before session loading when the portal is disabled.

**Limits:** These are Django-level tests, not production access controls, a review of future unnamed routes or proof of network isolation.

## 2026-11-26 — PostgreSQL connection lifetime bound

**Changes:** `POSTGRES_CONN_MAX_AGE` now fails startup outside 0–31,536,000 seconds. Extremely large integers previously passed configuration and could overflow Django's connection deadline.

**Limits:** The upper bound changes compatibility and is not a recommendation for long-lived connections or a network deadline. Real pooling and timeout policies need separate review.

## 2026-11-26 — selected maintenance traceback redaction

**Changes:** Generic database failures in synthetic login-window cleanup and the PostgreSQL schema/access inspectors no longer chain driver errors into formatted tracebacks. The offline schedule command likewise suppresses chained parser errors, which may contain input. Synthetic canary tests include `--traceback` CLI runs.

**Limits:** This does not scrub database/server logs, other commands, direct exception introspection or unexpected exception types; operators must still control diagnostic access and logging.

## 2026-11-26 — development staff-login password bound

**Changes:** The staff form rejects passwords over 4,096 characters before calling the backend, with the generic invalid-login error. CSRF-valid attempts still count toward the opt-in synthetic throttle.

**Limits:** This is a compatibility change for longer existing passwords, not a request-body limit, MFA or a production abuse control; see ADR 0186.

## 2026-11-26 — database configuration error redaction

**Changes:** Invalid PostgreSQL port or connection lifetime still fails startup, but no longer chains Python's conversion exception, which may contain the configured value. Fresh-process tests exercise synthetic canaries.

**Limits:** This covers these two integer settings only, not all startup, process, infrastructure or database logs; secrets must still be managed and logs reviewed separately.

## 2026-11-26 — optional non-debug HSTS duration

**Changes:** A bounded explicit HSTS max-age can be configured outside debug; the default remains off and subdomain/preload directives stay disabled.

**Limits:** HSTS persists in browsers, and resetting this option to zero does not clear an earlier policy. TLS, ownership and recovery require independent review; see ADR 0185.

## 2026-11-26 — opt-in trusted proxy scheme

**Changes:** A default-off non-debug option accepts a single forwarded scheme only from configured immediate peer networks, and rejects universal or malformed network lists.

**Limits:** This does not authenticate a proxy or firewall the app; a proxy must overwrite client-supplied headers and preserve the approved host. No TLS infrastructure or production authorization follows. See ADR 0184.

## 2026-11-26 — fail closed on selected non-debug configuration

**Changes:** Outside debug, startup requires a secret of an accepted minimum shape and explicitly configured, syntactically valid non-wildcard hosts. Debug preview defaults are unchanged.

**Limits:** This is a compatibility change, not proof of key randomness, host ownership, TLS, production security or authorization. See ADR 0183.

## 2026-11-25 — reject repeated staff-login credentials

**Changes:** The development staff login form rejects repeated enabled username/password values before invoking an authentication backend, preserving the generic error and existing sessions.

**Limits:** Other parameters and authentication routes remain outside this check; see ADR 0182.

## 2026-11-25 — opt-in synthetic staff-login throttle

**Changes:** An optional development-only shared PostgreSQL fixed-window throttle limits CSRF-accepted staff-login POSTs by pseudonymized server client address. A dry-run-first, bounded synthetic maintenance command removes older windows when explicitly requested.

**Limits:** Default off, disabled outside debug; not MFA, distributed-attack protection or a production access policy. Proxy configuration, unbounded row growth, manual cleanup and security review remain important; see ADR 0181.

## 2026-11-25 — opt-in process and PostgreSQL probes

**Changes:** Added default-off, minimal HTTP process liveness and database-connectivity probes; database errors return a generic unavailable response and selected responses are not cached.

**Limits:** The unauthenticated paths require separate network restriction. A successful probe does not verify migrations, backups, workers, data or production readiness; the SQL timeout is not an end-to-end deadline. See ADR 0180.

## 2026-11-25 — respect disabled form fields

**Changes:** Shared selected raw-input checks ignore request values for server-disabled fields, consistent with Django's initial-value semantics. Enabled fields retain duplicate and control rejection.

**Limits:** No current workflow was made disabled; other fields and direct service calls remain outside scope. See ADR 0179.

## 2026-11-25 — clinical child preview author status

**Changes:** The capped clinical child preview distinguishes a missing current author account from invalid or oversized child data using one batched existence check.

**Limits:** This is not historical identity or clinical verification and can change immediately. See ADR 0178.

## 2026-11-25 — preserve implicit partial presentation saves

**Changes:** Deferred same-database presentation saves preserve the originally loaded/assigned field set before projection generation and use the existing locked prospective-row path. A selected concurrent synthetic update no longer gets overwritten by an unloaded stale field.

**Limits:** Loaded stale fields, full saves, bulk/direct SQL and other interleavings remain outside this guarantee. See ADR 0177.

## 2026-11-25 — reject selected duplicate staff inputs

**Changes:** Selected single-value staff fields, choices and upload files reject duplicate submissions; an otherwise-empty component row with a duplicate value is no longer silently skipped.

**Limits:** This is not a general defense for every input, proxy, login or direct service. See ADR 0176.

## 2026-11-25 — formulation formset management validation

**Changes:** Selected create and correction formsets reject raw control characters or duplicate values in their total/initial management fields before attempting a write.

**Limits:** Hidden fields are still client-controlled; this does not establish authorization or identity. See ADR 0175.

## 2026-11-25 — clinical lock-test coordination

**Changes:** The synthetic oversized clinical writer test signals immediately before its target-row lock rather than before preliminary reads, while retaining the real PostgreSQL blocker and rollback assertions.

**Limits:** One earlier concurrent full-run failure has no confirmed root cause; timing-sensitive tests cannot establish complete concurrency safety. See ADR 0174.

## 2026-11-25 — checkbox state after form errors

**Changes:** Selected checkboxes now render their validated boolean state after form errors; false or malformed raw values no longer appear checked or echo as the input value.

**Limits:** This does not establish consent or cover all form widgets. See ADR 0173.

## 2026-11-24 — defensive bounded JSON decoding

**Changes:** Selected bounded candidate and review reads decode text defensively, so unusually deep or very large numeric JSONB values do not crash these reads before validation. Incompatible values are suppressed and comparison remains unknown.

**Limits:** The JSON can still be valid PostgreSQL data; this inspection outcome is not an authenticity or clinical finding and does not cover every read. See ADR 0172.

## 2026-11-24 — explicit staff checkbox values

**Changes:** Selected acknowledgements, source scopes and upload-rights checkboxes reject unknown or duplicate values; explicit `0` is false. Normal browser submissions remain supported.

**Limits:** A submitted checkbox does not establish consent, rights, authorization or safety; clients using other strings must update. See ADR 0171.

## 2026-11-24 — bounded price-list CLI payloads

**Changes:** The local price-list command limits selected candidate JSON transfer and emits an explicit oversized/unknown row without matching or printing its payload.

**Limits:** Consumers must handle this new shape; the bound does not cover database work or make output confidential. See ADR 0170.

## 2026-11-24 — reject raw controls in selected staff dates

**Changes:** Source and clinical date forms reject control characters in the original date value instead of silently stripping them or treating them as empty.

**Limits:** This covers selected forms, not all inputs or direct service callers. See ADR 0169.

## 2026-11-24 — reject raw controls in identity numeric inputs

**Changes:** Selected identity IDs and quantities now report field errors instead of silently stripping control characters from raw form submissions.

**Limits:** This is a form-level check, not comprehensive validation of every input or direct service call. See ADR 0168.

## 2026-11-24 — omit discarded projection from partial save

**Changes:** The locked read used for partial presentation saves no longer transfers the old search projection before rebuilding it from the current prospective row.

**Limits:** Other reads, full or bulk writes and database work remain outside this bound. See ADR 0167.

## 2026-11-24 — omit unused matching projections

**Changes:** Product comparison and price matching no longer transfer the unused stored search text, including on their lookahead and selected locked reads.

**Limits:** A later access to a deferred field can still fetch it; database work, other fields and other paths are not bounded. See ADR 0166.

## 2026-11-24 — canonical new clinical revision reasons

**Changes:** The direct clinical revision service validates the original reason, then strips outer whitespace before storing and hashing new revisions; internal whitespace is retained. Existing reasons and fingerprints are not rewritten.

**Limits:** Valid oversized historical reasons remain uninspected and can block selected writers. Input size, other fields and database work are not bounded by this change. See ADR 0165.

## 2026-11-24 — bounded locked clinical draft text

**Changes:** Revision, reference and review writers bound target and immediate-parent text under their existing row locks and conflict on uninspected values.

**Limits:** Even a valid long whitespace-bearing reason may conflict; inputs, database work and other paths are not bounded by this change. See ADR 0164.

## 2026-11-24 — bounded clinical detail and lineage

**Changes:** Selected draft, immediate-parent and child text in private clinical detail and lineage reads is bounded; excessive values remain uninspected and disable unsafe affordances.

**Limits:** This is not a snapshot or clinical validation; locked writer reads and other paths remain outside this bound. See ADR 0163.

## 2026-11-24 — bounded clinical scan text

**Changes:** Clinical queue and technical scan bound selected draft and parent text, reporting oversized values as uninspected rather than necessarily inconsistent.

**Limits:** Direct detail reads, database work and other paths remain outside this bound. See ADR 0162.

## 2026-11-24 — bounded locked source evidence notes

**Changes:** Source replay and review writers avoid transferring oversized evidence notes and reject them under their existing row locks.

**Limits:** Database work and other fields remain outside the bound. See ADR 0161.

## 2026-11-24 — bounded source evidence-note reads

**Changes:** Selected source claim displays and inspections bound evidence-note transfers and hide over-limit content, which is provably invalid under the existing field limit.

**Limits:** Other fields, writers and database work remain outside this bound. See ADR 0160.

## 2026-11-24 — bounded staging replay JSON

**Changes:** Product and price staging pre-lookups select only existing IDs and duplicate rereads bound candidate JSON under the existing lock; oversized replay conflicts roll back.

**Limits:** This is not a database-work bound or authenticity check. See ADR 0159.

## 2026-11-24 — bounded current candidate review

**Changes:** Product and price details and preliminary-review writer lock reads bound selected current-candidate JSON; oversized candidates are uninspected and review creation fails closed.

**Limits:** Other fields, database work, other writers and endpoints remain outside the bound. See ADR 0158.

## 2026-11-24 — bounded candidate queues

**Changes:** Staff product and price queues bound selected candidate JSON transfers and mark oversized content uninspected without changing pagination or counts.

**Limits:** Direct detail requests and database work are outside this bound. See ADR 0157.

## 2026-11-24 — bounded related candidate comparisons

**Changes:** Selected product and price comparison queries avoid transferring oversized related candidate JSON; uninspected comparisons do not yield details or price arithmetic.

**Limits:** Current candidate, database work, other fields and endpoints remain outside this bound. See ADR 0156.

## 2026-11-24 — bounded receipt candidate JSON

**Changes:** Private receipt detail and manifest inspection avoid transferring oversized candidate JSON, report it as uninspected and preserve pagination.

**Limits:** This does not bound database work or other fields and endpoints. See ADR 0155.

## 2026-11-24 — bounded identity revision-link reasons

**Changes:** Identity detail and lineage reads bound selected revision-link reason transfers while keeping existing validation and pagination.

**Limits:** Database work, other graph fields and write paths are not bounded. See ADR 0154.

## 2026-11-24 — bounded locked identity review

**Changes:** Identity review and revision writers bound selected fields in the same locked latest-review read; revision refuses an uninspected oversized latest review without partial classification.

**Limits:** Database work and other graph reads remain unbounded; review creation retains its prior latest-ID-only policy. See ADR 0153.

## 2026-11-24 — bounded identity review display

**Changes:** Private identity-package history and revision pages bound selected review graph and reason transfers. Oversized reviews are explicitly uninspected and preserve ordering and latest-review IDs.

**Limits:** Database work, current graphs and other pages are not bounded; the later ADR 0153 bounds selected latest-review fields in the identity writer lock read. See ADR 0152.

## 2026-11-24 — hidden review-token recovery

**Changes:** Five staff review forms offer an explicit same-origin GET restart for invalid hidden tokens, with a warning that unsaved inputs are discarded.

**Limits:** Reopening does not bypass validation, preserve inputs or guarantee a subsequent submission. See ADR 0151.

## 2026-11-24 — bounded review-scan parent fields

**Changes:** Selected current source and clinical TextFields are bounded during review scans; invalid product/price scan requests check candidate existence without loading candidate JSON.

**Limits:** Other pages and database work remain unbounded. See ADR 0150.

## 2026-11-24 — bounded source and clinical review-scan content

**Changes:** Private source and clinical review scans bound selected snapshot and reason transfers, mark oversized rows as uninspected and retain scoped batch continuation.

**Limits:** Database work and other data, including parent records, remain unbounded. See ADR 0149.

## 2026-11-24 — bounded recent-review content

**Changes:** Four private detail pages bound selected review snapshot and reason transfers, suppress oversized content and retain the newest review's concurrency token.

**Limits:** Database processing, other fields and pages remain unbounded; source and clinical review scans did not inherit this display protection at this step (see the subsequent ADR 0149). See ADR 0148.

## 2026-11-24 — bounded candidate-review scan content

**Changes:** Private product and price review scans bound selected candidate JSON, review snapshot and reason transfers; oversized reviews are explicitly uninspected and filterable.

**Limits:** The database may still read and process large values, and other pages are outside this boundary. This is neither authenticity nor a complete memory/work limit. See ADR 0147.

## 2026-11-24 — selected raw concurrency-token controls

**Changes:** Selected private review, revision and reference forms reject raw control characters and surrogates in hidden concurrency fields before field cleanup can hide them. Synthetic HTTP tests check invalid requests do not write and selected clean retries succeed.

**Limits:** This is not token authentication or a stronger locking guarantee; other writers, logging and possible redisplay of bound values remain outside scope. See ADR 0146.

## 2026-11-24 — offline window form boundaries

**Changes:** The offline schedule form independently validates its three inputs, rejects raw boundary controls and provides an error title and linked summary.

**Limits:** This is only a calculation, not dispatch or source authorization; selected browser checks do not establish comprehensive accessibility. See ADR 0145.

## 2026-11-24 — identity revision error navigation

**Changes:** Selected identity revision forms show an error title and summary with links to visible fields and component errors; unavailable forms do not receive dangling links.

**Limits:** Conflicts still require reloading, and automated/keyboard checks are not comprehensive accessibility validation. See ADR 0144.

## More review error summaries

**Changes:** Selected source, clinical and identity review responses now have an error-specific title and summary; unavailable forms use a fixed notice instead of broken links.

**Limits:** Selected tests are not comprehensive accessibility validation; identity conflicts still require reloading. See ADR 0143.

## Selected raw multiline controls

**Changes:** Selected staff review reasons, clinical statements and revision reasons reject forbidden raw controls before form whitespace cleanup can hide them; permitted multiline whitespace remains supported.

**Limits:** This is not a comprehensive Unicode or log-safety guarantee, and bound forms may redisplay submitted values. See ADR 0142.

## Candidate-review inspection

**Changes:** Private product and price candidate pages offer bounded, read-only review-history inspection with post-batch filtering and explicit continuation.

**Limits:** This is not an audit or authentication; reads are separate and scans are not snapshots. See ADR 0141.

## Product-review snapshot clues

**Changes:** The product candidate detail checks selected recent review snapshots, suppresses inconsistent review details, and compares consistent snapshots with the current candidate.

**Limits:** Unkeyed checks are not authentication or audit; coherent rewrites can pass, reads are not snapshots and other outputs remain outside this display. See ADR 0140.

## 2026-11-24 — candidate review error summaries

**Changes:** Product and price review errors receive a descriptive page title and server-rendered summary; when the form is unavailable, a fixed notice replaces links to absent fields.

**Limits:** Selected synthetic keyboard and automated checks are not comprehensive accessibility validation. See ADR 0139.

## 2026-11-24 — synthetic source deadlock probe

**Changes:** The actual PostgreSQL source-review deadlock probe checks both worker results and permits either real `40P01` victim, with the appropriate rollback or success outcome.

**Limits:** Only a service-victim run exercises translation of a real deadlock through the writer; injected tests cover mappings separately. See ADR 0138.

## 2026-11-24 — price-review snapshot clues

**Changes:** The selected price detail history checks recent stored review snapshots, suppresses details of inconsistent records, and compares consistent snapshots with the current candidate.

**Limits:** This is not authentication, audit or price approval; coherent rewrites can pass, reads are not snapshots and other outputs remain outside this display. See ADR 0137.

## 2026-11-24 — synthetic CSV sample downloads

**Changes:** The two staff upload pages link to their fixed repository-provided synthetic CSV examples, with the same permissions as upload and private download headers.

**Limits:** The files contain invented figures and are public repository examples, not verified source data; arbitrary spreadsheets and real-source permissions are not validated by this convenience. See ADR 0136.

## 2026-11-24 — selected staff form error summaries

**Changes:** Selected source, clinical, identity-create and upload forms show a linked error summary and an error-prefixed title after failed validation, including component-formset errors.

**Limits:** No automatic focus or general assistive-technology guarantee; other forms and manual accessibility review remain outstanding. See ADR 0135.

## 2026-11-24 — empty staff POST feedback

**Changes:** Six selected create, revision, reference and upload views bind even an empty authorized POST so required-field errors are shown; GET stays unbound.

**Limits:** Other views and all client or assistive-technology combinations were not exhaustively checked. See ADR 0134.

## 2026-11-24 — raw controls on selected staff forms

**Changes:** Selected source, clinical and identity assertion forms reject controls and surrogates in raw single-line input even when Django would trim them away; ordinary outer spaces and clinical multiline statement behavior remain unchanged.

**Limits:** This is form-level hardening, not a general Unicode, service, database or secrecy guarantee; unchanged empty extra component rows are skipped. See ADR 0133.

## 2026-11-24 — synthetic identity deadlock test coordination

**Changes:** The selected identity deadlock probe now coordinates from the actual lock holder and uses longer bounded waits while still requiring SQLSTATE `40P01`.

**Limits:** A prior full-suite run failed with a lock timeout; the exact scheduling cause was not established, and this is not a proof of determinism. See ADR 0132.

## 2026-11-24 — unknown source and clinical status labels

**Changes:** Selected source and clinical queues and related-source hints distinguish unknown non-null reviews from no review.

**Limits:** This does not validate history, prevent writes or establish source rights or clinical approval; nulls and other paths remain outside the check. See ADR 0131.

## 2026-11-24 — unknown candidate status labels

**Changes:** Selected product and price queues and review histories show a fixed invalid label instead of mapping an unknown status to a normal one.

**Limits:** This is defensive display for selected constraint-bypass cases, not history validation or repair; null latest decisions and other domains remain ambiguous. See ADR 0130.

## 2026-11-24 — candidate queue consistency display

**Changes:** Private product and price queues check each displayed candidate and replace inconsistent identity fields with a warning, retaining the ID, link and historical status.

**Limits:** This adds per-row validation but does not bound fetched JSON, verify authenticity or hide all metadata and history. See ADR 0129.

## 2026-11-24 — suppress inconsistent detail values

**Changes:** Private product and price detail pages replace selected identity and amount panels with a warning when candidate consistency checks fail; review gating remains independent.

**Limits:** Other pages, metadata, histories and logs can still contain untrusted values. Consistency is neither authenticity nor approval, and reads are not snapshots. See ADR 0128.

## 2026-11-24 — bounded catalog-quality projection fetch

**Changes:** The quality inspector selects a bounded search projection and flags oversized rows with unknown public-filter status instead of transferring the whole value.

**Limits:** This adds an issue code and suppresses other quality conclusions for such rows; database work and omitted-suffix controls remain unchecked. See ADR 0127.

## 2026-11-24 — bounded synthetic repair projection fetch

**Changes:** Synthetic projection-repair preview and locked commit select at most 8193 characters of the stored search projection; an oversized projection remains unsafe. Safe-length snapshots retain the complete text.

**Limits:** This bounds returned text, not database work or other readers, and does not authorize repair of real data. See ADR 0126.

## 2026-11-24 — public detail ID type

**Changes:** The direct public-detail service rejects non-integer and out-of-range IDs before database access, using the existing generic not-found response.

**Limits:** Direct callers passing coercible values must change; HTTP integer routes are unchanged. This is not authorization or source verification. See ADR 0125.

## 2026-11-24 — reject controls in retained search queries

**Changes:** Search rejects Unicode controls and surrogates in the retained query before cursor validation or database access, with a generic no-echo error.

**Limits:** This tightens existing behavior. Edge whitespace stripped by HTTP views and content beyond the prefix are not checked; logs and Unicode spoofing remain concerns. See ADR 0124.

## 2026-11-24 — defer internal projections on public reads

**Changes:** Search and detail reads avoid selecting two unused stored projection columns; the search still uses and rechecks its projection. Synthetic tests cover selected HTML, JSON and SQL paths.

**Limits:** The database still searches the text, and direct service callers accessing deferred fields make additional, potentially later-state queries. This is not a capacity guarantee; see ADR 0123.

## 2026-11-24 — publication/date database constraint

**Changes:** The catalog migration adds a check that a presentation marked published has a non-null verification date. Synthetic tests cover direct write rejection, legacy migration failure without rewrites and one DDL lock timeout.

**Limits:** Existing invalid rows make migration fail; no date or publication is automatically repaired. The date is not verification evidence or clinical approval; deployment and recovery require separate review. See ADR 0122.

## 2026-11-24 — baseline content-security policy

**Changes:** Django responses receive a same-origin CSP baseline; synthetic Chromium checks selected blocked inline/off-origin behaviors and existing workflows. It intentionally leaves preview framing to existing environment-specific controls.

**Limits:** Same-origin script remains allowed, views and upstream infrastructure can set different headers, no reports are collected, and this is not a security assessment or deployment approval. See ADR 0121.

## 2026-11-24 — synthetic search index experiment

**Changes:** Added an opt-in 100,000-record synthetic PostgreSQL experiment comparing existing search and temporary trigram and ordering indexes, with selected warm search queries, four-client probes for one query, result checks and rollback-only updates.

**Limits:** No index is added to application migrations. Selected timings do not establish representative concurrency, deployment safety or production performance. See ADR 0120.

## 2026-11-24 — explicit intake commit mode

**Changes:** Product and price intake services require an actual boolean for `commit`, before reading a file or writing. The synthetic projection-repair command also rejects non-boolean programmatic flags before any query. Synthetic tests cover selected non-boolean values, callbacks, preview and attested staging/repair.

**Limits:** This changes direct-call compatibility and does not replace source-rights verification or protect direct database writers. See ADR 0119.

## 2026-11-24 — raw controls at intake boundaries

**Changes:** Product and price CSV parsers reject control/surrogate characters before cell trimming; price source validation and the two upload forms check raw source fields before controls can be erased. Synthetic direct and authenticated upload tests cover selected no-write paths.

**Limits:** Ordinary spaces still trim, this intentionally rejects formerly accepted input, and other forms/writers and Unicode spoofing remain out of scope. See ADR 0118.

## 2026-11-24 — reject hidden characters in price amounts

**Changes:** Price amount conversion rejects selected Unicode controls, format characters, marks and line separators before normalization; CSV checks the raw cell before trimming. Synthetic direct, atomic CSV, legacy integrity and Unicode-category tests cover selected cases.

**Limits:** Some formerly accepted legacy candidates will require review; compatibility digits and ordinary outer spaces remain supported. This is not complete Unicode, source or financial validation. See ADR 0117.

## 2026-11-24 — synthetic encrypted restore probe

**Changes:** Added an opt-in OpenSSL CMS envelope, detached synthetic signature and isolated PostgreSQL restore exercise with selected tamper, wrong-key, replacement-archive and replay controls; CI opts in.

**Limits:** Ephemeral keys and intermediate archives are plaintext locally; encryption alone does not authenticate the backup creator, and the test signature lacks trusted key distribution and replay protection. No production backup, key-management or off-host policy is implemented; see ADR 0116.

## 2026-11-24 — synthetic public-read role probe

**Changes:** A disposable PostgreSQL test exercises anonymous presentation pages and APIs under selected restricted-role grants and verifies several denied operations.

**Limits:** Table-wide SELECT still exposes unpublished rows to direct SQL; the test is not an authenticated role, deployment configuration or complete privilege assessment. See ADR 0115.

## 2026-11-24 — isolated test teardown name guard

**Changes:** The isolated test backend records a successful CREATE on the creation instance and allows a single teardown attempt only for that exact name. A real synthetic canary and mocked failed-DROP tests cover selected refusal paths.

**Limits:** The record is not ownership or database identity, and replacement before DROP remains possible. Crashes and failures may leave databases behind; see ADR 0114.

## 2026-11-24 — historical migration failure and lock evidence

**Changes:** Four historical catalog migration tests register schema restoration before setup can fail; synthetic injected failures verify restoration is attempted before Django flush. Presentation projection migration tests also cover selected old rows, transactional failure and a two-connection lock conflict. One-off 5,000-row probes counted per-row updates for both projection backfills.

**Limits:** Cleanup can fail or be interrupted; these selected synthetic checks and timings do not establish safe production deployment, recovery or performance. See ADRs 0112 and 0113.

## 2026-11-24 — selected legacy-data migration tests

**Changes:** PostgreSQL migration tests verify selected old receipt summaries and clinical draft/review fixtures survive existing additive migrations without invented manifest or reference rows; selected new constraints reject invalid values.

**Limits:** This is synthetic sampled evidence, not a production migration or rollback plan. See ADR 0111.

## 2026-11-24 — PostgreSQL session-access clues

**Changes:** Added a development-only, one-statement aggregate inspection of selected current/session-role attributes, current-role table-level privileges, RLS flags and server-observed transport. Synthetic restricted-role and RLS-bypass tests cover selected limits.

**Limits:** It reports facts, not a security pass or production authorization; column grants, role escalation paths, policies and end-to-end transport remain outside scope. See ADR 0110.

## 2026-11-24 — isolated PostgreSQL test-database collision guard

**Changes:** The synthetic, browser and restore test settings use a PostgreSQL test-creation backend that fails on a colliding name without dropping or reusing the pre-existing database. Real synthetic canaries cover all three settings with and without `--noinput`.

**Limits:** Only initial test-database creation is guarded. Normal teardown, privileged writers, interruptions, shared cluster resources and default settings remain separate risks; use a disposable authorized cluster. See ADR 0109.

## 2026-11-24 — direct price-conversion bound

**Changes:** The direct amount helper enforces the existing 50-character input limit and uses exact digit-string arithmetic independent of decimal context; selected oversized and 3,000 synthetic compatibility-digit cases are tested.

**Limits:** The CSV parser already imposed its own limit; the direct-helper change is not evidence of a CSV exploit or a price-approval mechanism. See ADR 0108.

## 2026-11-24 — projection length boundary coverage

**Changes:** Added synthetic tests for normalization expanding a short IRC to the exact or over-limit 80-character derived column, including full/partial rejection and explicit correction of a bypassed row. Corrected the API privacy documentation to include known-path early redirects.

**Limits:** This tests existing model validation, not arbitrary bulk/SQL writes or every Unicode normalization case. Redirect headers do not redact queries or control upstream proxies.

## 2026-11-24 — partial presentation validation

**Changes:** Nonempty partial presentation saves validate the prospective combination of locked stored fields and explicitly updated values, closing stale-state publication/date mismatches; synthetic two-connection and unit tests cover selected cases.

**Limits:** Bulk and SQL writes bypass this validation, full saves can overwrite newer values, and signal instances can still carry stale omitted fields. See ADR 0107.

## 2026-11-24 — architecture decision index

**Changes:** Restored 22 missing decision links and sorted the index; an offline test now checks coverage, uniqueness and order.

**Limits:** The test checks index entries, not the correctness or currency of each decision.

## 2026-11-24 — selected check expression reuse

**Changes:** The one-statement inspector reuses a materialized set of selected named-check expressions for its exact constant counts; a mixed-constraint test checks aggregate outcomes.

**Limits:** Materialization costs vary; expression coverage and privacy boundaries are unchanged. See ADR 0106.

## 2026-11-24 — selected constant-false check clues

**Changes:** The inspector flags exact deparsed false expressions on selected named model checks; a synthetic test confirms an otherwise valid insert is rejected.

**Limits:** Equivalent always-false expressions can remain undetected, and intentionally false checks can be flagged; see ADR 0105.

## 2026-11-24 — selected constant check clues

**Changes:** The PostgreSQL inspector flags exact deparsed true/null expressions on selected named model checks; synthetic tests demonstrate rows that those checks allow.

**Limits:** Other tautologies and unexpected checks remain outside this narrow test; it is not full expression comparison or data validation. See ADR 0104.

## 2026-11-24 — selected auto-sequence settings

**Changes:** The single-statement PostgreSQL development inspector flags selected owned auto sequences with nonpositive increment, minimum below one or cycling enabled. Synthetic tests include a sequence that reissues a value and a rewound-value negative control.

**Limits:** Intentional settings may be flagged; current values, data alignment and future insert success are not proven. See ADR 0103.

## 2026-11-24 — synthetic backup argument guards

**Changes:** The synthetic backup guide rejects non-absolute archive paths and libpq connection-string-like source database names before invoking client commands; restore operands use an option terminator. Offline guards and a disposable PostgreSQL restore probe cover selected paths.

**Limits:** It cannot verify server identity, a trusted filesystem or inherited environment and intentionally accepts only simple ASCII database names; see ADR 0102.

## 2026-11-24 — PostgreSQL trigger session clues

**Changes:** The single-statement development schema inspector flags replica session mode and selected trigger enabled modes that do not fire in that session, in addition to disabled triggers. Synthetic tests demonstrate an origin-mode replica-only trigger and a replica-mode foreign-key bypass.

**Limits:** A trigger mode mismatch may be intentional and the result covers only the inspecting session and selected tables; no repair or production certification is implied. See ADR 0101.

## 2026-11-24 — manifest header consistency

**Changes:** Validate selected version-1 receipt header totals, domain limits and suggestion counts before aggregating manifest rows; invalid headers stop row inspection, while legacy receipts stay legacy.

**Limits:** Selected consistency only; the check is not a snapshot, provenance proof or schema repair. See ADR 0100.

## 2026-11-24 — manifest ordinal distinctness

**Changes:** Manifest structural checks now count distinct ordinals, detecting gaps masked by duplicate positions even if a uniqueness constraint is missing or bypassed. Product and price detail and inspection stop displaying structurally inconsistent rows.

**Limits:** This adds aggregate database work and is neither schema repair nor a snapshot or proof of provenance; see ADR 0099.

## 2026-11-24 — selected failed-restore relation counts

**Changes:** The synthetic restore drill compares selected target `public` relation-kind counts before and after a failed truncated restore; target-only canaries test detection and the equal-count replacement blind spot.

**Limits:** Equal counts do not establish schema equivalence, and objects outside the selected relation kinds are not covered. See ADR 0098.

## 2026-11-24 — price staging replay integrity

**Changes:** Committed price staging locks and checks duplicate candidates and derived price fields before recording them, with rollback on conflict. Actorless CLI candidates remain replayable and the original suggestion remains unchanged.

**Limits:** Per-duplicate checks add work and locks; a null recorder has no provenance proof and source rights or prices are not verified. See ADR 0097.

## 2026-11-24 — product staging replay integrity

**Changes:** Committed product staging locks and checks duplicate candidates before counting them or recording receipt items; unsafe replays roll back the stage and return a conflict. Synthetic PostgreSQL tests include integrity failures and concurrent row updates.

**Limits:** Locks and account checks add per-duplicate work; rights and authenticity are not verified, and price staging is unchanged. See ADR 0096.

## 2026-11-24 — source-claim replay integrity

**Changes:** Duplicate source-claim replays lock and re-read the existing row, checking its current payload, exact submitted fields and recorder existence; unsafe replay returns a private conflict. PostgreSQL concurrency tests cover timeout, outer lock lifetime and a mutation between lookup and locked read.

**Limits:** Recorder identity and rights are not proven, later writes remain possible, and outer-transaction failures are outside the local boundary. See ADR 0095.

## 2026-11-24 — PostgreSQL legacy serial-default clue

**Changes:** Selected legacy serial defaults are compared to a canonical `nextval` expression for their owned sequence, rejecting selected wrong defaults and a shadowed custom function.

**Limits:** Equivalent noncanonical expressions can be flagged; function safety and sequence state are not proven. See ADR 0094.

## 2026-11-24 — PostgreSQL auto-field generation clues

**Changes:** The read-only inspector checks selected model and recorder auto fields for an owned sequence and supported identity or legacy-default clues; synthetic DDL covers missing/always identity, missing ownership and missing default.

**Limits:** The legacy default expression and current sequence value are not verified; a wrong default can pass. See ADR 0093.

## 2026-11-24 — PostgreSQL migration-recorder primary-key clue

**Changes:** The catalog inspector checks selected primary-key index properties for Django's migration recorder; a synthetic DDL test removes the key and substitutes a standalone unique index.

**Limits:** The primary-key physical type remains skipped, and sequence, defaults and migration records are not verified. See ADR 0092.

## 2026-11-24 — fail-stop synthetic backup example

**Changes:** The manual synthetic backup example chains all stages so a failed target creation cannot be followed by a restore. Offline fake-command tests exercise each failure; a separate PostgreSQL 16 synthetic-cluster probe checks target collision and a successful restore.

**Limits:** This is not an atomic, encrypted or production backup tool and relies on running the entire block against a disposable cluster. See ADR 0091.

## 2026-11-24 — optimization-safe synthetic restore checks

**Changes:** The opt-in synthetic restore fixture and identity-graph verification use explicit checks instead of Python assertions, so optimization cannot erase them. PostgreSQL tests verify valid and deliberately corrupted fixtures under `python -O`.

**Limits:** Only selected fixture checks and corruptions are exercised; this does not prove recovery of production backups. See ADR 0090.

## 2026-11-24 — PostgreSQL migration-recorder column clues

**Changes:** The inspector checks recorder-column presence, nullability and supported non-primary types. PostgreSQL tests remove each recorder column and alter selected nullability and types in rolled-back transactions.

**Limits:** The recorder primary-key type is skipped and counted; key constraint, sequence and migration-history content remain unchecked. See ADR 0089.

## 2026-11-24 — PostgreSQL unique-key operator and collation clues

**Changes:** Selected simple unique-key matches require B-tree, default operator-class flags and index collations matching their current columns. Rolled-back PostgreSQL tests cover discrepancies on both keys of a composite index.

**Limits:** A default flag is not an exact operator-class comparison; column collation versus model intent and full definitions remain unchecked. See ADR 0088.

## 2026-11-24 — PostgreSQL unique-key enforcement timing

**Changes:** Selected simple uniqueness matches must be enforced immediately; synthetic DDL tests cover deferrable constraints in both initial modes.

**Limits:** A standalone immediate unique index still matches and full constraint equivalence remains unchecked. See ADR 0087.

## 2026-11-24 — unsupported unique declarations

**Changes:** The read-only schema inspector reports unsupported managed-model unique declarations as an aggregate attention count instead of silently omitting them. Synthetic metadata tests cover conditions, expressions, include, operator classes, explicit null semantics, deferrability and subclasses.

**Limits:** This is a model-metadata coverage clue, not a comparison of those definitions or full schema equivalence. See ADR 0086.

## 2026-11-24 — PostgreSQL selected unique-key null semantics

**Changes:** The inspector flags `NULLS NOT DISTINCT` substitutes for selected model unique keys expecting PostgreSQL's default semantics; a synthetic PostgreSQL 16 DDL test exercises the discrepancy.

**Limits:** Explicit model null-semantics declarations and full uniqueness equivalence are not covered; other PostgreSQL versions are not tested. See ADR 0085.

## 2026-11-24 — PostgreSQL named-index collation and included-column clues

**Changes:** Supported simple named indexes are checked for index-versus-column collation mismatch and additional included columns; synthetic DDL tests cover both.

**Limits:** Column collation is not compared with model intent; exact operator class, storage options, plans and full definitions remain unchecked. See ADR 0084.

## 2026-11-24 — PostgreSQL named-index operator-class clues

**Changes:** The inspector flags supported named B-tree indexes whose key operator classes are not marked default; synthetic DDL tests include a nondefault pattern operator class.

**Limits:** This is not an exact operator-class comparison. Collation and complete definitions remain unchecked, and useful alternatives can be flagged. See ADR 0083.

## 2026-11-24 — PostgreSQL named-index null-order clues

**Changes:** The catalog inspector checks supported named index keys for the PostgreSQL default null order corresponding to each model-declared direction; synthetic DDL tests cover both ascending and descending mismatches.

**Limits:** Operator class, collation, performance and full definitions remain unchecked, and equivalent alternatives can be flagged. See ADR 0082.

## 2026-11-24 — PostgreSQL named-index direction clues

**Changes:** The read-only inspector compares each supported named index key's ascending or descending direction with the model declaration. Rolled-back PostgreSQL tests exercise mismatches on both keys of a two-key index.

**Limits:** Direction is only a conservative clue, not a plan or performance guarantee; null ordering, collation, operator class and full definitions remain unchecked. See ADR 0081.

## 2026-11-24 — PostgreSQL model-index presence clues

**Changes:** The catalog inspector checks selected field-index coverage and named model B-tree indexes against the current metadata, reporting unsupported named definitions as attention. Rolled-back PostgreSQL tests cover missing, partial, hash, reordered and alternate indexes.

**Limits:** Sort direction, operator class, collation, complete schema definitions and query performance are not verified; a useful alternative can be flagged. See ADR 0080.

## 2026-11-24 — synthetic post-restore sequence probes

**Changes:** The disposable PostgreSQL restore drill exercises new service writes across selected domains and checks generated IDs advance beyond restored records. A negative control rewinds one target-only synthetic sequence, detects an integrity failure, then resets it for a successful probe.

**Limits:** This is not a general sequence-repair recipe or proof that every sequence, backup or production workflow is safe. The modified target is disposable; see ADR 0079.

## 2026-11-24 — PostgreSQL managed-column type clues

**Changes:** Catalog inspection compares selected managed field types, including varchar length and numeric precision, against PostgreSQL. Unsupported types cause an incomplete/attention result. Synthetic rolled-back DDL exercises varchar, numeric and timestamp mismatches.

**Limits:** Auto-created many-to-many primary-key types are skipped and counted because runtime metadata and historical migrations differ; defaults, collations, generation, sequence state and complete schema equivalence are not checked. See ADR 0078.

## 2026-11-23 — cross-domain synthetic restore drill

**Changes:** The opt-in PostgreSQL restore drill now also restores and verifies selected synthetic source, product, price, receipt and clinical records and relationships, and runs the read-only catalog inspector on the restored database. A corruption probe checks that altered manifest and evidence snapshots are detected; additional fixture guards run before writes.

**Limits:** This sample does not prove complete restoration, provenance, encrypted/off-host backups, recovery time or production safety; see ADR 0077.

## 2026-11-23 — PostgreSQL readiness retry window

**Changes:** The development startup helper no longer starts a new readiness attempt after its monotonic retry window ends; it still performs one initial attempt even for a zero window. Deterministic clock tests and actual synthetic PostgreSQL success/absence tests cover the selected behavior.

**Limits:** This is not a hard wall-clock timeout or query cancellation; a connection, query or DNS operation already in progress can overrun it. See ADR 0076.

## 2026-11-23 — PostgreSQL managed-column clues

**Changes:** The development catalog inspection counts missing managed-model columns and differences in PostgreSQL nullability versus current model metadata. Synthetic rolled-back DDL tests cover a missing column and changes in both nullability directions.

**Limits:** It does not compare column types or defaults; a type change with the same name and nullability passes. It does not establish schema equivalence or production safety; see ADR 0075.

## 2026-11-23 — PostgreSQL named-check clues

**Changes:** Catalog inspection now reports missing explicitly named model check constraints and wrong constraint types; unvalidated checks remain separately flagged. Synthetic rolled-back PostgreSQL DDL exercises each case.

**Limits at that point:** The check compared name and type only. ADR 0104 later added exact true/null clues, but other tautologies still pass and an equivalent check under another name is flagged. It does not validate data, compare migrations or certify production safety; see ADR 0074.

## 2026-11-23 — PostgreSQL unique-key clues

**Changes:** The development-only catalog inspection flags missing selected simple model-declared unique and primary-key indexes, ignoring nonunique, partial, invalid or wrong-column indexes. Rolled-back PostgreSQL tests exercise composite keys, partial indexes and primary-key loss.

**Limits:** Order-sensitive clues can flag a logically equivalent reordered key; null semantics and other properties are not compared. This is not migration equivalence, data validation or production readiness; see ADR 0073.

## 2026-11-23 — PostgreSQL foreign-key behavior clues

**Changes:** The read-only catalog inspection now also counts matching expected foreign keys that depart from the current Django/PostgreSQL deferred and `NO ACTION` conventions, including unexpected duplicate immediate or cascading constraints. Selected PostgreSQL DDL tests verify these cases with rolled-back synthetic data.

**Limits:** This compares current model-declared pairs and observed catalog attributes, not complete migrations or ORM deletion behavior. It does not repair or certify the database; see ADR 0072.

## 2026-11-23 — isolated general PostgreSQL test databases

**Changes:** Opt-in general synthetic test settings assign a fresh random test database per invocation and reject reuse and Django parallel mode; CI uses them for the ordinary suite. A local two-process probe verified distinct databases and passing PostgreSQL catalog tests.

**Limits:** This is probabilistic name isolation on an already disposable cluster, not a production safeguard; abrupt termination can leave orphaned databases. A previous overlapping run against the shared default database failed when one process removed it; see ADR 0071.

## 2026-11-23 — PostgreSQL catalog clues

**Changes:** A development-only, read-only command reports aggregate counts of unresolved managed tables, non-table relations, missing model-declared single-column managed-table foreign keys, unvalidated constraints, unusable index states and disabled triggers. Synthetic PostgreSQL tests create actual selected defects, including a failed concurrent index build and a missing or wrong-target foreign key; CI runs the command after migrations.

**Limits:** It does not compare complete schema definitions with migrations, detect missing non-FK constraints or indexes, validate application data or certify backups, security or production readiness. Only scoped resolved tables are examined; see ADR 0070.

## 2026-11-23 — product detail consistency gate

**Changes:** Product detail reuses its existing candidate comparison availability to suppress the review form and show a warning when the observed candidate payload or derived identity is inconsistent. Tests cover changed payloads, stale and invalid submissions, coherent rewrites and a selected non-snapshot race; write-side validation remains independent.

**Limits:** Raw fields and history remain visible to authorized staff. This is not authenticity, legal authorization, confidentiality or snapshot isolation; see ADR 0069.

## 2026-11-23 — source detail review comparisons

**Changes:** Source detail checks up to 25 displayed review snapshots and reports limited comparisons to the observed claim, suppressing review details if the current claim or historical review is inconsistent, or the reviewer account is missing. The latest-review token and write-side behavior remain unchanged. Tests exercise a selected stale-read race and successful fresh review after a corrupt historical row.

**Limits:** Separate reads are not a snapshot and coherent alteration may pass. Raw current claim data remains visible to authorized staff. No source rights, authenticity, reviewer qualification, chronological cause or history completeness is established; see ADR 0068.

## 2026-11-23 — source review snapshot inspection

**Changes:** Authorized development staff can scan up to 50 source-review records per section for structural and payload consistency without displaying snapshot content, reasons, accounts, or hashes. Filters operate within the scanned section and malformed inputs receive private non-reflecting recovery. Synthetic database and Chromium checks cover permissions, bounded pagination, keyboard access, and non-snapshot behavior.

**Limits:** Coherent rewrites can pass; this is not an authenticity, source-rights, account-existence, qualification or completeness check. Reads are not a snapshot; see ADR 0067.

## 2026-11-23 — source claim creation conflict handling

**Changes:** Source-claim creation translates selected PostgreSQL write conflicts after rollback, and the staff form returns a private HTTP 409 rather than a raw database failure. Tests include a real unique-insert lock timeout at the service and HTTP boundaries, plus simulated selected failures after insertion and explicit replay preserving the original recorder.

**Limits:** No automatic retry, source authorization, production guarantee or outer-commit handling is added. Real deadlock and serialization failures on this path were not reproduced; see ADR 0066.

## 2026-11-23 — price detail consistency gate

**Changes:** A staff price detail now checks the staged payload before computing its current suggestion; an inconsistent payload shows a warning and suppresses that suggestion and new review form. A stale POST still fails at the existing write-side check. Queue and detail candidate queries no longer join an unused stored suggestion. Synthetic regressions cover changed amount, fields, hash and URL, conflict responses and SQL joins.

**Limits:** Raw fields and review history can remain visible to authorized staff. Consistency is not authenticity or confidentiality, the queue does not run this check, and reads are not snapshots; see ADR 0065.

## 2026-11-23 — unsafe presentation text in price matching

**Changes:** Price matching marks an identity ambiguous when a matching presentation has invalid matching text or an unsafe displayed Persian name, rather than ignoring it or suggesting it. An unassignable non-string matching field makes its IRC group ambiguous. Staging, fresh suggestions and acceptance use the shared check; stored history is unchanged. Synthetic tests cover all fields, duplicate conservatism, receipts and acceptance.

**Limits:** This is a narrow text check, not product verification, spoofing protection or uniqueness under concurrent writes. Unpublished rows may still be suggested; see ADR 0064.

## 2026-11-23 — projection repair conflict handling

**Changes:** The default-database synthetic projection writer now translates three selected PostgreSQL concurrency failures after rollback into its existing domain error; the CLI reports its generic failure. Tests exercise a real lock timeout at service and command boundaries and simulated selected failures after an update.

**Limits:** There is no automatic retry. Real deadlocks and serialization failures in this path, surrounding-transaction commits and production operation are not established; see ADR 0063.

## 2026-11-23 — price candidate CLI consistency check

**Changes:** The local listing now checks stored price payload/derived values before emitting full fields or computing a current suggestion. Inconsistent rows receive a reduced JSON shape and `payload_status: invalid`; consistent rows receive `payload_status: consistent`. The stored-status filter and row limit are unchanged. Synthetic tests cover malformed and altered payloads, filtering and coherent recomputation.

**Limits:** This is not a confidentiality, authenticity, source-rights or review-eligibility check; coherent alteration and sensitive content can still pass. Local CLI access is not controlled by web authorization. See ADR 0062.

## 2026-11-23 — identity lineage cursor depth bound

**Changes:** Identity-lineage continuation rejects a signed depth greater than the positive ID gap between anchor and current record. Synthetic tests reproduce the previously accepted impossible depth, verify a private error and check all four identity kinds.

**Limits:** This necessary arithmetic bound does not prove that any skipped links existed or remain unchanged. Signing-key holders can still produce plausible cursors; see ADR 0061.

## 2026-11-23 — clinical scan guide correction

**Changes:** Corrected the development guide's clinical scan sequence, author-presence precedence and maximum four service SELECTs to match ADR 0056 and the existing implementation. The prior guide text was stale; no application behavior changed.

## 2026-11-23 — inactive-user backend login edge

**Changes:** If an authentication backend returns an inactive user, the staff form now clears its cached identity and returns the same generic invalid-login error as bad credentials. Synthetic tests override the backend to exercise this path, session behavior and independent destination permissions.

**Limits:** The default backend already rejects inactive users, and no HTTP login bypass was demonstrated. Custom backends and production authentication still need independent review; this adds no MFA or throttling. See ADR 0060.

## 2026-11-23 — synthetic stream and time-window regression coverage

**Changes:** CSV tests compare fragmented reads and replay manifest membership across multiple chunk sizes and invalid tails. A seeded, independent UTC-window enumeration checks returned plans across ten time zones and selected transition dates; a larger 50,000-sample local probe found no returned-plan mismatch.

**Limits:** These sampled synthetic tests do not prove complete timezone coverage, inspect cases the implementation rejects, establish source rights or operate a scheduler; local tzdata determines the rules tested.

## 2026-11-23 — skip-link viewport failure diagnostics

**Changes:** A failed skip-link visibility assertion's allowlisted CI annotation now identifies affected viewport sides and coarse overflow distances, without copying geometry or arbitrary diagnostic text. Reduced-motion CSS now uses zero transition/animation duration instead of inadvertently introducing a 0.01ms transition even on the previously non-transitioning skip link. Chromium checks the computed timings and rejects a nonzero-duration mutation.

**Limits:** CI run 45263717417 failed forced-colors home visibility with an element outside the viewport; its log download returned EOF and GitHub rejected the rerun. The failure's side and cause remain unknown; this CSS correction and diagnostic are not proven to resolve it or to establish accessibility.

## 2026-11-23 — bounded CSV short-read handling

**Changes:** Both synthetic CSV parsers now join ordinary short reads up to EOF or one byte beyond the existing size cap before validating any rows. A reproduced prefix-acceptance bug could otherwise stage a partial file; tests check valid and invalid tails, no partial receipt, byte and call limits, HTTP and CLI read failures.

**Limits:** EOF is trusted, reads can block and callers with exceptionally fragmented streams may hit the read-call cap. This is not file provenance, source authorization or a production availability guarantee; see ADR 0059.

## 2026-11-23 — ID-only account existence reads

**Changes:** Source and clinical queue presence checks and both account checks in the clinical technical scan now select only account IDs, rather than full account objects. Tests cover invalid/duplicate IDs, inactive users, alias forwarding, query columns and the existing bounds.

**Limits:** This applies only to selected existence reads; authentication, display and other workflows may still fetch account attributes, and IDs may be logged. Existence is not identity, qualification or authorization, and the separate reads are not a snapshot; see ADR 0058.

## 2026-11-23 — source queue recorder-presence clue

**Changes:** The source queue now uses a single page-local account lookup and flags currently missing recorders while retaining the claim and independent date status. Synthetic tests cover privacy, inactive accounts, page bounds, the empty result and separate reads; Chromium exercises the explanatory text.

**Limits:** Existence is not identity, activity, authorization or source-rights verification, and the unlocked reads do not form a snapshot. Date inspection retains its separate behavior. See ADR 0057.

## 2026-11-23 — clinical inspection author-presence clue

**Changes:** The bounded clinical scan now reports a separate current-author-missing status before checking supplementary references. A page-local account lookup adds at most one SELECT, and the private page offers a filter and explains the limited check. Synthetic tests cover precedence, account absence, pagination, privacy and the unexamined parent author.

**Limits:** Account existence is not activity, identity or qualification; reads are separate and non-snapshot, and parent authors and reviews remain unchecked. This is not clinical approval; see ADR 0056.

## 2026-11-23 — selected CSV staging conflict handling

**Changes:** Product/price staging and their receipt transactions translate selected PostgreSQL concurrency failures after rollback. Uploads return a private 409 and ask for the file to be selected again; the price CLI reports a command error. Synthetic tests cover actual advisory-lock timeouts and simulated candidate/manifest rollback.

**Limits:** No timeout, automatic retry, source verification or publication is introduced. Unknown errors, connection loss and later enclosing-transaction commits remain outside the guarantee; see ADR 0055.

## 2026-11-23 — clinical draft and reference write conflict handling

**Changes:** Clinical draft creation/revision and supplementary-reference creation translate selected PostgreSQL concurrency failures after rollback; initial draft creation now also returns a private generic 409. Synthetic tests cover actual lock timeouts for revision/reference and simulated errors, rollback and HTTP responses for all three forms.

**Limits:** No timeout or retry is configured; enclosing-transaction commit, pre-write reads and unrelated errors remain outside scope. Deadlock and serialization tests for these writers are simulated; see ADR 0054.

## 2026-11-23 — selected header action accessibility checks

**Changes:** The header search action has an opaque background. Chromium checks its label and decorative arrow against the selected background at rest and on hover in four widths, rejects selected low-contrast/compositing mutations, and follows the accessible link using a real keyboard sequence.

**Limits:** These are computed-style and selected keyboard checks, not pixel rendering, a screen-reader test or an accessibility certification. Axe still reports the decorative arrow as inconclusive; manual review remains necessary.

## 2026-11-23 — selected triage write conflict handling

**Changes:** The four preliminary review writers translate selected PostgreSQL lock/deadlock/serialization errors into their existing conflict responses after transaction/savepoint rollback; synthetic tests cover rollback and private HTTP 409 responses, with real lock-timeout races across all four domains.

**Limits:** No timeout or retry is configured; a failure at an enclosing transaction's later commit and other services/errors remain outside the boundary. Deadlock and serialization are exercised on PostgreSQL for the source writer and simulated for the other three; see ADR 0053.

## 2026-11-23 — selected product-candidate latest-review lock

**Changes:** Product triage locks its latest existing review while comparing the prior ID. Synthetic PostgreSQL tests cover selected competing writers, transaction boundaries and deferred insertion; the private detail page describes history limitations.

**Limits:** Only the latest existing row and its ID are involved; prior content is not checked, deferred insertion and later bypass remain possible, and additional locks may wait or deadlock. No retry, approval or publication is added; see ADR 0052.

## 2026-11-23 — selected price latest-review lock

**Changes:** Price triage locks its latest existing review while comparing the prior ID. Synthetic PostgreSQL tests cover selected competing writers, transaction boundaries, deferred insertion and the acceptance path holding the existing product lock; the private page describes history limits.

**Limits:** Only the latest existing row and its ID are involved; prior content is not checked, deferred insertion and later bypass remain possible, product matching is not a uniqueness guarantee, and added locks may wait or deadlock. No retry, approval or publication is added; see ADR 0051.

## 2026-11-23 — selected source latest-review lock

**Changes:** Source triage locks its latest existing review while comparing the prior ID. Synthetic PostgreSQL tests cover selected competing writers, transaction boundaries and deferred insertion, and the private detail page describes history limitations. A clinical test also checks a preceding update with unchanged ID.

**Limits:** Only the latest existing row and its ID are involved; prior content is not checked, deferred insertion and later bypass remain possible, and lock waits/deadlocks are possible. No retry, legal approval or source access is added; see ADR 0050.

## 2026-11-23 — selected clinical latest-review lock

**Changes:** Clinical triage locks the latest existing review row while checking its prior-ID token. Synthetic PostgreSQL tests cover competing updates/deletions, an earlier deletion, outer transaction lifetime and selected non-guarantees; the private page clarifies that this is not full history validation.

**Limits:** Only the latest existing row is locked, only its ID is checked, deferred bypass inserts and later changes remain possible, and additional locks may wait or deadlock. No retry or clinical approval is added; see ADR 0049.

## 2026-11-23 — development staff login policy

**Changes:** The development staff login form rejects authenticated nonstaff accounts using the same visible error as invalid credentials, without creating a new authenticated session. Staff with no domain permission can still sign in but are denied domain access; tests cover subsequent demotion and an existing session.

**Limits:** This only affects the staff form, not other authentication mechanisms or existing sessions. It does not add MFA, rate limiting, audit or production readiness. See ADR 0048.

## 2026-11-23 — stronger hero contrast test boundaries

**Changes:** Selected hero text and search-placeholder contrast checks run at four viewport widths and fail closed on selected opacity, filter, blend and background layers. Deliberate compositing and low-contrast mutations verify the checks.

**Limits:** This checks computed colors, not actual pixels, all overlays, states or accessibility criteria; other axe contrast results still need manual review.

## 2026-11-23 — oversized public product paths

**Changes:** Known public product URL shapes retain privacy headers when an extremely long numeric ID fails URL resolution, including HTTPS redirects. A synthetic test reproduced the previously missing headers before the fix.

**Limits:** This does not redact URLs from logs or govern unrelated or upstream-generated responses. See ADR 0044.

## 2026-11-23 — malformed signed cursor timestamps

**Changes:** The shared cursor decoder now maps Django's `IndexError` and `OverflowError` for validly signed empty or extreme timestamps to generic invalid-cursor errors. A synthetic test reproduced the previous public HTTP failure before the fix and now covers all four cursor decoders.

**Limits:** Generating these valid signatures requires the signing key; development's fallback key is public. This is not key management or a production security assessment. See ADR 0047.

## 2026-11-23 — in-flight search observation boundary

**Changes:** Coordinated synthetic PostgreSQL tests demonstrate that a name change or withdrawal committed after search fetch does not alter the already-fetched in-flight result. Subsequent reads reflect the change; API and architecture documentation now state this exposure window.

**Limits:** These tests characterize selected schedules, not a fix, immediate-withdrawal guarantee or proof of all concurrency behavior. See ADR 0046.

## 2026-11-23 — future-dated cursor rejection

**Changes:** Public search, catalog IRC inspection, identity lineage and clinical lineage now reject correctly signed cursors dated after the verifying host's clock, in addition to their existing maximum-age checks. Controlled-clock and synthetic HTTP tests cover the four consumers.

**Limits:** Clock skew or rollback can reject legitimate cursors; monitoring and synchronization are not implemented. Tokens remain signed, not encrypted. See ADR 0047.

## 2026-11-23 — current-field public search recheck

**Changes:** Before displaying a SQL search candidate, recheck that its fetched current normalized fields still contain the query. Synthetic tests cover stale positives and negatives, unchanged valid matches, Persian normalization and continuation after 150 stale hits.

**Limits:** Stale indexes can still hide matches; this does not repair data, offer a snapshot or prove identity or clinical correctness. See ADR 0046.

## 2026-11-23 — early HTTPS redirect privacy

**Changes:** A response-only middleware wraps Django's security middleware so its early HTTPS redirects receive the existing privacy headers for known public-read and staff paths. The HTTPS redirect and the disabled staff gate retain their order; synthetic tests cover both, methods, query retention and lookalikes.

**Limits:** Proxy-generated redirects, request logging and other paths remain outside scope; redirect locations retain queries. See ADR 0044.

## 2026-11-23 — public display control-character guard

**Changes:** Shared public presentation eligibility now rejects non-string display fields and Unicode control/surrogate characters, including in optional fields and source metadata. Synthetic bypass tests cover HTML and JSON search/detail; Persian zero-width non-joiners remain valid.

**Limits:** This does not repair records or establish identity, source authenticity, Unicode spoofing protection, clinical validity or production readiness. See ADR 0045.

## 2026-11-23 — slashless privacy boundaries

**Changes:** Known slashless search and product routes receive the public privacy headers even on Django's append-slash redirect; the staff root without a slash receives staff privacy headers and is blocked when the development portal is disabled. Exact path boundaries and redirect queries are tested.

**Limits:** Redirects retain query strings; upstream redirects, logging, proxies and other unresolved paths remain outside scope. See ADR 0044.

## 2026-11-23 — isolated synthetic restore drill

**Changes:** An opt-in PostgreSQL test creates separate random synthetic source and target databases, verifies archive creation, one failed truncated restore, a full restore, migration state and a synthetic identity graph. CI runs it with matching PostgreSQL 16 client commands in a container; the designated test runner refuses parsed reuse and parallel options for restore and browser exercises, including abbreviations. Explicit runner overrides bypass that guard.

**Limits:** This is not an encrypted/off-host backup, production recovery policy, complete-data verification or clinical assurance. Use a disposable cluster only; see ADR 0043.

## 2026-11-23 — skip-link diagnostic classification

**Changes:** Restore privacy-preserving CI classification of the structured skip-link visibility assertion; report only fixed failure categories, not the diagnostic JSON. Test malformed and injected input. A separate local 100-context forced-colors probe passed.

**Limits:** The earlier CI failure was not reproduced and its cause remains unknown; the probe is not a real-device accessibility test.

## 2026-11-23 — selected identity write concurrency errors

**Changes:** After rollback, selected private identity writer boundaries convert PostgreSQL lock-not-available, deadlock and serialization SQLSTATEs to a generic conflict; private HTTP writers return 409. Actual synthetic PostgreSQL timeout, deadlock and serialization tests cover selected schedules.

**Limits:** No timeout or automatic retry is configured; errors at a later outermost commit remain the caller's responsibility. The whole enclosing transaction must be abandoned/retried as appropriate after deadlock or serialization failure. See ADR 0042.

## 2026-11-23 — latest identity package review lock

**Changes:** Package review and correction now lock the latest existing review before their existing optimistic-token checks; correction still validates that row structurally. Synthetic PostgreSQL tests cover selected update, delete, outer-transaction, older-row and concurrent insertion cases.

**Limits:** This is not a history, absent-row or predicate lock; review creation still checks only the previous ID, and concurrent deferred inserts or later/same-transaction bypasses remain possible. See ADR 0041.

## 2026-11-22 — bounded identity component and ingredient locks

**Changes:** Selected identity dependent-creation, package-review and correction services now lock and re-read bounded existing component and ingredient rows after their applicable parent locks. Missing rows fail closed. Synthetic tests exercise both update directions across six writer paths, shared ingredients, outer transactions, bounded SQL and a deferred concurrent insertion.

**Limits:** New rows and later or same-transaction bypass mutations can still stale observations; locks are not gap locks or evidence of authenticity. Waiting/deadlocks remain possible without retry. See ADR 0040.

## 2026-11-22 — identity package formulation lock

**Changes:** Package review and correction now re-read and lock the product's formulation after the package/product locks. Missing formulations conflict. Synthetic tests cover selected contention in both directions, cached rows, missing FKs, outer transactions and still-unlocked component/ingredient changes; interface text describes the limits.

**Limits:** Ingredient/component rows and account identities remain outside this explicit lock, the reads are not a full snapshot, and a same-transaction bypass can add components. More locks can wait or deadlock; no retries or production/clinical guarantee. See ADR 0039.

## 2026-11-22 — identity package immediate-product lock

**Changes:** Package review and correction lock the package then re-read and lock its immediate product before evaluating the graph. Missing products conflict, and direct non-string review decisions now conflict rather than raising an unhashable-input type error. Synthetic PostgreSQL tests exercise both lock directions, cached reads, outer transactions, missing products, validation and an unlocked formulation mutation; Chromium checks the new scope notice.

**Limits:** This is not whole-graph isolation: formulation, ingredients, components and exclusive account locks are outside this change. More locks can wait or deadlock; no retries, clinical approval or production guarantee. See ADR 0038.

## 2026-11-22 — identity graph creator presence in writes

**Changes:** Selected identity dependent creation, package review and correction writers now reject a missing current creator anywhere in their validated current graph, with one bounded bulk account read per check. Tests cover every graph position with temporary deferred-FK account deletion, independent permissions and self-review, conflicts and rollback, inactive accounts, maximum graph size and selected unlocked/bypass behavior.

**Limits:** Structural views and lineage remain account-independent; creator accounts are not locked or authenticated, correction ancestor/link actors are not checked, and graph reads are not a snapshot. See ADR 0037.

## 2026-11-22 — identity package review account display

**Changes:** Identity package history and correction pages retain reviews but suppress details when the current reviewer account is missing, using a bounded page-local lookup. Cursor positions and real latest-review versions remain intact; missing prior accounts alone do not block later review or correction. Identity workspace and lineage pages explicitly warn that graph/link creator existence is not checked. Synthetic tests cover permissions, missing reviewers, pagination, fresh/stale submissions, account/graph boundaries and stale reads.

**Limits:** Separate reads are not a snapshot and an existing account does not establish historical identity, reviewer qualification or graph validity. Graph creator existence is still not enforced; see ADR 0036.

## 2026-11-22 — missing receipt actor accounts

**Changes:** Permission-scoped receipt lists and details retain receipts with a missing current actor and show a notice, with one page-local account lookup rather than an inner join. Related-receipt and manifest-inspection pages state that they do not check receipt actors. Synthetic tests cover orphaned product/price receipts, privacy and domain permissions, legacy data, pagination/query counts and stale reads; Chromium exercises ordinary pages at four widths.

**Limits:** An account name is not historical identity or authorization, and separate reads are not a snapshot. Receipt actor changes, other relationships, authenticity and production use are not guaranteed; see ADR 0035.

## 2026-11-22 — missing product and price stager accounts

**Changes:** Product and price review now conflict if the current stager account is missing. Orphaned products remain visible, both details show a notice and disable review, and nullable price stagers retain their separate handling. Comparisons and receipt inspections explicitly describe their narrower checks. Synthetic tests exercise service and HTTP paths, all decisions, nullable and inactive accounts, diagnostic boundaries and selected bypass/race limitations.

**Limits:** Existence is not attribution or authorization and accounts are not locked; receipt actors and other relationships are outside this change. See ADR 0034.

## 2026-11-22 — missing source and clinical creator accounts

**Changes:** Source review and the three clinical writers now reject a missing current creator account. Source and clinical queues/details retain orphaned rows; clinical text/actions are hidden and source review is disabled. The clinical queue uses a page-local author lookup. Synthetic tests cover deferred-FK corruption, direct/HTTP writes, ordinary and inactive accounts, ancestor and diagnostic boundaries, nonparticipating mutations and selected account-update races; scan pages explain that they do not check creator accounts.

**Limits:** Existence is neither historical identity nor qualification, accounts are not locked, and parent authors or other domains are not covered. Nonparticipating changes can occur after the check. Synthetic only; see ADR 0033.

## 2026-11-22 — reviewer lookup in intake histories

**Changes:** Source, product and price detail retain recent review rows even if their reviewer account is missing, show an unknown-details notice and keep the real latest review ID in the form. The bounded reviewer lookup is shared with clinical detail. Synthetic tests cover missing latest and older reviewers, stale and fresh submissions, permissions, 25-row/query bounds and non-snapshot lookup; Chromium checks normal histories at four widths.

**Limits:** A fresh review remains permitted when a previous reviewer is absent. Lookup is not a historical identity check, audit or review-snapshot validation. Missing parent authors, direct database writes and later changes remain out of scope; see ADR 0032.

## 2026-11-22 — clinical review detail comparison boundaries

**Changes:** The private detail distinguishes the reviewed draft/author comparison from the reference-set comparison, uses the existing technical classifier before displaying historical assertions, and treats missing evidence without claiming age. Invalid record decisions and reasons are suppressed, and a missing reviewer no longer hides the row or resets the expected-review ID. Tests cover corruption, contributor conflicts, separate-read and ABA behavior, the 25-row cap, query counts and synthetic Chromium at four widths.

**Limits:** Readings are non-snapshot; a match does not prove absence of intervening changes, actor qualifications, source rights or clinical correctness. A corrupted missing draft author can still hide the draft in the existing detail join. No historic data is rewritten or authenticated; see ADR 0031.

## 2026-11-22 — immediate-parent locks for clinical writes

**Changes:** Review, supplementary reference addition and revision creation now lock and re-read the immediate parent of the already locked draft before their local consistency check. Selected PostgreSQL tests cover both directions of parent updates, stale preloaded objects, sibling contention, rollback, missing parents and outer transaction lifetime.

**Limits:** Only one parent is checked; a grandparent can change during review. Later bypass writes and deferred reference inserts can still stale observations. More locks can increase waits or deadlocks and no retry is provided. This is not provenance, clinical approval, whole-lineage validation or production hardening. See ADR 0030.

## 2026-11-22 — limited clinical reference row locking

**Changes:** Review and reference addition lock the bounded existing assertion rows after the draft lock, before validation, while read-only inspection stays non-locking. PostgreSQL tests exercise waiting updates, stale conflicts, rollback, outer transaction lifetime and the 11-row sentinel. The specific concurrent existing-reference update from ADR 0028 is blocked while the write transaction holds the lock.

**Limits:** Later updates and pending new inserts can stale snapshots; a separate test demonstrates an unprotected concurrent parent update. There is no predicate or parent lock, retry, audit or clinical guarantee, and locks can wait or deadlock. See ADR 0029.

## 2026-11-22 — source and clinical triage boundaries

**Changes:** Source review rejects malformed/out-of-range IDs, boolean IDs and non-string decisions; clinical review applies the same expectation bounds and decision type check. Both hidden fields reject out-of-range values and offer a private, explicit detail-page restart. Tests exercise direct services, permissions, HTTP errors, synthetic Chromium recovery and selected PostgreSQL review races. Clinical detail warns about stale reference snapshots.

**Limits:** A controlled bypass writer can change an existing clinical reference during review despite the parent lock, leaving a coherent but already stale review snapshot. This limitation is demonstrated, not fixed. Results are not a production concurrency, source-rights, audit or clinical guarantee. See ADR 0028.

## 2026-11-22 — focusable skip target and failure categories

**Changes:** The shared main landmark is focusable by native fragment navigation but not in normal Tab order. Browser checks wait for actual landmark focus before Tab, verify a missing target tabindex fails, and report only a fixed active-element region on selected failures. This follows CI run 45137885675, which failed the login skip next-focus check at 1440 pixels.

**Limits:** The active element in that historical run was not recorded; the failure's cause remains unknown, as does the older home failure's. This change is not a demonstrated root-cause fix or screen-reader and cross-browser certification. See ADR 0027.

## 2026-11-22 — skip navigation and contrast checks

**Changes:** The staff login form no longer forces focus to username. Real-keyboard browser coverage now checks skip navigation on home, about and login, invalid-login recovery and selected forced-color states, with negative mutation tests and bounded diagnostic annotations. The test waits for the fragment before Tab and keeps axe outside the keyboard sequence. Darkened a home eyebrow and decorative captions after axe reported low contrast; selected opaque-background contrast checks were added.

**Limits:** CI run 45135591434 failed on the old home skip assertion; its full log was unavailable and rerun failed. The cause and width remain unknown, and later passes do not prove the historical failure fixed. Some axe results remain inconclusive; manual contrast, screen-reader, other-browser and device review remain necessary. See ADR 0027.

## 2026-11-22 — receipt validation reuse and product triage checks

**Changes:** Receipt detail and inspection reuse pure candidate integrity results within a single joined page/batch while checking each manifest row independently; tests cover duplicate and distinct candidates, corruption, page boundaries, operation and query counts, and a duplicate receipt in Chromium. Product review IDs are bounded in the form and direct service; PostgreSQL tests exercise selected simultaneous reviewers and candidate updates.

**Limits:** This is not an optimization of staging writes, a benchmark, a database snapshot or proof of provenance/identity. Privileged writers can bypass review protocols; no retry, audit or production guarantee is added. See ADR 0026.

## 2026-11-22 — bounded receipt-row consistency inspection

**Changes:** Added a private, permission-scoped, read-only inspection of one receipt at a time, scanning up to 50 current candidate comparisons plus lookahead and filtering only within that batch. Shared the structural and per-row checks with receipt detail. Tests cover both domains, legacy and corrupt manifests, permissions, private errors, query counts, selected non-snapshot behavior and synthetic Chromium access at four widths.

**Limits:** Technical consistency is not file provenance, source authorization, identity or clinical approval. Aggregate and row reads can observe different times; no snapshot or complete-history claim is made. Recorded price matching is not recomputed. Synthetic data only; database work and bytes are not bounded by the output cap. See ADR 0025.

**Browser-test correction:** A later recurrence of the 320px upload-result failure showed `staff.css` had not yet applied (`display: block`, no input max width) when layout was measured. The POST test now waits for page load, explicitly asserts the stylesheet's grid is applied, and exercises an intentionally delayed stylesheet; it still fails on real overflow. Earlier CSS width constraints remain, but the prior change alone did not establish the cause of every occurrence.

## 2026-11-22 — explicit synthetic projection repair

**Changes:** Added a DEBUG-only local command to preview a single presentation's projection drift and explicitly repair only derived fields after a signed, short-lived state/database recheck under a row lock and a synthetic-data attestation. Tests cover stale/deleted records, malformed inputs, time precision, failure rollback, private output, CLI flags, matching/search effects and selected PostgreSQL concurrency.

**Limits:** Repair can alter search and matching of already-published records without changing publication flags. It does not verify identity, rights or clinical content; DEBUG and attestation do not make real data safe. There is no batch operation, audited user attribution, automatic retry or production authorization. See ADR 0024. During validation, Chromium intermittently reported horizontal overflow in the 320px price preview; geometry identified the file input extending beyond the viewport. The form grid and file input now have bounded widths, and the browser smoke checks a long selected filename. Overflow failures report bounded geometry without form values; broader browser/device coverage remains incomplete.

## 2026-11-22 — presentation partial-save projection consistency

**Changes:** Nonempty partial model saves lock and read the presentation row inside a transaction before recomputing the search and IRC projections. Deprecated Django 5.2 positional save parameters are parsed before projection handling; empty updates remain no-ops. The quality inspector shares the projection field list. Synthetic PostgreSQL tests exercise overlapping partial saves, lock waits, errors, rollback, stale instances, positional calls and pricing lookup.

**Limits:** This adds locking and possible waits/deadlocks without retries. Bulk/SQL writes, historical models and stale full saves are not covered; existing inconsistencies are not automatically repaired. It does not prevent concurrent duplicate matching rows or provide source or clinical verification. See ADR 0023.

## 2026-11-22 — price review concurrency limits and validation

**Changes:** Added separate-connection PostgreSQL tests for simultaneous reviewers, locked product updates, concurrent duplicate inserts and a staging cache observed across a committed product change. The price detail page now warns that acceptance does not guarantee uniqueness. Review service and form reject out-of-range IDs, with direct service calls rejecting boolean IDs and malformed decisions.

**Limits:** One test deliberately reproduces a duplicate inserted between the fresh locked match and acceptance; it is not fixed by this change. Row locks do not protect absent matches or future writes. Tests cover selected interleavings with synthetic data, not production behavior or an approval, provenance or audit system. See ADR 0022.

## 2026-11-22 — bounded per-IRC price matching reuse

**Changes:** Added a per-invocation, eight-group LRU of bounded candidate indexes, so distinct price identities sharing an IRC can reuse one catalog query. Fresh matching and accept-review use the same matching logic, retaining conservative over-limit ambiguity and row locking. Tests compare the previous algorithm, exercise stale indexes, duplicate matches, the 100/101 boundary, eviction and changing catalog data; Chromium covers a synthetic multi-identity preview.

**Limits:** Cached IRC groups can miss catalog changes across distinct identities; eviction can mix observations from different times with older per-identity results. This is not a snapshot, validation of product or source, or production benchmark. Cache group/row limits do not bound byte size, database work or time.

## 2026-11-22 — request-local price matching reuse

**Changes:** Price CSV preview and staging now reuse one matching observation per normalized identity within each invocation, preserving per-row counts, receipts, source/payload deduplication and fresh detail and accept-suggestion review matching. The web form and CLI explain the reuse. Tests cover 5,000 repeated and distinct keys, all identity fields, ambiguous sets, replay, receipt outcomes, rollback and catalog changes between rows; synthetic Chromium exercises price preview at four widths.

**Limits:** Repeated rows may reuse a stale first observation if the catalog changes during the call; different identities can reflect different times. This is not a snapshot, production benchmark, source authorization or approval. Up to 5,000 distinct identities can still cause 5,000 matching queries; byte size, database work and time are not bounded by the cache.

## 2026-11-22 — synthetic clinical review snapshot inspection

**Changes:** Added a private read-only, per-draft, 50-review scan with page-local status filters and non-reflecting error recovery. It validates supported historical draft and supplementary-evidence snapshot structures, reports missing or invalid images and compares the snapshot draft hash/author ID to a technically consistent current version. It shows IDs and fixed statuses only. PostgreSQL tests and synthetic Chromium exercise access, tampering, pagination and selected accessibility checks.

**Limits:** Missing evidence is not proof of age. Actor existence/qualifications, current evidence, provenance, source rights and clinical correctness are not established. The scan is non-snapshot, JSON bytes and database work are not bounded, and this is not an audit or production feature. Axe contrast inconclusives require manual review.

## 2026-11-22 — synthetic clinical parent-path inspection

**Changes:** Added a private, permission-checked, read-only inspector for up to 20 immediate-parent links per section, including restartable, signed, time-limited continuation and a generic non-reflecting cursor error. It checks observed payloads and seams, stops on inconsistencies and shows IDs only. PostgreSQL and synthetic Chromium tests cover paths, boundaries, stale/malformed cursors, permissions, concurrent-change seams and selected accessibility checks.

**Limits:** The path is not a snapshot or complete history; earlier links, reviews, authors and references are not revalidated on continuation. Hash consistency is not authenticity, source rights or clinical approval. Tokens can appear in logs; this remains development-only and axe contrast inconclusives require manual review.

## 2026-11-22 — batch clinical technical inspection queries

**Changes:** Replaced per-draft reference and recorder lookups in the clinical scan with a per-draft PostgreSQL window and bulk recorder lookup, retaining the existing shared reference/cap checks and over-limit precedence. The diagnostic now runs at most three SELECTs for 50 drafts and fetches at most 11 assertions per valid draft; the write/review workflow retains its individual state and snapshots. Added boundary, reused-instance, missing-recorder and equivalence tests.

**Limits:** This is not a consistent snapshot, and fewer returned rows/queries do not bound database work or establish clinical, source or audit validity. PostgreSQL query performance on production data is unmeasured; this remains a synthetic development diagnostic.

## 2026-11-22 — synthetic clinical technical inspection

**Changes:** Added a private, view-permission-only, forward-only inspection of up to 50 draft versions per section with page-local status filtering. Reuses current draft/immediate-parent and bounded supplementary-reference checks, shows only IDs and fixed statuses, and offers non-reflecting invalid-input recovery. PostgreSQL and synthetic Chromium tests cover validation, permissions, bounded queries, paging, privacy and selected accessibility checks.

**Limits:** Not a snapshot or full lineage/review audit; no check proves authenticity, evidence quality, source rights, clinical validity or publication readiness. Query count is bounded, not database work or response size/time; this remains development-only. Axe contrast inconclusives require manual review.

## 2026-11-22 — private scan error recovery

**Changes:** Authorized staff now receive a generic Persian HTTP 400 page for invalid catalog-quality or source-date scan parameters, with a fixed local restart link and no reflected input. Restart clears position and filter. Existing authorization, validation, privacy headers and scan limits remain unchanged. Server and synthetic browser tests cover error handling, access checks and recovery.

**Limits:** Invalid URLs can still be logged; the page is not a production security or accessibility review. Automated axe checks have inconclusive contrast results requiring manual review.

## 2026-11-22 — localized staff inspection IDs

**Changes:** The source-date and catalog-quality starting-ID forms now accept Persian, Arabic-Indic and ASCII digits, including mixed scripts. A shared bounded parser maps only these digits before integer conversion; the unchanged upper limit and permissions still apply. Unit, PostgreSQL and synthetic Chromium tests cover localized values, equivalence, exact boundaries and invalid formats.

**Limits:** Other numeral sets, signs, separators and exponent notation are rejected. HTML validates syntax only; the server checks the exact maximum. Device keyboards, screen readers and all browser engines remain untested; this does not change source rights or clinical validity.

## 2026-11-22 — staff inspection ID entry

**Changes:** Replaced the two starting-ID number controls with required numeric-mode text controls and an ASCII digit syntax constraint, plus visible accessible guidance. This preserves large integer text exactly and prevents empty or exponent-form submissions that the server rejected. Existing server limits, query behavior, permissions and data remain unchanged. Synthetic Chromium checks syntax and invalid submission at four widths; PostgreSQL tests cover the boundaries.

**Limits:** HTML validates syntax, not the exact upper numeric bound; 19-digit values above the maximum still get HTTP 400 from the server. Browser keyboards and native validation messages vary; real-device and screen-reader validation remains necessary. Axe contrast inconclusives still need manual review.

## 2026-11-22 — focus failure diagnostics

**Changes:** Browser failure annotations can now identify focus checks by an exact, fixed allowlist of control labels, viewport widths and failure reasons. Tests reject unrecognized and injected messages; no arbitrary assertion text is copied. The focus criterion, application CSS and failure behavior are unchanged.

**Limits:** Five consecutive local synthetic Chromium runs passed; the previous CI focus failure was not reproduced or explained. The annotation is heuristic, covers selected checks only, and does not replace logs or a manual accessibility review.

## 2026-11-22 — browser failure call-site diagnostics

**Changes:** Include up to two additional JavaScript call-site line numbers in browser-failure annotations, without copying arbitrary stack text or paths. A synthetic multi-frame test checks both the bound and redaction.

**Limits:** CI for the public-read header change failed at a focus-outline assertion; the failing control and root cause could not be determined from the available annotation, and the full job log was inaccessible. The additional lines can help diagnose a future failure but do not fix or explain this one.

## 2026-11-22 — public-read error privacy headers

**Changes:** A narrowly scoped response middleware applies `no-store`, `no-referrer` and `noindex` to resolved search, presentation detail and OpenAPI views, including Django's 405 and CSRF 403 responses. Existing view-level headers and allowed methods remain unchanged. PostgreSQL-backed tests cover GET/HEAD, selected 400/404/500 errors, unsafe methods with and without CSRF, method `Allow`, and unrelated staff/public policy isolation.

**Limits:** The policy does not cover unresolved requests, redirects before URL resolution or upstream responses; URLs can still appear in access logs. Debug error pages can expose request data. No rate limiting, logging redaction or production security review is added.

## 2026-11-22 — synthetic browser CI diagnostics

**Changes:** Failed isolated Chromium subprocesses in GitHub Actions now add a compact error annotation with an exit outcome, fixed heuristic category and optional smoke-test source line; timeouts are also noted. Offline tests check the summary and exclusion of arbitrary sample error text. Existing failure output and failure status are unchanged; no automatic retry is added.

**Limits:** The annotation does not explain every failure or replace full logs, and ordinary test logs can still contain synthetic values. A previous browser CI failure remained unexplained because its job log was inaccessible and rerun permission was denied; this diagnostic is for future failures, not a claim about that cause.

## 2026-11-22 — public-search cursor recovery coverage

**Changes:** Added server and synthetic Chromium regression tests for the existing invalid-cursor recovery: valid query retained, invalid cursor not echoed or resubmitted, and restart by Enter. Tests cover selected malformed Unicode, NUL and overlong cursors, GET/HEAD and privacy headers, plus layout at four widths and axe at 390. No search behavior or medical data changed.

**Limits:** The checks are not exhaustive input, accessibility, privacy or security reviews; access logs can still contain search URLs, and pagination is not a snapshot. Axe's inconclusive contrast results require manual review.

## 2026-11-22 — invalid public-search query handling

**Changes:** A NUL in a public search previously caused a PostgreSQL text error. Search now rejects NUL or surrogate code points in the retained query prefix before a database query, returning HTTP 400 with a blank recovery form or an `invalid_query` API error; the invalid input is not echoed. Existing 120-character truncation and other search normalization remain unchanged. Added PostgreSQL, API contract and synthetic browser regression tests.

**Limits:** This narrow check is not general input sanitization, logging protection, rate limiting, clinical verification or production hardening. Search URLs can still appear in access logs; never enter personal data.

## 2026-11-22 — internal inspection keyboard and contrast checks

**Changes:** Styled numeric inspection filters consistently with the existing controls. Expanded synthetic Chromium coverage for keyboard focus and Enter submission on source-date and catalog-quality inspections, including forced-colors emulation for the source-date form. Added computed text contrast checks for selected workspace, source summary and scan elements; deliberate low-contrast, background-image and missing-focus mutations are rejected.

**Limits:** These checks cover selected text and controls on known opaque surfaces, not all pixels, pages, assistive technologies or devices. Axe still reports inconclusive contrast items needing manual review. The changes do not alter application data or authorization.

## 2026-11-22 — bounded source claim date inspection

**Changes:** Added a private read-only date inspection for source viewers: a 50-claim ascending-ID scan with an optional batch-local category filter and continuation even through empty batches. It shows IDs and date categories, not source names or URLs, and does not modify data. Synthetic tests cover bounded traversal, permissions, invalid inputs, live changes and browser navigation.

**Limits:** This is neither a fixed snapshot nor proof of source rights, coverage or authorization; dates and assertions are unverified. It is not an alert, a scheduler, or a production-scale monitoring system. See the [development guide](DEVELOPMENT_GUIDE.md#development-only-source-rights-assertions).

## 2026-11-22 — page-local source claim date summary

**Changes:** Added a read-only date-category summary for the currently displayed, review-filtered page of source claims, using one local date for all rows. Tests cover boundaries, invalid claims, permissions, pagination, no writes and synthetic Chromium layout/accessibility checks.

**Limits:** Counts are page-local, not a global inventory or a consistent snapshot. Dates and claims are unverified; the summary does not establish source rights or authorize use, and does not alert or calculate upcoming expiry. Database filtering/counting work is not bounded by the page size.

## 2026-11-22 — workspace landing and unreviewed queue shortcuts

**Changes:** Active staff now land on the permission-scoped workspace by default after login; Django's explicit safe `next` destination still takes precedence and its own permissions remain enforced. Added shortcuts to the existing unreviewed filters for product, price, source and clinical queues. They add no counts, data writes, new review states or permissions.

**Limits:** Unreviewed means no recorded review event, not all outstanding work or eligibility for this reviewer. Existing reviewed/deferred records are excluded. The portal remains development-only, synthetic-data-only and not a production dashboard.

## 2026-11-22 — permission-scoped staff workspace navigation

**Changes:** Added a private, read-only `/staff/` navigation page and return link from private staff pages. Active staff see only links corresponding to existing view permissions; the page does not show counts, records or operational status. Login landing behavior and destination authorization are unchanged. Synthetic role, permission revocation, privacy, CSRF logout and Chromium/axe checks cover the new page.

**Limits:** This is navigation, not a production dashboard or an authorization boundary; each destination independently enforces its permissions. No metrics, scheduler, approval, publication, audit, MFA or production security capability is added. The portal remains development-only and synthetic-data-only.

## 2026-11-22 — read-only lock metadata comparison

**Changes:** Added an optional standard-library tool to compare both checked-in Python hash locks with current PyPI release metadata, plus offline tests for mismatches, invalid input and registry failures. It does not change lock files, application logic or data. See the [maintenance procedure](DEVELOPMENT_GUIDE.md#maintaining-python-dependency-locks).

**Limits:** This compares metadata hash sets rather than downloading artifacts or independently authenticating them. Registry changes and intentional artifact subsets can cause mismatches; a match is not a safety or reproducibility guarantee.

## 2026-11-22 — Python artifact hash locks

**Changes:** Added a runtime artifact lock with transitive pins and SHA-256 hashes, a direct-pin consistency check, and a separate hash lock for the development image's pip/setuptools upgrade. CI and Docker require hash verification; direct runtime versions and application/database behavior remain unchanged. See the [maintenance procedure](DEVELOPMENT_GUIDE.md#maintaining-python-dependency-locks).

**Limits:** Hashes verify selected bytes against checked-in values, not publisher authenticity or package safety; image tags, initial image tooling and audit-tool dependencies remain outside these locks. This is not a fully reproducible or production-hardened build.

## 2026-11-22 — dependency advisory checks

**Changes:** Added isolated `pip-audit` checks for resolved Python requirements and Python packages in the development image, plus an npm audit for browser dependencies. The local requirements and npm audits found no known advisories at the time of review. Older pip/setuptools in the ignored local development venv were updated after retaining the old wheels and package list under ignored `.cache/`. The development image now installs pinned newer pip/setuptools before the unchanged application requirements; no database or business logic changed.

**Limits:** Advisory databases change; checks require external registries and do not scan operating-system packages, Chromium, bundled native libraries or the auditor's own dependencies. Version pins are not package hashes, image tags remain mutable and this is not a production security assessment. See [Testing strategy](TESTING_STRATEGY.md#known-dependency-vulnerability-checks).

## 2026-11-22 — CI action runtime and pin review

**Changes:** Updated official checkout, setup-python and setup-node actions to version-specific v7 commit SHAs using the Node 24 Actions runtime, and disabled checkout credential persistence. Preserved the Python 3.11 and browser Node 22 environments and the PostgreSQL, browser and Compose checks.

**Limits:** SHA pins need regular review and do not verify upstream code, package downloads or mutable container images. This is not a complete supply-chain or production security assessment. See [Deployment](DEPLOYMENT.md#development-ci-and-proposed-cicd).

## 2026-11-22 — development build-context and PostgreSQL readiness review

**Changes:** Excluded local environment variants and JavaScript dependencies from Git/build context while preserving `.env.example` templates; hardened Docker exclusion ordering for backups and local dependency/cache directories. Added synthetic CI probes for root/nested excluded files and template exceptions, real PostgreSQL readiness and nonexistent-database checks; no schema or data migration changed.

**Limits:** Ignore rules do not remove already tracked secrets or old image layers and are not comprehensive secret scanning. CI uses a disposable Compose volume; this is not production hardening or disaster recovery. See [Testing strategy](TESTING_STRATEGY.md#development-image-build-context-checks).

## 2026-11-22 — keyboard focus regression review

**Changes:** Removed a CSS reset that suppressed the search input's keyboard-focus outline. Extended isolated Chromium tests to check selected focus outlines and their computed contrast, submit search and staff login with Enter, and exercise search, login and a private synthetic form under emulated forced colors and reduced motion. Missing and low-contrast outline regressions were observed to fail. No business logic, data or layout changes.

**Limits:** These checks cover selected controls and computed container colors only; emulation is not an OS/device, screen-reader or complete accessibility assessment. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — browser startup investigation and contrast review

**Changes:** Investigated intermittent local headless Chromium startup failures. The isolated SSR smoke test now uses software rendering without the bundled GPU/SwiftShader flags, retaining normal web security. A local about:blank launch experiment recorded 4/30 failures with previous flags and 0/130 with GPU disabled; no automatic retry was added. Added computed-color contrast checks for selected home-page text and placeholder against the gradient endpoints and input background; a deliberately low-contrast mutation failed as expected. No product data or public layout were changed.

**Limits:** This local experiment does not prove the crash's root cause or guarantee other environments; GPU/WebGL rendering is untested. Axe continues to report other inconclusive contrast items; manual, screen-reader and device evaluation remains necessary. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — focused accessibility and CSRF regression review

**Changes:** Expanded the isolated synthetic Chromium workflow to public product detail, logout, invalid-form error associations, missing-token rejection and keyboard skip navigation. Added automated axe WCAG-tagged checks on ten representative page states, corrected three reported contrast issues and the home-link accessible name, and added same-origin, hostile/null Origin and HTTPS Referer CSRF regression cases with valid tokens. No clinical or published data were added.

**Limits:** Axe reports inconclusive contrast items for manual review. The local headless Chromium process intermittently crashed at startup on this lean container; no automatic retries hide the failure. No complete WCAG, screen-reader, device or security assessment is claimed. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — isolated Chromium checks and staff CSRF fix

**Changes:** Added opt-in, isolated synthetic PostgreSQL/Chromium smoke checks in CI. Chromium revealed that the staff `no-referrer` policy generated `Origin: null` on form submission and caused Django's CSRF protection to reject real logins. Staff responses now use `same-origin`: form requests retain a valid Origin while cross-origin requests omit referrers. Existing private cache and indexing headers are unchanged.

**Limits:** Same-origin requests and logs can contain staff URLs; never use sensitive data. The browser runs without an OS sandbox in trusted test environments. A few viewports and keyboard assertions are not full accessibility, device, security or clinical validation. See [Testing strategy](TESTING_STRATEGY.md#opt-in-synthetic-chromium-smoke-test).

## 2026-11-22 — synthetic correction ancestry inspection

**Changes:** Added permission-scoped, read-only, bounded parent-path inspection for the four private identity draft types, with signed, graph-bound continuation cursors. Invalid graphs/links stop inspection without rendering their details. Added synthetic pagination, corruption, stale/expired cursor, role, privacy, bounded-query and data-isolation tests. No schema, review or public behavior changed.

**Limits:** The path is not a snapshot, completeness or authenticity proof; earlier pages are not rechecked and parallel branches are not traversed. Hashes can be recomputed and direct writers can race. No browser/accessibility, clinical, legal or production security validation. See [ADR 0015](ARCHITECTURE_DECISIONS/0015-synthetic-lineage-inspection.md).

## 2026-11-22 — synthetic ingredient, formulation and product corrections

**Changes:** Added typed private immediate-parent correction links and forms for synthetic ingredients, formulations and products, with branch support, graph preconditions, transactional creation, scoped link navigation and validation. Existing dependants and package reviews are not rewired or transferred. Added populated migration, rollback, permission/CSRF, corruption, pagination and concurrent PostgreSQL tests.

**Limits:** Links are unverified assertions, not equivalence, whole-ancestry validation, clinical approval or audit. Formulation corrections preserve ordered ingredients; product corrections preserve formulation. Bulk/SQL and non-cooperative writers bypass guards and locks; hashes are not signatures. No real data, public changes, browser/accessibility, clinical or production assessment. See [ADR 0014](ARCHITECTURE_DECISIONS/0014-synthetic-component-revisions.md).

## 2026-11-22 — synthetic package correction branches

**Changes:** Added an additive PostgreSQL migration for private immediate-parent package correction links, fixed-product child creation, separate reason and graph hashes, latest-review and graph stale checks, atomic creation, and independent branch support. Staff can create corrections and browse validated links in bounded pages; old records and reviews remain unchanged. Synthetic migration, rollback, malformed data, permissions, CSRF, conflict and two-connection race tests included.

**Limits:** These are asserted links, not equivalence, authenticity, ancestry-wide checks or approval. Reviews cover the new graph only, not revision provenance or the parent, and do not transfer. No ingredient/formulation/product corrections, public changes or source verification. Bulk/SQL bypass guards; hashes are not signatures. No browser, clinical, legal or production security validation. See [ADR 0013](ARCHITECTURE_DECISIONS/0013-synthetic-package-revisions.md).

## 2026-11-22 — formulation formset validation

**Changes:** Ensure even an empty or malformed formulation component formset is validated and its errors rendered. The create-only form requires its fixed five management slots with no initial forms, rejects duplicate ingredient IDs before the service, and offers a fresh-form link if no component forms were rendered. The service retains its own bounds and uniqueness checks; no schema or public behavior changed.

**Limits:** The form structure check is not an authenticity or source validation mechanism. Only synthetic input is allowed. No browser/accessibility, clinical or production assessment was performed. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — identity graph read and migration checks

**Changes:** Reconstruct each formulation and its ingredient snapshots from one joined component read, reusing the result throughout the graph rather than repeatedly reading it; staff package/product queries join their direct dependencies. Payload hashes and stored graph format are unchanged. Added synthetic compatibility, query-count, PostgreSQL constraint and populated 0004-to-0005 catalog migration tests.

**Limits:** One component statement is not an isolated graph snapshot, a lock against uncooperative writers, or a production performance benchmark. Migration tests do not replace backups or restore drills. No database schema or publication behavior changed. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — identity review history navigation

**Changes:** Replaced the 25-review history cutoff with bounded descending-ID pages scoped to the selected package. The review form appears only on the newest page and uses the latest review actually shown as its optimistic precondition. A stale submission requires a reload and reassessment. Existing permissions, privacy, snapshot checks and public isolation remain in place; no schema change.

**Limits:** Pages are not a database snapshot or tamper-proof audit. Uncooperative writes and out-of-order IDs can change results; query plans and large datasets were not benchmarked. Historical content remains synthetic and unverified. No browser/accessibility or production validation. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — identity review history interpretation

**Changes:** Made the private identity graph human-readable with explicit source/actor fields and links; validate stored review graph shape, links, hashes, quantities and reviewer separation before display. Consistent reviews are labeled current or historical, with an expandable historical snapshot; invalid current graphs suppress history rather than claiming none exists. No schema or public changes.

**Limits:** Coherent snapshots can be fabricated by a database writer, and reason, decision and time are not integrity-protected. Historical comparison does not prove a real change. Bulk/SQL bypass guards; reads are not snapshots. No browser/accessibility, medical or production validation. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — private synthetic identity drafts

**Changes:** Added a private, permission-scoped draft chain from ingredients through ordered formulation components and products to packages, with asserted sources and preliminary independent package review. Bounded staff pages, conflict checks, PostgreSQL migration and synthetic tests are included. Public catalog records and eligibility are unchanged.

**Limits:** A development prototype, not a comprehensive identity model, verified source, clinical approval, equivalence or publication workflow. Hashes are not signatures; bulk ORM/SQL bypass guards, direct writes can race, and only cooperative reviews are serialized. No real patient or proprietary data, browser/accessibility, medical or production validation. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).

## 2026-11-22 — cross-batch indexed IRC clues

**Changes:** Added a private, permission-scoped indexed IRC inspection page and local command anchored on a presentation ID. Forward signed cursors paginate bounded indexed clues across the catalog; inconsistent indexes are flagged, anchor drift or cursor tampering stops inspection, and raw names/URLs/codes are not deliberately output.

**Limits:** This is not a complete catalog-wide duplicate audit: stale indexes can hide rows and concurrent changes make pages non-snapshot. Codes and cursors are not proof of identity, rights or confidentiality; no repair or publication occurs. No browser accessibility, medical or production validation was performed.

## 2026-11-22 — PostgreSQL staging concurrency

**Changes:** Product and price committed CSV stages now take a transaction-level advisory lock for the exact source URL and domain, including direct services, CLI and web receipts. Added PostgreSQL two-connection tests for reversed import order, lock waiting, rollback, preview, receipt integrity and concurrent clinical evidence/triage. No schema or publication behavior changed.

**Limits:** The lock is cooperative, may wait without an application timeout and can be bypassed by other writers. Different URL spellings are distinct; collisions can serialize unrelated imports. It does not protect catalog matching from concurrent insertion or establish exactly-once receipts, source rights, complete concurrency safety or production readiness.

## 2026-11-22 — PostgreSQL-only database

**Changes:** Configured Django and psycopg for PostgreSQL exclusively, introduced environment-based connection settings, PostgreSQL-backed CI and a development Compose stack with persistent volume and readiness checks. Existing Django migrations and models remain in place. Replaced former database-specific backup tooling with PostgreSQL-native dump/restore guidance. Added PostgreSQL integration and concurrent stale-review tests.

**Limits:** Development Compose is not production deployment; no production backup retention, independent security or load review exists. Database locks protect selected rows only; concurrency is not universally proven. Hosted CI and Docker availability depend on the environment.

## 2026-11-22 — read-only catalog quality inspection

**Changes:** Added a permission-scoped debug staff page and local JSON command for bounded ID-ordered product-presentation inspection. Reports flag projection drift, stricter source URL warnings, published rows rejected by technical filters, invalid text and page-local IRC duplicates; no field values, automatic repairs or publication changes. Added synthetic permission, drift, pagination, corruption and read-only tests.

**Limits:** Duplicate checks only cover one batch, and scans are not snapshots. Passing checks is not clinical, identity, rights or publication approval; stricter URL hygiene is advisory and does not change existing public eligibility. CLI and service are outside the web gate; no production monitoring, browser, security, source or clinical validation was performed.

## 2026-11-22 — development CI

Basic GitHub Actions checks were added; the current workflow uses a PostgreSQL service. The former database-specific local snapshot utility has been retired; PostgreSQL-native backup and restore guidance supersedes it.

## 2026-11-22 — supplementary clinical reference assertions

**Changes:** Added up to ten unverified supplementary reference assertions per draft version, explicit asserted relationship labels, deduplication, separate-recorder review separation, sequential evidence-set stale checks and bounded review snapshots. Staff can inspect historical snapshot metadata and see whether its fingerprint differs from the current set; old reviews are explicitly marked without a snapshot. Added synthetic tests for role separation, caps, corruption, migration and public exclusion.

**Limits:** Claimed relationships, citations, dates, licences and reviewer qualifications are not verified; no clinical approval or publication occurs. The set fingerprint includes recorder IDs but omits timestamps, and hashes are not signatures. The limit and stale checks are not concurrency or audit guarantees; bulk ORM/SQL bypass guards. No real evidence, browser accessibility, medical, legal or production validation was performed.

## 2026-11-22 — private synthetic clinical statement drafts

**Changes:** Added a development-only clinical draft domain with separate view/add/review permissions, a Persian RTL queue, asserted citation metadata, branched parent-linked versions and independent preliminary triage snapshots. Integrated separately permissioned exact-URL source-claim hints and clinical-only login navigation. Added synthetic role, CSRF, input, version, stale and corruption tests; there is no approval or publication action.

**Limits:** Drafts, references, dates and reviewer qualifications are unverified; the text field cannot enforce one statement and is not linked to a real drug. Immediate-parent checks do not certify full ancestry. No seed clinical content, licensed evidence, clinical approval or public presentation was added. Hashes omit actor/time and are not signatures; bulk ORM/SQL bypass guards, concurrent behavior and production security remain unproven. No browser, medical, legal or production validation was performed.

## 2026-11-22 — intake row outcomes and receipt navigation

**Changes:** New receipt-backed product and price imports atomically record bounded per-data-row outcomes linking to candidates, including duplicates, content fingerprints and request-time price suggestions. Receipt details validate structure and candidate consistency, paginate rows and hide inconsistent links. Candidate pages show capped, domain-scoped recent receipt clues. Existing receipts are explicitly marked as lacking row details; no backfill is invented. Added synthetic rollback, permissions, corruption, replay, constraints and migration tests.

**Limits:** No raw file or file-level hash is kept; this cannot prove original contents, source permission or immutable audit. Hashes are not signatures and price payload hashes omit source URLs. CLI/direct imports, preview, failures and older receipts remain outside row manifests. FKs protect ordinary deletion, but bulk ORM/SQL bypass guards; retention and production concurrency/crash behavior are unresolved. No source, clinical, browser or production validation was performed.

## 2026-11-22 — web intake receipts

**Changes:** Added minimal successful-web-stage receipts for product/price CSV imports, written transactionally with candidates, plus permission-filtered Persian list/detail pages and links from uploads and queues. Stored counts distinguish created and duplicate rows; price match counts include duplicates and reflect that request's catalog. Added count constraints and synthetic rollback, permission, replay, CSRF and pagination tests.

**Limits:** Receipts are not source-rights proof, verified data, complete logs, batch manifests or immutable audit. No raw file, filename, file hash or row membership is retained; previews, failures, older imports and CLI/direct imports are absent. Replays create new receipts, without request idempotency. Model guards can be bypassed with bulk ORM/SQL, and concurrency/crash behavior and production security are unproven. No source, clinical, browser or production validation was performed.

## 2026-11-22 — offline ingestion-window inspection and input hardening

**Changes:** Added a pure offline current/next window calculator with configurable per-call IANA timezone and local HH:MM boundaries, default Tehran 23:00–01:00, a JSON management command and a permission-gated Persian debug-only staff view. Rejects ambiguous/nonexistent local boundaries and converts to UTC using timezone rules. Shared validators now reject unsafe source URL edge cases and invalid review text across product, price and source workflows. Added synthetic timezone, permission and validation tests.

**Limits:** No persisted schedule, scheduler, worker, rights check, network collection or publication. Clock and IANA data must be maintained; an open interval is not authorization or evidence of a run. Existing candidate records with newly invalid URLs fail review and require investigation, not silent rewriting. No concurrency, browser accessibility, penetration, source-rights or production testing.

## 2026-11-22 — source assertions and independent preliminary triage

**Changes:** Added a development-only internal ledger of source-rights assertions with explicit scopes, owner, evidence URL, claimed dates, recorder, duplicate detection and a separate preliminary reviewer. Added a paginated/filterable Persian staff queue and exact-URL, permission-gated, capped links from product and price candidate details. Validation and synthetic tests cover access boundaries, CSRF, sequential conflicts and integrity, date labels and no public writes.

**Limits:** Claims, evidence, dates and triage are unverified and do not authorize or gate intake, source use, crawling or publication. Source hints are not part of candidate review snapshots. Fingerprints omit actor/time and are not signatures; bulk ORM/SQL can bypass model guards; concurrency is unproven. Only synthetic local testing, not legal/source verification, browser accessibility, penetration or production testing.

## 2026-11-22 — price revision triage and safer suggestions

**Changes:** Added a staff price-queue filter for the latest preliminary review, combinable with the original match-status filter. Detail pages show up to 10 same-source/ID revisions and a conditional exact whole-Rial difference only when source name, unit/category and nonempty normalized identity fields match. Dates and original currencies remain explicit; no price or trend is approved/published. Hardened matching against invalid/normalization-empty identifiers and conservatively marks more than 100 same-IRC indexed presentations ambiguous. Malformed Unicode in stored JSON is not rendered as valid staff data. All 99 Django tests, system/migration checks, pip check and a synthetic price CSV dry run passed.

**Limits:** Comparisons are advisory and not captured/rechecked on review; normalized identity does not prove equivalence or rights, and the source URL is outside the existing price payload hash. Existing invalid rows fail current validation, but are not automatically corrected. DB work, stale indexes, concurrency, immutability and production security remain unresolved. No clinical/source verification, real data, browser/accessibility, penetration or production testing. Previous entries are historical snapshots.

## 2026-11-22 — advisory product comparisons

**Changes:** Added normalized candidate IRC index with historical backfill and controlled staging population; inconsistent indexes fail closed for preliminary review. Staff product details now show bounded source-record revision differences and normalized IRC comparison clues for other private candidates and eligible public presentations. The view explicitly excludes catalog drafts and warns about truncation, normalization uncertainty and absent IRC. No automatic match, merge or publication is performed. The full 85-test Django suite, historical migration test, local migration, system/migration checks and pip check passed.

**Limits:** Clues can be incomplete or stale, are neither identity nor rights verification, and are not snapshotted or rechecked on review. Bulk ORM/direct SQL can bypass index maintenance; production concurrency remains untested. Application row caps do not bound DB scan/sort costs. No real source data, clinical validation, browser/accessibility, penetration or production testing. Previous entries are historical snapshots.

## 2026-11-22 — private product candidate intake and triage

**Changes:** Added a separate development-only product candidate model, CSV preview/staging with explicit internal-storage attestation, submitter provenance and revision deduplication. Added Persian RTL queue, latest-review filtering, independent preliminary review and snapshot history with separate permissions. Product candidates never create or publish a catalog product. Added a fully synthetic CSV example and workflow/security tests. Local migrations, all 78 Django tests, system/migration checks and pip check passed.

**Limits:** Source rights and identity are not verified; reviews are triage only and no final approval, matching, clinical content or publication is implemented. Hashes are not signatures; bulk ORM/SQL can alter snapshots and row locking alone cannot guarantee all concurrent workflow correctness. Debug/preview, upload buffering and incomplete production controls make this suitable only for synthetic development data. No browser, penetration, concurrency or production test was performed. Previous entries are historical snapshots.

## 2026-11-22 — forward search pagination and API contract

**Changes:** Search and API now use query-bound, signed, expiring forward cursors, with a 30-result page limit and up to 150 validated candidates per request plus one lookahead. Empty pages can continue past ineligible rows. Persian UI includes continuation, clear empty and stale-cursor states. Added a bundled OpenAPI 3.0.3 document for actual public endpoints at `/api/v1/openapi.json` and automated response-shape checks. All 63 Django tests, checks, dependency checks and OpenAPI validator 0.7.2 passed; local HTTP smoke checks also passed.

**Limits:** Pagination is not snapshot-consistent; changes can skip/duplicate results or invalidate the anchor. Cursor signatures do not encrypt IDs and do not replace authorization; queries and tokens can appear in logs. the database may scan/sort more rows than the application validation limit; no public rate limiting or production load/security assessment. Source rights, clinical/price approval and real data remain absent. No browser or accessibility-device test was performed. Previous entries are historical snapshots.

## 2026-11-22 — presentation details and safer public reads

**Changes:** Added Persian RTL `/products/<id>/` and read-only `/api/v1/products/<id>/` with source, recorded review time, exact presentation fields and explicit clinical/price limitations. Search links to details; both surfaces share bounded eligibility checks, avoid invalid source URLs with embedded credentials, and omit drafts. Search inspects at most 150 candidates and returns at most 30; it cannot claim completeness. Missing, unpublished and invalid items produce the same generic 404; detail responses are noindex/no-store and excluded from the sitemap. Removed unsupported confirmation wording from the home page. Synthetic tests cover the contract and defensive cases. The full 51-test Django suite, system check, migration drift check and pip check passed; local HTTP smoke checks returned the expected search and missing-item responses.

**Limits:** Product flags and timestamps are not clinical approval or source-rights evidence; bulk database writes may bypass validation and make indexes stale. No real product data, browser/device accessibility test, security assessment or production deployment performed. Previous entries are historical snapshots.

## 2026-11-22 — development-only price staging and preliminary review

**Changes:** Added permission-gated CSV upload with preview or attested staging, authenticated submitter provenance, and a separate preliminary review permission. A different reviewer can record reasoned acceptance of a current unique match, rejection, or deferral. Records include a source snapshot and product fingerprint; sequential stale forms and inconsistent payloads fail closed. Existing/CLI candidates without a submitter cannot be reviewed here. No review publishes or approves prices. Added migrations, Persian UI and synthetic workflow tests. The full 45-test Django suite, local migration/check, migration drift check and pip check passed.

**Limits:** Source permission is only asserted; no real sources or prices were loaded. Review history is not database-immutable; direct SQL/bulk ORM bypass model guards, and the hash is not a signature. Matching can race with catalog changes without a stronger concurrency design. The staff portal remains debug-only and is not production-ready. No browser, penetration, concurrency or clinical validation was performed. Previous entries are historical snapshots.

## 2026-11-22 — development-only read-only staff queue

**Previous state:** staged price candidates were inspectable only by a local CLI; there was no session-based web access.

**Changes:** enabled Django auth and sessions; added a Persian RTL login and read-only candidate queue/detail views with scoped `pricing.view_pricecandidate` checks, status filtering, pagination and current match recalculation. Added private/no-store/noindex response headers, CSRF-protected POST logout and a hard feature gate disabling all `/staff/` endpoints outside debug mode. No accounts or passwords are seeded. Files: `daroobank/settings.py`, `daroobank/middleware.py`, `daroobank/urls.py`, `pricing/staff_views.py`, `templates/staff/`, `static/css/staff.css`, `pricing/test_staff.py` and documentation.

**Verification:** 23 existing tests passed before changes; 32 total tests passed after changes, including access control, CSRF, open redirect, escaped data, no-store, pagination and disabled-mode checks. Local Django auth/session migrations and HTTP checks were run. No external or production systems were tested. Browser/responsive accessibility tests and a penetration test were not performed.

**Limitations:** development-only; no MFA, login throttling, audited identity management, review decisions, protected approval/publishing, clinical validation or production deployment. No real source data was loaded. Debug mode and public preview URLs are unsuitable for real or sensitive data. All previous changelog entries are historical snapshots.

## 2026-11-22 — review-only price candidate staging

**Previous state:** the development application had no price ingestion or staging. It had an IRC search projection that could become inconsistent on partial model saves.

**Changes:** added an independent `pricing` Django app and migration; bounded, full-file-validated local CSV staging with explicit currency and exact Rial conversion; provenance and deduplicated candidate revisions; strict, review-only package suggestions; dry-run-by-default CLI and bounded, read-only local candidate listing. Improved and backfilled the normalized IRC index and synchronized derived search fields on partial saves. Files: `pricing/`, `catalog/models.py`, `catalog/migrations/0002_productpresentation_irc_normalized.py`, `examples/price_candidates.synthetic.csv`, settings and documentation.

**Verification:** the original 12 tests passed before changes; after changes 23 tests passed, including synthetic imports, mismatch/ambiguity, idempotency, exact conversion, rejected files and no public prices. Local migrations and a synthetic dry run were executed successfully. The example produced two unmatched records and stored none. Django system and migration checks are run separately in the final verification. No real data, source permission, clinical validation, network crawling, publication or production deployment was involved.

**Limitations:** candidates, permissions and matches are not independently verified; no authenticated admin, audit, approval, immutable database enforcement, scheduler, production data or public price/history exists. CSV storage is allowed only with appropriate rights. The initial suggestion may become stale; the listing recalculates a current suggestion but never approves it.

## 2026-11-22 — first development vertical slice

**Previous state:** repository contained architecture and research documentation only; no application, tests, database or UI existed. The prior documentation was preserved.

**Changes:**
- Added a Django 5.2 development application with migrations, `ProductPresentation`, bounded server-side Persian/Arabic/English/digit-normalized search, publication/source/date filtering, and a read-only `/api/v1/search/`. Files: `daroobank/`, `catalog/`, `manage.py`, `requirements.txt`.
- Added shared Persian RTL pages, local licensed font, responsive design tokens, honest empty/coming-soon states, no invented prices or clinical claims. Files: `templates/`, `static/`, [design system](DESIGN_SYSTEM.md).
- Added per-page metadata, home/about canonical URLs, sitemap, robots and noindex search/price pages. Website JSON-LD is descriptive, not a ranking guarantee. Files: `catalog/views.py`, `templates/base.html`.
- Added query bounding, HTML escaping, safe HTTPS source validation, GET-only views, no-store/no-referrer search responses, and a development-versus-production host/secret distinction. `ProductPresentation` does not implement reviewer approvals, audit, database-level tamper prevention or a full source-rights system; direct ORM/bulk writes can bypass model validation. Do not expose write access or treat the published flag as a governance workflow.
- Documented source usage and remaining gaps in [resource review](RESOURCE_REVIEW.md), [architecture](SYSTEM_ARCHITECTURE.md), [API](API_DESIGN.md), [security](SECURITY.md) and other existing docs.

**Verification:** `manage.py test` (12 tests), `manage.py check`, `manage.py makemigrations --check --dry-run` and local HTTP requests were run successfully. One initially incorrect test asserted that the echoed query was absent rather than inspecting results; corrected and rerun. `pip check` found no broken requirements. A 50-request single-client local empty-database development-server search smoke test measured median 8.70 ms and p95 10.52 ms; this is not representative of production or a browser performance benchmark. Django deployment checks initially found missing HSTS, HTTPS redirect and secure CSRF settings; redirect and secure cookies were added for non-debug mode, while HSTS remains deliberately unset pending a TLS/deployment policy. A browser test was attempted using temporary Playwright/Chromium, but Chromium could not start because `libnspr4.so` was unavailable; no browser, responsive-device or screen-reader test was completed. No representative load, vulnerability scanner, crawler or production tests were run. No external sites were security tested.

**Limits:** No production configuration or security sign-off; no user accounts, administration, pricing, provenance/review workflow, full relational drug model, interactions, crawler, consultation or AI. At that stage search used substring matching with a 30-result cap and no pagination, inappropriate for a large production catalog. Source records and verification flags require a future properly authorized workflow. Product identity and price publication are deliberately not automated. GET search terms can appear in server/access logs; avoid entering personal health details and implement log redaction before production.
