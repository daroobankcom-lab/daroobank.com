# Security and privacy strategy

Django escaping, HTTPS source validation, bounded queries and basic security headers are implemented and tested in the development slice. A limited same-origin content-security policy is enforced on Django responses, with explicit exceptions and important deployment limitations described in [ADR 0121](ARCHITECTURE_DECISIONS/0121-development-content-security-policy.md). Most controls below remain proposed; these are not proof of compliance or production readiness. Iranian legal, professional, data residency and telehealth obligations require advice from qualified local counsel and review by clinical governance before handling patient data or launching consultations.

## Threats and access

Protect against unauthorized price/content changes, account takeover, source poisoning, malicious uploads, PHI leakage, API abuse, privilege escalation and supply-chain compromise. Default deny; server-side object-level authorization and separation of author/reviewer. Users may hold multiple roles; implement auditable permission grants, revocation and periodic review.

| Role | Proposed scope; not automatically granted |
|---|---|
| Super administrator | Manage roles/security configuration; no automatic clinical approval bypass. |
| Database administrator | Operate backups and database, not editorial publication by default. |
| Content editor | Draft/submit clinical content, not approve own work. |
| Pharmacist/medical reviewer | Review/approve clinical content within qualification, not own drafts. |
| Pricing administrator / verifier | Review prices, source evidence and corrections within assigned scope. |
| Crawler operator | Run/pause/retry jobs and configure schedules, no clinical approval. |
| Consultation professional | Access only assigned, consented consultations after verified licensure; disabled initially. |
| Registered user | Own profile and future consented records only; no admin data. |

## Controls

MFA for administrators, secure sessions, CSRF, Argon2-compatible password hashing, rate limits, lockout/recovery controls and scoped expiring API credentials. TLS in transit; encryption at rest where appropriate with isolated managed keys and rotation; least-privilege DB/worker credentials. Validate inputs and sanitize display; CSP, security headers, safe dependencies, restricted egress and bounded uploads with malware scanning and private storage. Keep secrets in a secrets manager/environment, never in Git; the existing `.env.example` contains placeholders only.

Audits record actor, role, target, before/after versions or hashes, decision, time and request correlation, without PHI in general logs. Protect audit from modification by application roles and monitor unauthorized access. Separate production and non-production data; synthetic data only in tests. Backups encrypted, access controlled and regularly restore-tested.

## Known staff-session revocation gap

In the development portal, disabling an account or removing its staff flag denies selected requests while that state remains in effect, but reactivation or regranting staff can make the same unexpired session usable again. This is **not durable revocation**. A synthetic password-change test invalidates an old session on its next request, but does not establish an operational incident procedure or cover all authentication backends and races. See [ADR 0191](ARCHITECTURE_DECISIONS/0191-staff-session-revocation-gap.md); account lifecycle and session revocation remain production blockers.

## Privacy and incident response

Data minimization and purpose limitation; record consent, role access, legal basis, retention and deletion/withdrawal policy with legal review. Do not put PHI in metrics, search URLs, errors or analytics. Segregate consultation data, apply per-case access and audit, and do not record audio/video by default; recording requires explicit consent and legal justification. Define incident severity, containment, notification and recovery owners before launch. Retention periods and deletion exceptions are pending legal decision, not invented here. See [runbook](OPERATIONS_RUNBOOK.md).

## Actual development-slice review

`catalog/tests.py` tests XSS escaping, published-only filtering, invalid source URL rejection and GET-only methods. A development-only staff queue, bounded CSV upload, preliminary review and Django session login now exist; no production admin or patient-record feature exists. Django development server and local database, default dev secret and permissive development preview hosts are not production controls. Source validation and a boolean flag can be bypassed by bulk writes or database access; no production write path should be enabled until transactional authorization, provenance, immutable audit, separation of duties and DB constraints are implemented. Search terms can appear in server/access logs; do not enter PHI and configure logging/redaction before production. No Strix/BugHunter scan or third-party penetration test was run.

## Local staging security limitations

