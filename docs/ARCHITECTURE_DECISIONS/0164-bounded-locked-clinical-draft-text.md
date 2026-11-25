# ADR 0164: bounded locked clinical draft text

Status: development-only writer defense for synthetic data, with no schema or change to accepted input validation.

## Decision

Draft revision, supplemental-reference addition and review now use a bounded, unjoined `SELECT FOR UPDATE` of the target's `statement` and `change_reason`. Their existing immediate-parent re-read/lock uses the same bounded projection, replacing any stale cached parent. The writer materializes only complete prefixes; oversize target/parent text stops the transaction as an uninspected conflict before partial payload validation, evidence locking or creation. Self-review permission denial still precedes the technical conflict. The error explicitly says consistency was not checked: a raw reason longer than 1,000 characters can be valid after stripping whitespace. Complete values at the threshold continue through existing validation and fingerprints.

The lock order (target, immediate parent, assertions, latest existing review) and transaction conflict boundary are unchanged. The parent is read after the target lock, and direct bypasses, absent/future rows, later mutations and other records are not all locked. Conflict responses include the same private/no-store policy. Existing valid long-whitespace reasons can no longer be used as target/parent by these selected writers without further design; this defensive availability trade-off does not prove they are invalid. Input acceptance is unchanged, including service-level long whitespace, and newly created values can therefore exceed the transfer cap.

The projection bounds selected text transfer to Python, not exact bytes, other fields, request inputs, database work/decompression, every writer, or full concurrency. It does not establish authorship, provenance, rights or clinical correctness.

## Evidence

Synthetic PostgreSQL tests check all three writers against both text fields on target and parent, SQL projections and lock shape, complete threshold values, valid oversized whitespace reasons, self-review and no-writes on conflict. Selected waiting-writer races commit excessive target or parent content before the lock is acquired; existing parent-lock and evidence races remain. HTTP tests mutate after form precheck, verify private conflict and no writes, and opt-in Chromium exercises a stale review submission. These are selected scenarios, not a proof of all concurrency schedules.
