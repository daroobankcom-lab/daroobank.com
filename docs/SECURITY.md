# Security and privacy strategy

Django escaping, HTTPS source validation, bounded queries and basic security headers are implemented and tested in the development slice. Most controls below remain proposed; these are not proof of compliance or production readiness. Iranian legal, professional, data residency and telehealth obligations require advice from qualified local counsel and review by clinical governance before handling patient data or launching consultations.

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

## Privacy and incident response

Data minimization and purpose limitation; record consent, role access, legal basis, retention and deletion/withdrawal policy with legal review. Do not put PHI in metrics, search URLs, errors or analytics. Segregate consultation data, apply per-case access and audit, and do not record audio/video by default; recording requires explicit consent and legal justification. Define incident severity, containment, notification and recovery owners before launch. Retention periods and deletion exceptions are pending legal decision, not invented here. See [runbook](OPERATIONS_RUNBOOK.md).

## Actual development-slice review

`catalog/tests.py` tests XSS escaping, published-only filtering, invalid source URL rejection and GET-only methods. A development-only staff queue, bounded CSV upload, preliminary review and Django session login now exist; no production admin or patient-record feature exists. Django development server/SQLite, default dev secret and permissive development preview hosts are not production controls. Source validation and a boolean flag can be bypassed by bulk writes or database access; no production write path should be enabled until transactional authorization, provenance, immutable audit, separation of duties and DB constraints are implemented. Search terms can appear in server/access logs; do not enter PHI and configure logging/redaction before production. No Strix/BugHunter scan or third-party penetration test was run.

## Local staging security limitations

`stage_price_csv` is a command-line development tool, not an authenticated or authorized administration interface. `--attest-authorized` is not evidence of a legal right, user identity or approval. It restricts file size, row count, field names, HTTPS source URLs and source URL credentials/query strings, but cannot determine whether a source is legitimate. Only validated selected fields are persisted; operators must exclude PHI, credentials and unlicensed data. Restrict local DB, console and file access; CLI listing can expose source fields. Direct database/ORM edits bypass staging validation and append-only expectations. Before any production data use or public publication, implement access control, durable audit, source-rights governance, human review, retention, backups and independent security review.

## Development staff queue

`/staff/` is disabled unless debug mode is enabled. In debug mode the queue and its detail page require an active authenticated staff account with `pricing.view_pricecandidate`; neither grants editing, approval or publication. Login/logout use Django session authentication and CSRF; session cookies are HttpOnly, SameSite=Lax, browser-session-scoped and expire after one hour. Staff responses, including redirects and errors, are marked private/no-store/noindex, and referrers are suppressed. Non-debug configuration uses secure session/CSRF cookies and HTTPS redirects.

This is **not a production security model**. No MFA, throttling, account lockout, password reset flow, tamper-resistant audit trail, staff provisioning workflow or production permissions review exists. Debug error pages and public preview URLs may expose sensitive data; use synthetic data and development-only accounts. Portal activation must remain disabled until those gaps, source permissions and a security review are addressed. CLI/DB access is separate from web permissions and must be controlled by the operating system.

## Development-only staged price review risks

Price upload requires view and add permissions, explicit source-rights attestation to write, complete CSV validation and CSRF. Review requires separate view/review permissions and a different authenticated submitter; older/CLI entries without an actor fail closed. Events retain snapshots but are not database-immutable: bulk ORM writes and SQL bypass model guards. Hashes are not signatures and the source URL is outside the candidate payload hash. Rights are asserted, not verified. The application upload size check happens after Django receives the request; production needs request limits, safe temporary storage and malware handling. SQLite does not enforce `select_for_update` row locks, and product-match queries do not prevent concurrent matching insertions; conflict checks are not a concurrency guarantee. Treat all this as synthetic development functionality only, and design/test a hardened production authorization, isolation, audit and source-governance system before real use.

## Presentation read surface