`stage_price_csv` is a command-line development tool, not an authenticated or authorized administration interface. `--attest-authorized` is not evidence of a legal right, user identity or approval. It restricts file size, row count, field names, HTTPS source URLs and source URL credentials/query strings, but cannot determine whether a source is legitimate. Only validated selected fields are persisted; operators must exclude PHI, credentials and unlicensed data. Restrict local DB, console and file access; CLI listing can expose source fields. Direct database/ORM edits bypass staging validation and append-only expectations. Before any production data use or public publication, implement access control, durable audit, source-rights governance, human review, retention, backups and independent security review.

## Opt-in synthetic login throttle

The debug-only staff login can optionally use a shared PostgreSQL per-server-address fixed-window limiter with `DAROOBANK_STAFF_LOGIN_THROTTLE=1`. It is disabled by default and outside debug, is not MFA or production protection, ignores forwarded client headers, and may block users sharing a proxy. Old pseudonymous rows require explicit synthetic-only maintenance; no scheduler or cardinality cap exists. See [ADR 0181](ARCHITECTURE_DECISIONS/0181-development-staff-login-throttle.md) before enabling it.

## Development staff queue

`/staff/` is disabled unless debug mode is enabled. In debug mode the queue and its detail page require an active authenticated staff account with `pricing.view_pricecandidate`; neither grants editing, approval or publication. Login/logout use Django session authentication and CSRF. The staff login form refuses nonstaff users with a generic visible error, but does not revoke existing sessions or change other authentication paths; each destination must still check active/staff status and its own permissions. See [ADR 0048](ARCHITECTURE_DECISIONS/0048-development-staff-login-policy.md). Session cookies are HttpOnly, SameSite=Lax, browser-session-scoped and expire after one hour. Staff responses, including redirects and errors, are marked private/no-store/noindex, and the `same-origin` referrer policy suppresses referrers to other origins; same-origin requests can carry private paths or query strings in their Referer header and server logs. Do not use sensitive or real data. This policy permits same-origin CSRF-protected form submissions in Chromium; `no-referrer` caused an `Origin: null` rejection. Non-debug configuration uses secure session/CSRF cookies and HTTPS redirects. The slashless `/staff` root is covered by the same development gate and headers, and known slashless public search/product paths get their public privacy headers, including append-slash redirects. Known-path redirects generated early by Django's HTTPS enforcement also receive those headers; this does not change redirect or gate ordering. Redirects retain the query string, and upstream proxies and logging remain outside these headers; see [ADR 0044](ARCHITECTURE_DECISIONS/0044-slashless-privacy-boundaries.md).

This is **not a production security model**. No MFA, throttling, account lockout, password reset flow, tamper-resistant audit trail, staff provisioning workflow or production permissions review exists. Debug error pages and public preview URLs may expose sensitive data; use synthetic data and development-only accounts. Portal activation must remain disabled until those gaps, source permissions and a security review are addressed. CLI/DB access is separate from web permissions and must be controlled by the operating system.

## Development-only staged price review risks

Price upload requires view and add permissions, explicit source-rights attestation to write, complete CSV validation and CSRF. Review requires separate view/review permissions and a different authenticated submitter; older/CLI entries without an actor fail closed. Events retain snapshots but are not database-immutable: bulk ORM writes and SQL bypass model guards. Hashes are not signatures and the source URL is outside the candidate payload hash. Rights are asserted, not verified. The application upload size check happens after Django receives the request; production needs request limits, safe temporary storage and malware handling. PostgreSQL locks selected rows but product-match queries do not prevent concurrent matching insertions; conflict checks are not a concurrency guarantee. Treat all this as synthetic development functionality only, and design/test a hardened production authorization, isolation, audit and source-governance system before real use.

## Presentation read surface

HTML and JSON details share search's eligibility checks and reject unpublished, undated, incomplete or invalid-source records, including HTTPS URLs with embedded userinfo. Read-side checks reject selected control/surrogate characters in public display fields but do not constitute complete Unicode spoofing protection; see [ADR 0045](ARCHITECTURE_DECISIONS/0045-public-display-control-characters.md). Read-side checks cannot establish source legitimacy, rights or content accuracy and do not repair stale search indexes caused by bulk writes. Source URLs, including query parameters, are public; operators must not store secrets or personal information there. Detail pages are deliberately noindex/no-store, not a security boundary for published data. No third-party assessment or production release is implied.

