# ADR 0018: bounded synthetic clinical draft parent-path inspection

Status: development-only implementation, 22 November 2026; extends [ADR 0005](0005-clinical-draft-triage.md).

## Decision

Provide a read-only path inspector at `/staff/clinical/<id>/lineage/`, accessible from the draft detail even when the selected draft is inconsistent. The web route uses the existing DEBUG-only gate, private headers and active staff with `clinical.view_clinicaldraft`; the underlying service also enforces this permission, but not the web gate. It displays only IDs and relative step counts for successfully checked immediate-parent links, not text, reasons, source URLs, authors or raw hashes. It follows the one recorded parent path, not child branches; no records, review states, references or publication are changed.

Each request examines at most 20 parent links in descending ID order, applying the same payload and immediate-parent checks as `valid_draft`. An inconsistent or missing parent stops the traversal before showing that link. On subsequent reads within the same request, the current node's validated payload hash is compared with the previously observed parent hash, detecting that seam changing; the last checked parent determines if a continuation is needed. An absent recorded parent is not proof of origin or completeness. With permissions already cached, a first page uses at most 20 draft SELECTs and a continuation at most 21; authentication/permission queries are additional. Row count does not bound bytes, database work or response time.

Continuation tokens are signed, limited to 1024 characters, time-limited to one hour, and bind anchor/current IDs, depth and keyed digests of the validated payload hashes. The anchor and continuation payloads are rechecked when resuming, and permission is checked on every request. Invalid, expired, altered or stale cursors produce a generic private non-reflecting 400 with a local restart link. Tokens are signed, not encrypted: IDs and keyed digests are visible, and the URL may be logged. A token is not an authorization grant or a confidentiality mechanism.

## Limits

Queries and pages are not a consistent snapshot: a concurrent or out-of-band change can occur after a check, and earlier links are not rechecked on continuation. Revalidating anchor and continuation payloads and checking seams does not certify earlier pages. Hashes are unkeyed internal consistency checks, not signatures; privileged writers can bypass model guards or recompute them. No check proves authenticity, identity, scientific correctness, source rights, reviewer qualifications, approval, full ancestry or completeness. Authors, supplementary references and review histories are not validated here. There is no repair, global branch listing, automatic approval, production monitoring or publication. Only synthetic non-sensitive data may be used; clinical, legal, security and real-device accessibility review remain necessary.
