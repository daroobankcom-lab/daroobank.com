# ADR 0068: source detail review consistency clues

Status: development-only implementation, 23 November 2026; extends [ADR 0032](0032-reviewer-lookup-in-intake-history.md) and [ADR 0067](0067-source-review-inspection.md).

## Decision

Apply the existing source snapshot classifier to each of the at most 25 recent reviews already fetched for a source-claim detail. When the current claim is technically invalid, suppress the decision, reason and reviewer name and report an unknown comparison. Otherwise, suppress those fields for an invalid historical record or a currently missing reviewer; for a structurally consistent review with a currently present reviewer, continue showing the reason and name and add a fixed same/different/unknown comparison against the observed current claim hash and recorder ID. An invalid current claim takes display precedence over a missing reviewer, which takes precedence over an invalid historical record. The separate bounded reviewer-account lookup and latest-review ID used in the form are unchanged. This display check does not gate a new review: the writer continues to check the claim, recorder and last review ID, not full historical content.

The comparison reads the current claim and review rows at different times; the separately fetched reviewer and recorder accounts can also change. Tests exercise one stale-read schedule. A present account is not evidence of historical identity or qualifications. Unkeyed hashes and all related fields can be altered coherently, so consistent/equal is not authentication or a rights determination. Raw current claim fields remain visible to authorized staff even when inconsistent. This check does not sanitize data or establish provenance, source authorization, legality, history completeness, chronological cause or production safety. Only synthetic, non-sensitive data is suitable.

## Evidence and limits

Synthetic tests cover same/different/unknown states, corrupted snapshots, missing reviewers, preserved last-review tokens and a successful fresh review despite a malformed historical row. Existing capped-history tests check query count remains independent of the number of displayed reviews. Chromium checks the normal notice and layout at four widths; account corruption is checked at HTTP/test-database level. Row count is bounded, but snapshot bytes, database work and time are not. No general concurrency guarantee is implied.