## Search cursors

Forward cursors are size-limited, timestamped and signed with the Django secret, tied to the normalized query and anchor identity, and expire after one hour. Raw queries and anchor names are not embedded: keyed digests are used, but an anchor ID remains visible. Signed tokens are not encrypted and do not provide authorization. Secret rotation, anchor deletion or changes can invalidate a cursor. Search terms and cursors can still appear in access logs; avoid personal health data and implement redaction. Application candidate validation is bounded but PostgreSQL can still scan/sort a large table, and there is no public rate limiting or production load/security assessment.

## Development product intake and review

The `/staff/products/` queue, upload and review use separate catalog permissions and the existing debug-only staff gate. Upload validates 1 MiB/1,000-row files, stores only listed structured fields, requires a source-rights assertion for staging and does not create or publish a product. Review requires a different authenticated submitter and separate permission; data integrity and sequential stale forms are checked. Source URLs are included in the candidate fingerprint. Neither the fingerprint nor the actor/rights snapshot provides tamper-proof evidence; model guards are bypassable by bulk writes and SQL. PostgreSQL locks selected rows, but simultaneous changes across the workflow are not proven safe. File limits are applied after Django receives the request; do not use real or sensitive data in the publicly reachable debug preview. Source permission, clinical review, production authorization, audit, anti-malware, request limits and independent security review remain required.

## Advisory product comparisons

Candidate comparison is available only behind the existing staff candidate-view permission and debug gate. Candidate details are already visible to that role; only eligible public presentations are included, not unpublished catalog records. Source values remain escaped and current-candidate inconsistencies suppress comparison. Ten rows per category are inspected, with truncation and skipped-invalid warnings. Neither this bound nor the index prevents database scan/sort costs, denial of service or stale data; direct/bulk writes can make indexes inconsistent or hide rows. The comparison is not rechecked or recorded when the preliminary review is submitted, so it is not a concurrency, identity, authorization or approval control. No network request is made and no security assessment or source-rights determination has been performed.

## Price comparison and suggestion safeguards

Price revision comparison is behind the existing staff-view permission and debug gate. It is limited to 10 other records with the exact source URL/ID, and verifies candidate structure and derived amounts before calculating any difference. It requires matching nonempty normalized identity fields, source name, category and unit; this is not proof of identity or rights. The URL is not covered by the existing price payload hash. Comparisons are live, not snapshotted or rechecked by review. Price matching rejects malformed/normalization-empty identifiers and treats more than 100 same-IRC indexed presentations as ambiguous, not a unique match. Stale indexes, direct DB writes, concurrent changes and DB scan/sort costs remain unresolved; no rate-limit, production security or source-rights validation follows from these safeguards.


## Development-only source assertions

The `/staff/sources/` portal is disabled outside debug mode and requires an active staff account with `sources.view_sourceclaim`. Adding a claim also requires `sources.add_sourceclaim`; independently reviewing another user's claim requires `sources.review_sourceclaim` plus view. CSRF and staff privacy headers apply. Product and price details do not expose claim data to users without the separate source view permission. Source and evidence URLs reject credentials, query and fragment, but users can still enter sensitive text elsewhere; use only synthetic data in this debug portal. The server does not fetch URLs. The ledger is not an authorization gate, source verification, a legal decision or an audit system. Its hashes omit actor/time and provide no signature; bulk ORM/SQL bypass model guards, and full concurrent review behavior is unproven. Existing production-security gaps, MFA, throttling, tamper-resistant audit and legal review remain prerequisites.


## Window inspection and shared validation

The development-only schedule page is GET/HEAD-only, uses the normal privacy/debug gate and requires active staff with at least one product, price or source view permission. It performs no source/network operation, settings write or dispatch. The local management command bypasses web authorization, so restrict OS access; it likewise only computes. Timezone boundaries are rejected if ambiguous or nonexistent. The utility relies on host clock/tzdata and does not authorize ingestion. The shared private-intake URL validator rejects empty credential markers, query/fragment delimiters (including empty ones), controls and invalid Unicode. It is not an SSRF safety policy or network authorization, and existing public presentation URL behavior is separate. Invalid control/surrogate characters in new review reasons are rejected. Bulk ORM/SQL still bypasses service validation.


