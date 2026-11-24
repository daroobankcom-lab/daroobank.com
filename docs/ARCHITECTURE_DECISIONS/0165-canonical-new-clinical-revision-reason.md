# ADR 0165: canonicalize new clinical revision reasons

Status: development-only synthetic writing behavior; no schema or historical data migration.

## Context and decision

ADR 0164 deliberately treated raw revision reasons over the transfer limit as uninspected, because the shared validator checks length *after* stripping outer whitespace. The direct `create_draft` service could therefore create a valid child with a very long raw reason that the application's own bounded reads and subsequent writers would not inspect. The browser form already strips outer whitespace; the direct service did not.

After validating the original reason, new child revisions now store and fingerprint `change_reason.strip()`. Internal tabs and newlines are preserved. Forbidden controls and surrogate characters in the original input are still rejected, even if stripping might otherwise hide them; the initial version still requires an exactly empty reason. The canonical reason remains 12–1,000 characters under the existing validator and thus fits the selected read transfer cap. This changes the returned and fingerprinted raw representation for direct service calls with outer whitespace; clients must use the returned stored hash. It does not change clinical approval or permissions.

Existing rows are never rewritten. A historically valid reason with outer whitespace retains its original hash and remains valid under the old rules; a historical oversized reason remains *uninspected*, not invalid, and selected reads/writers continue to fail closed as in ADRs 0162–0164. Those ADRs describe their historical behavior; this decision supersedes their statements about newly stored reasons, not their handling of old data. Canonicalization does not bound incoming request size, database work, other fields, all writers or exact bytes and does not establish provenance or clinical validity.

## Evidence

Synthetic PostgreSQL tests cover long edge whitespace, preserved internal tab/newline, canonical hash and review snapshot, 12/1,000 boundaries, invalid raw controls, root behavior and an unchanged legacy short raw reason/hash. Separate defensive-read and locked-writer tests construct valid legacy oversized rows with their exact historical digest. These cases are not proof of all inputs, race schedules or production readiness.
