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

## Development-only staged review risks

Upload requires view and add permissions, explicit source-rights attestation to write, complete CSV validation and CSRF. Review requires separate view/review permissions and a different authenticated submitter; older/CLI entries without an actor fail closed. Events retain snapshots but are not database-immutable: bulk ORM writes and SQL bypass model guards. Hashes are not signatures and the source URL is outside the candidate payload hash. Rights are asserted, not verified. The application upload size check happens after Django receives the request; production needs request limits, safe temporary storage and malware handling. SQLite does not enforce `select_for_update` row locks, and product-match queries do not prevent concurrent matching insertions; conflict checks are not a concurrency guarantee. Treat all this as synthetic development functionality only, and design/test a hardened production authorization, isolation, audit and source-governance system before real use.

## Presentation read surface

HTML and JSON details share search's eligibility checks and reject unpublished, undated, incomplete or invalid-source records, including HTTPS URLs with embedded userinfo. Read-side checks cannot establish source legitimacy, rights or content accuracy and do not repair stale search indexes caused by bulk writes. Source URLs, including query parameters, are public; operators must not store secrets or personal information there. Detail pages are deliberately noindex/no-store, not a security boundary for published data. No third-party assessment or production release is implied.