## Development-only web intake receipts

Successful web product/price staging and its receipt use one database transaction. Read access is scoped by the corresponding candidate view permission, with domain filtering before count, pagination and detail lookup; source-only users have no receipt access. The staff debug gate, private headers and CSRF-protected staging still apply. Receipt source URL and actor are unverified assertions; no raw file, filename or file-level hash is retained. New receipt manifests retain source record IDs, candidate hashes and references; this is additional sensitive metadata and must remain synthetic in this debug system. Preview, failure, CLI/original-importer and imports before receipts have no receipt; earlier receipts have no row manifest, so this is not a complete or tamper-resistant audit. Local code can call the receipt wrappers directly with an authorized user, outside the web debug gate; restrict OS and database access. Bulk ORM/SQL bypass guards, permissions can be modified without audit and production concurrency/crash safety is not established. Do not use real source data or credentials in the debug portal.


Row manifests are domain-scoped through the receipt lookup; structural and per-row checks suppress inconsistent links, but do not establish authenticity or integrity against a database writer. Candidate pages show at most five recent distinct same-domain receipt clues; their presence/absence proves nothing about source rights or complete history. Foreign keys use `PROTECT`; `QuerySet.update/delete` and SQL still bypass model guards, and retention/deletion/repair remain undefined. Price hashes omit source URL. No real personal or proprietary data should be entered into this debug workflow.


## Development-only clinical drafts

The clinical queue and its create/revise/review routes are under the normal debug-only staff gate and use separate `clinical.view_clinicaldraft`, `clinical.add_clinicaldraft` and `clinical.review_clinicaldraft` permissions. Review also requires view and a reviewer distinct from the draft author and all current supplementary-reference recorders. CSRF and private/no-store/noindex and same-origin referrer headers apply (private URLs can reach same-origin logs, not external sites); source-claim hints require independent source view permission. The form's synthetic-data checkbox is an assertion; the app cannot prevent a user from entering patient or copyrighted information, and direct services bypass the web debug gate. Use only isolated synthetic data. URLs are validated but never fetched. Draft hashes omit author/time and are not signatures; bulk ORM/SQL can alter history and full concurrency behavior is not proven. Review is not approval; no public clinical route or publication exists. Qualified review, retention, privacy, durable audit and production security remain unresolved.


Supplementary clinical assertions use the same separate clinical view/add permissions and the normal staff CSRF/debug/private gates. No source is fetched. New review snapshots contain the bounded supplementary reference metadata and recorder IDs; access and retention need consideration even though the development portal must only contain synthetic data. Sequential evidence-set mismatches, malformed snapshots and over-limit assertion sets fail closed in the application, but assertion payload hashes do not cover recorder/time, while set hashes include recorder IDs but not timestamps; neither is a signature. PostgreSQL row locks do not protect direct writes, and bulk ORM/SQL bypasses prevent claims of tamper-resistant audit. Direct service calls are outside the web debug gate.


## Development catalog quality inspector

The DEBUG-only `/staff/catalog/quality/` requires an active staff user with `catalog.view_productpresentation`, separate from candidate permissions, and applies staff privacy headers. It reveals IDs, technical flags and diagnostic codes for both published and unpublished presentations, not their raw names or URLs. The read-only management command and Python service operate outside the web gate and do not enforce user permissions. Use only synthetic local data and avoid logging/sharing reports. The inspector is a bounded diagnostic, not an authorization, audit, sanitization, identity, rights or clinical check; it neither repairs records nor changes public eligibility. Scans are not consistent snapshots or production load guarantees. See [ADR 0008](ARCHITECTURE_DECISIONS/0008-catalog-quality-inspection.md).


## Cooperative staging locks

