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

MFA for administrators, secure sessions, CSRF, Argon2-compatible password hashing, rate limits, lockout/recovery controls and scoped expiring API credentials. TLS in transit; encryption at rest where appropriate with isolated managed keys and rotation; least-privilege DB/worker credentials. Validate inputs and sanitize display; CSP, security headers, safe dependencies, restricted egress and bounded uploads with malware scanning and private storage. Keep secrets in a secrets manager/environment, never in Git; an `.env.example` containing placeholders only should be added when runtime configuration actually exists.

Audits record actor, role, target, before/after versions or hashes, decision, time and request correlation, without PHI in general logs. Protect audit from modification by application roles and monitor unauthorized access. Separate production and non-production data; synthetic data only in tests. Backups encrypted, access controlled and regularly restore-tested.

## Privacy and incident response

Data minimization and purpose limitation; record consent, role access, legal basis, retention and deletion/withdrawal policy with legal review. Do not put PHI in metrics, search URLs, errors or analytics. Segregate consultation data, apply per-case access and audit, and do not record audio/video by default; recording requires explicit consent and legal justification. Define incident severity, containment, notification and recovery owners before launch. Retention periods and deletion exceptions are pending legal decision, not invented here. See [runbook](OPERATIONS_RUNBOOK.md).

## Actual development-slice review

`catalog/tests.py` tests XSS escaping, published-only filtering, invalid source URL rejection and GET-only methods. No admin, authentication, upload or patient-record feature exists to audit. Django development server/SQLite, default dev secret and permissive development preview hosts are not production controls. Source validation and a boolean flag can be bypassed by bulk writes or database access; no production write path should be enabled until transactional authorization, provenance, immutable audit, separation of duties and DB constraints are implemented. Search terms can appear in server/access logs; do not enter PHI and configure logging/redaction before production. No Strix/BugHunter scan or third-party penetration test was run.
