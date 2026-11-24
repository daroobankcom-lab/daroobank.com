# ADR 0067: bounded source-review snapshot inspection

Status: development-only implementation, 23 November 2026; complements [ADR 0019](0019-clinical-review-inspection.md) and the source ledger.

## Decision

Provide a read-only scan at `/staff/sources/<claim-id>/reviews/inspection/`, linked from the source-claim detail. The existing development-only portal and active staff `sources.view_sourceclaim` permission apply; the service checks that permission independently. It returns only review IDs and fixed statuses/comparison clues, not source values, reasons, decisions, hashes, snapshots or account names. Invalid scan inputs yield a private non-reflecting 400 with a restart link only for an existing accessible claim.

Each request reads the claim and up to 51 reviews in ascending ID order, classifies at most 50, and filters within that batch. The next position is the last scanned ID even for an empty filtered result. With a warm permission cache this entails two SELECTs. Reviewers are not joined, so missing related accounts do not hide rows; account existence, activity and permissions are not checked.

A review is `invalid_record` if its assertion has an unsupported snapshot shape, invalid or noncanonical payload, mismatched hash, invalid decision or untrimmed/invalid reason, implausible IDs, or identical reviewer and recorded-by IDs. Otherwise `consistent` means only these checks found no inconsistency. Comparison is `same` or `different` based solely on the historical hash and recorder ID versus the currently valid claim, and `unknown` when either record or current comparison is unsuitable. Historical and current values can be altered coherently and the hashes recomputed; test coverage demonstrates such a rewrite still passing.

## Limits

The claim and review reads are separate, not a snapshot; concurrent changes and inserts behind the cursor may escape observation, and a test demonstrates a stale comparison. A separate-connection synthetic test uses a direct test-only review insertion that bypasses the participating review writer: the lower-ID insert stays uncommitted while 51 higher-ID rows commit and a forward cursor advances; when the lower-ID row commits, continuation misses it, while a fresh scan can see it. This demonstrates one bypass schedule, not that ordinary same-claim writers bypass their existing claim lock; it documents a limitation rather than requiring it to remain. Bounded rows are not a bound on JSON bytes, database work, response time or production load. This does not establish provenance, source rights, permission to collect or publish, reviewer qualification, account existence, authenticity, completeness or correctness. URL parameters and operational logs may be retained. Do not use sensitive or real data; this is neither legal review nor production readiness. The existing detail and review-writing behavior is unchanged except for the link.
