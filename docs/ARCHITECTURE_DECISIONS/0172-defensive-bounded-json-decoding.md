# ADR 0172: defensive decoding of selected bounded JSON

Status: development-only defensive reads; no schema migration, repair, source authentication or review approval.

## Context

A 65,536-character transfer cap is not sufficient to guarantee that Python's JSON decoder can read a PostgreSQL JSONB value. Synthetic direct SQL produced valid JSONB containing a 5,000-digit integer or over 1,000 nested arrays, both below the cap. Database-driver decoding raised `ValueError` or `RecursionError` before application integrity checks, causing errors in candidate, receipt, review and identity screens.

## Decision

Selected existing candidate and review reads now return their bounded JSON as PostgreSQL text, not as an implicitly decoded JSONField. Application-side decoding limits integer literals to 128 digits and catches decoding and recursion failures. The existing schemas require bounded identifiers and numbers and shallow structured fields; no valid supported integer approaches this limit. Values that cannot be decoded for inspection become `None`, as does JSON null. Existing validators reject this as an invalid/inconsistent candidate or snapshot, suppress its details, and use unknown for comparisons. The original database value is not changed. Values over the transfer cap retain the distinct oversized/uninspected status; ordinary valid values and JSON null retain their prior behavior.

This affects selected candidate queue, detail, review, comparison, staging replay and CLI reads; joined receipt candidates; product/price review scans; and selected review histories, scans and identity revision reads. It does not cover every JSON read, arbitrary database backends or decoder configuration. The text cap is not a byte/memory/CPU bound and does not limit PostgreSQL work, decompression, other columns, other writers or malicious access. The invalid status describes incompatibility with this inspection path, not invalid PostgreSQL JSON, authenticity, consent, or clinical correctness.

## Evidence

On synthetic PostgreSQL, tests insert huge integers and deeply nested JSONB directly, then exercise private candidate queues/details/scans, the price CLI, locked review and replay conflicts, four review domains, both receipt joins and identity revision; payloads and review reasons are not echoed in the selected paths. Existing valid, null, boundary, SQL, sentinel, conflict, browser and optimized-Python regressions supplement these cases. This is not a complete robustness or security audit.