HTML and JSON details share search's eligibility checks and reject unpublished, undated, incomplete or invalid-source records, including HTTPS URLs with embedded userinfo. Read-side checks cannot establish source legitimacy, rights or content accuracy and do not repair stale search indexes caused by bulk writes. Source URLs, including query parameters, are public; operators must not store secrets or personal information there. Detail pages are deliberately noindex/no-store, not a security boundary for published data. No third-party assessment or production release is implied.

## Search cursors

Forward cursors are size-limited, timestamped and signed with the Django secret, tied to the normalized query and anchor identity, and expire after one hour. Raw queries and anchor names are not embedded: keyed digests are used, but an anchor ID remains visible. Signed tokens are not encrypted and do not provide authorization. Secret rotation, anchor deletion or changes can invalidate a cursor. Search terms and cursors can still appear in access logs; avoid personal health data and implement redaction. Application candidate validation is bounded but SQLite can still scan/sort a large table, and there is no public rate limiting or production load/security assessment.

## Development product intake and review

The `/staff/products/` queue, upload and review use separate catalog permissions and the existing debug-only staff gate. Upload validates 1 MiB/1,000-row files, stores only listed structured fields, requires a source-rights assertion for staging and does not create or publish a product. Review requires a different authenticated submitter and separate permission; data integrity and sequential stale forms are checked. Source URLs are included in the candidate fingerprint. Neither the fingerprint nor the actor/rights snapshot provides tamper-proof evidence; model guards are bypassable by bulk writes and SQL. `select_for_update` is ineffective as a row lock on SQLite and simultaneous changes are not proven safe. File limits are applied after Django receives the request; do not use real or sensitive data in the publicly reachable debug preview. Source permission, clinical review, production authorization, audit, anti-malware, request limits and independent security review remain required.

## Advisory product comparisons

Candidate comparison is available only behind the existing staff candidate-view permission and debug gate. Candidate details are already visible to that role; only eligible public presentations are included, not unpublished catalog records. Source values remain escaped and current-candidate inconsistencies suppress comparison. Ten rows per category are inspected, with truncation and skipped-invalid warnings. Neither this bound nor the index prevents database scan/sort costs, denial of service or stale data; direct/bulk writes can make indexes inconsistent or hide rows. The comparison is not rechecked or recorded when the preliminary review is submitted, so it is not a concurrency, identity, authorization or approval control. No network request is made and no security assessment or source-rights determination has been performed.

## Price comparison and suggestion safeguards

Price revision comparison is behind the existing staff-view permission and debug gate. It is limited to 10 other records with the exact source URL/ID, and verifies candidate structure and derived amounts before calculating any difference. It requires matching nonempty normalized identity fields, source name, category and unit; this is not proof of identity or rights. The URL is not covered by the existing price payload hash. Comparisons are live, not snapshotted or rechecked by review. Price matching rejects malformed/normalization-empty identifiers and treats more than 100 same-IRC indexed presentations as ambiguous, not a unique match. SQLite locking, stale indexes, direct DB writes, concurrent changes and DB scan/sort costs remain unresolved; no rate-limit, production security or source-rights validation follows from these safeguards.


## Development-only source assertions

The `/staff/sources/` portal is disabled outside debug mode and requires an active staff account with `sources.view_sourceclaim`. Adding a claim also requires `sources.add_sourceclaim`; independently reviewing another user's claim requires `sources.review_sourceclaim` plus view. CSRF and staff privacy headers apply. Product and price details do not expose claim data to users without the separate source view permission. Source and evidence URLs reject credentials, query and fragment, but users can still enter sensitive text elsewhere; use only synthetic data in this debug portal. The server does not fetch URLs. The ledger is not an authorization gate, source verification, a legal decision or an audit system. Its hashes omit actor/time and provide no signature; bulk ORM/SQL bypass model guards, and SQLite row locking/concurrent reviews are unproven. Existing production-security gaps, MFA, throttling, tamper-resistant audit and legal review remain prerequisites.
