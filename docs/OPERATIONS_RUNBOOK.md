# Operations runbook

This is a prospective checklist; no services, dashboards, alerts or on-call rotation currently exist. Create concrete commands, owners and escalation contacts before production.

## Source or worker incident

1. Confirm source health and rights/expiry, inspect run status, counts, pagination coverage, checkpoints and sanitized errors. Distinguish partial, failed and complete runs.
2. Pause the affected source and disable automated publication on schema drift, unexpected empty data, price/currency anomalies or permission uncertainty. Do not delete products or change approved prices due to absent records. Keep last verified data with freshness warning.
3. Escalate to data steward/source owner. Fix adapter against authorized fixtures, rerun in staging, then explicitly resume from a safe checkpoint. Verify idempotency, complete coverage and candidate review. Record incident, remediation and approvals.

## Bad price or clinical claim

Withdraw or supersede the publication through an authorized auditable decision; preserve original evidence and history. Invalidate caches, record affected scope and time, notify clinical lead and affected users where legally appropriate, investigate root cause and correct only with evidence. Never silently rewrite history. For serious harm risk escalate through the clinical incident protocol.

## Restore and recovery

Before deployment, define ownership, encrypted backup cadence, off-host retention, RPO/RTO and recovery environment according to business and legal requirements; no values have been approved. Test restoring database and authorized objects together, permissions, audit integrity, point-in-time consistency and application compatibility. Record actual restore duration and recovery point; conduct periodic drills. If queue state is lost, use DB checkpoints and idempotent replay rather than treating broker as audit source.

## Security/privacy incident

Contain, preserve evidence, restrict access/rotate exposed credentials and engage security, legal and clinical owners. Assess PHI exposure and regulatory notification duties with qualified counsel; keep sensitive data out of incident tickets. Verify recovery and review access/audit logs after restoration. Define the on-call chain before enabling patient accounts.
