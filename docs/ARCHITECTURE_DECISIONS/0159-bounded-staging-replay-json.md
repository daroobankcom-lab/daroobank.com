# ADR 0159: bound candidate JSON on staging replay

Status: development-only defense for synthetic inputs; no schema or input-validation policy change.

## Decision

Product and price CSV staging find or create a candidate by its existing key and, on duplicates, reread and compare it under a row lock. Both the first lookup and locked reread previously selected the whole stored `source_fields` JSON. A bypassed write can make that JSON arbitrarily large. The initial `get_or_create` now selects only the primary key of an existing row; a newly created row still uses the validated input. The duplicate reread keeps the existing lock and uses the 65,536-character PostgreSQL JSON-text transfer bound (ADR 0156). It rejects an oversized existing value as a staging conflict before comparing any partial data. A valid intake row has much smaller per-field limits, so a value beyond this bound cannot equal that row. No prefix is treated as a complete value. Other mismatches, unavailable rows, existing account checks, actorless price CLI replay, transaction rollback, per-request outcomes, receipt creation, and lock order are unchanged.

The pre-lock ID is not a stable content check; only the reread under the row lock is authoritative for the fields it checks. A concurrent mutation between those operations can still occur and is rechecked. The selected transfer bound is not a bound on database work or decompression, all fields, other endpoints or bypass writes. It establishes neither authenticity nor source rights or clinical validity.

## Evidence

Synthetic PostgreSQL tests inspect both query shapes, check rollback after an earlier insert and after a same-request callback mutation, cover the private HTTP conflict, and confirm no partial receipt is created. Existing replay tests, including a selected interleaving that changes a row after pre-lock lookup, remain in place; explicit oversized variants exercise both domains. Test injection hooks were moved to the new lookup helper without changing the tested rollback or concurrency scenarios. Chromium checks the two conflict screens at one selected width; this is not comprehensive accessibility testing.
