# Phase 1 foundation: evidence and outstanding decisions

This is a working checklist, **not** an approval, a percentage complete, a production runbook, or evidence that patient data may be used. The local application and every test dataset must remain synthetic. The Phase 1 scope and broader dependencies are in [the roadmap](ROADMAP.md); security and operational controls are described in [Security](SECURITY.md) and [Deployment](DEPLOYMENT.md).

**Status key:** `development evidence` means a limited local implementation or exercise exists, not that an operational gate has passed. `open` means a decision or implementation remains. Items can have both statuses. Owners and dates are intentionally not invented: the project must assign them.

| Area | Development evidence | Outstanding gate / evidence to collect before any production authorization |
|---|---|---|
| Architecture and hosting | ADRs and a modular Django/PostgreSQL skeleton exist. | **Open:** owners approve architecture, data classification, provider/region, legal and operational responsibilities; assess connectivity, vendor and data-residency constraints. Document decisions and exceptions. |
| Data model and migrations | Migrations and PostgreSQL-backed synthetic tests exist. | **Open:** staging upgrade and rollback plan against a representative schema, migration compatibility, tested recovery and authorization for any destructive operation. |
| API and permissions | Versioned OpenAPI and selected server-side authorization tests exist. | **Open:** complete endpoint-by-endpoint authorization review, threat modeling and independent security assessment; approve exposure and permissions for the intended deployment. |
| Staff authentication | Debug-only staff portal and opt-in synthetic IP-window limiter exist; duplicate login fields are rejected. | **Open:** MFA enrollment, recovery, revocation and replay protection; production-grade account and network abuse controls, proxy identity, alerting and independently reviewed policy. The current limiter is not a production control. See the unapproved [MFA implementation plan](MFA_IMPLEMENTATION_PLAN.md). |
| Secrets and access | Non-debug startup checks selected secret and host shapes; runtime dependencies are pinned. | **Open:** secret manager, key generation/rotation and recovery, least-privilege accounts and access review. Shape checks do not demonstrate entropy or secrecy. |
| Network and TLS | Optional proxy-scheme trust and HSTS settings exist; both are off by default. | **Open:** actual network isolation, trusted proxy configuration and header sanitization, approved hostnames, TLS issuance/renewal, HTTPS/CSRF/cookie checks and HSTS rollback plan; see ADRs 0184–0185. |
| Backups and recovery | Synthetic PostgreSQL dump/restore and encrypted-envelope negative controls exercise a limited local scenario. | **Open:** encrypted off-site backups, independent key custody, access control, retention, integrity and anti-replay/freshness policy, recovery objectives, scheduled isolated restore drills and documented owner. The synthetic test is not an operating backup service. |
| Monitoring and response | Minimal opt-in process and PostgreSQL probes exist. | **Open:** private access restrictions, network/request deadlines, monitoring, alert routing, on-call ownership, incident response and production-specific readiness checks. Probe success proves neither migrations nor recovery. |
| CI and supply chain | GitHub Actions runs development tests and selected dependency scans. | **Open:** independent review, immutable production artifacts and image digests, OS/transitive dependency review, staging/release gates and rollback. CI success is not a security certification. |
| Data and clinical governance | Only synthetic workflows and selected validation tests exist. | **Open:** qualified legal/privacy and clinical governance, source rights, retention, protected audit and explicit publication approval. No clinical or pricing accuracy is established here. |

## How to close a gate

1. Assign an accountable owner, scope, decision deadline and applicable environment; link an approved policy or decision record.
2. Capture dated, reproducible evidence and exceptions without placing secrets, patient data or sensitive infrastructure details in this repository.
3. Have the relevant independent security, operations, legal or clinical reviewer approve the evidence where applicable. A successful local test is supporting evidence only.
4. Obtain explicit authorization before provisioning or deploying production infrastructure, importing real data, or publishing clinical/price claims. Record rollback and incident ownership separately.

A working development control must not be promoted to a passed operational gate merely because it appears in this checklist. See [Testing strategy](TESTING_STRATEGY.md) for exact test scope and known gaps.
