# ADR 0107: validate the prospective partial presentation row

Status: development-only implementation, 24 November 2026. Extends [ADR 0023](0023-presentation-partial-save-projections.md).

## Decision

For a nonempty partial model save of an existing presentation, the locked row now supplies every concrete field omitted from `update_fields` to a separate prospective instance. Explicitly updated fields come from the caller; both lookup projections are rebuilt from that combined state. `full_clean()` validates the prospective row before the original object performs the update. Validated/coerced written fields and projections are copied back to the original object, which remains the signal sender. The lock and atomic block remain those of ADR 0023. Empty updates remain no-ops, and full saves keep their existing semantics.

This fixes validation against stale or unwritten instance attributes: for example, a stale `published=True` update must not pass merely because that instance retained a verification date that another committed update removed. Conversely, an invalid local URL that is not being written should not itself reject an otherwise valid update, while an invalid URL already stored can reject it. Correcting that stored field explicitly remains possible. This is a behavioral change for partial writes involving invalid stored data; no existing data is rewritten.

The original object is deliberately not refreshed for omitted fields. Signal receivers and callers can therefore still observe stale or locally modified omitted attributes on it even though validation used locked values. Receivers should not treat the object as a fresh representation of the entire row. `full_clean` can invoke application/database validation and can fail on existing invalid data; this is not a generic database constraint or audit. The approach assumes the current model's concrete fields and validation behavior; future relations, custom fields, validators, routers or signal changes require review.

## Evidence and limits

Synthetic PostgreSQL tests first demonstrated three invalid-write failures and one spurious rejection against the old code. They now cover both directions of the publication/date stale-state mismatch, invalid local versus invalid stored URL, explicit correction, validation coercion and valid simultaneous changes. A two-connection test loads the stale second instance before the first publication, verifies that it waits on the row lock, then observes validation reject the attempted verification removal after the first commit. Existing tests cover projection maintenance, rollback, positional parameters, deferred objects and signals. These selected schedules do not prove behavior for all isolation levels, concurrency paths or external writers.

Bulk updates, direct SQL and historical migration models still bypass the override. Full saves may overwrite newer data; writes by any path can change the row immediately after commit. The publication flag and verification timestamp are not proof of rights, safety or clinical approval. This is not production authorization, tamper resistance, a data repair, or a substitute for database constraints and deployment review. Use only synthetic development data.
