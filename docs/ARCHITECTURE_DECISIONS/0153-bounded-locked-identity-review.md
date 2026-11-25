# ADR 0153: bound the locked latest identity review transfer

Status: development-only synthetic identity workflow, not deployment hardening. Extends ADR 0152 and existing identity latest-review locking; no schema, authorization or concurrency-token change.

## Decision

Identity package review and revision writers both lock the newest existing review row in their current transaction. Previously the `SELECT ... FOR UPDATE` transferred the full `graph_snapshot` and `reason`, even though review creation needs only the latest ID. The shared lock helper now selects the same row in the same order with the same row lock and the selected character bounds from ADR 0152, and replaces deferred fields from that same SELECT. The row, if present, keeps its original ID, including when oversized.

Revision requires a structurally consistent latest review. It now refuses an oversized latest review without classifying a partial graph; the transaction rolls back with an `IdentityConflict`. A complete in-limit row still follows the existing validator. Review creation deliberately keeps its previous policy: it checks the latest ID and does not require historical review consistency; an oversized previous review alone does not block the new review. The existing permissions, actor separation, expected token, lock order and conflict policy remain in force. A stale token is still rejected. This does not introduce locking of absent or future reviews, account rows or every graph row, nor defend against all bypass writes, post-transaction changes or same-transaction mutation.

## Evidence and limitations

Synthetic PostgreSQL tests examine the SQL shape, `FOR UPDATE`, bounded fields, exact character thresholds, no lazy fetch, rollback and preservation of the existing review-creation behavior. Existing selected multi-connection lock and conflict tests run in normal and optimized Python. These tests do not prove every interleaving or external writer's behavior. PostgreSQL may process or decompress the entire value before limiting transfer; database work, time, other graph fields and routes remain outside the protection. Thresholds are application-local defensive limits, not schema constraints, a resource budget, authentication or clinical approval.