Product and price committed CSV staging uses PostgreSQL transaction advisory locks keyed by domain and exact source URL; previews do not lock. Receipt/manifest writes are inside the outer transaction. Only writers using the current services participate; older processes, ORM bulk operations and SQL can bypass the protocol. A long transaction or callback can make other same-source requests wait, and the service does not set a lock timeout or retry policy. Selected PostgreSQL concurrency errors are translated after staging/receipt rollback into a generic conflict; connection loss and later enclosing-transaction commit remain outside this boundary. See [ADR 0055](ARCHITECTURE_DECISIONS/0055-staging-conflict-boundary.md). This protects neither source authorization nor matching against concurrent catalog changes, and does not create immutable or exactly-once audit records. See [ADR 0010](ARCHITECTURE_DECISIONS/0010-staging-concurrency.md).


## Indexed IRC inspection

The DEBUG-only indexed IRC clue page uses `catalog.view_productpresentation` and can reveal IDs and status for unpublished presentations; group permissions apply. It does not intentionally render source names, URLs or IRC values. Its signed cursor contains IDs and a keyed digest; it is not encrypted, not an access grant and can be guessable when a known debug secret protects low-entropy codes. Cursor URLs may be logged. The local command/service operate outside the web gate. A stale or corrupt index can hide matching records and results are not a snapshot, evidence, authorization or identity verification; use synthetic data only. See [ADR 0011](ARCHITECTURE_DECISIONS/0011-indexed-irc-inspection.md).


## Synthetic identity drafts

The development-only staff identity workspace uses independent view/add/review permissions, CSRF and staff privacy headers. Full current source assertions and internally consistent historical graph snapshots are visible to authorized viewers; the checkbox does not prevent sensitive input. History pages are package-scoped and permission-checked; their ID cursor is not a secret or an access grant and pages are not a snapshot. Historical comparisons and internal hash checks do not establish authenticity; review reasons, decisions and timestamps are not covered by the graph hash. Direct service calls are outside the web gate. Never use real patient or proprietary data. A joined component read reduces redundant graph queries but does not isolate the full graph; stale caller objects or out-of-band writes can still affect reads. Locks coordinate same-package review service calls; hashes and model guards are not tamper-proof, bulk ORM/SQL bypass them and out-of-band writes can race. No clinical, identity or production security approval is implied. See [ADR 0012](ARCHITECTURE_DECISIONS/0012-synthetic-identity-drafts.md).


## Synthetic package correction links

The development-only correction form requires identity view/add permissions, CSRF and synthetic-data acknowledgment. Authorized viewers may see correction reasons, author IDs and linked synthetic graphs. Graph/link hashes do not authenticate them, and direct ORM bulk/SQL can bypass constraints or recompute hashes. A parent row lock and latest-review/graph preconditions coordinate only current review/revision services; stale reads and uncooperative writers remain possible. Only immediate links are checked, not ancestry, and package review does not cover correction provenance. Direct services do not enforce the web gate or checkbox. No PHI or real proprietary data. See [ADR 0013](ARCHITECTURE_DECISIONS/0013-synthetic-package-revisions.md).


## Synthetic ingredient, formulation and product corrections

These typed private corrections require identity view/add permission, the debug-only web gate, CSRF and synthetic-data acknowledgment. Visible link reasons and parent/child graphs must be nonconfidential. Hashes are not signatures, and ordinary model guards, dependency checks and cooperative locks can be bypassed by bulk ORM/SQL or uncooperative writers. Checks cover only immediate links; package reviews do not certify correction provenance or earlier authors. Service calls do not enforce the web gate or acknowledgment. See [ADR 0014](ARCHITECTURE_DECISIONS/0014-synthetic-component-revisions.md).


## Synthetic identity ancestry inspection

The development-only read-only parent-path page requires identity view permission and staff privacy headers. It intentionally shows IDs and link status, not names, source fields or change reasons. Signed, time-limited cursors contain IDs and keyed digests, are not encrypted or access grants, and may be logged; direct service calls are outside the web gate. Earlier sections are not revalidated during continuation, and coherent graphs or links can be fabricated by a privileged writer. Do not enter real patient or proprietary data or treat the inspection as identity, clinical or audit approval. See [ADR 0015](ARCHITECTURE_DECISIONS/0015-synthetic-lineage-inspection.md).
