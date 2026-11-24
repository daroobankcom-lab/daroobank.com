# ADR 0163: bounded clinical detail and lineage reads

Status: development-only defensive read change for synthetic data; no authorization, write-validation or schema change.

## Decision

Extend ADR 0162's selected draft and immediate-parent text prefixes to private detail GET, invalid review POST and conflict refresh, revision/reference form prechecks, and each step of the lineage scan. The detail page reports excessive content as uninspected rather than invalid, hides draft/evidence and disables edit/review affordances. Its ten recent child clues and eleventh sentinel use the same bounded transfer; an oversized child is uninspected and has no detail link. Existing bounded recent-review handling continues with comparison unknown if the current version is unavailable.

Lineage stops before a link whose current version or immediate parent has excessive text, reports `oversized`, and does not issue a continuation cursor. Earlier inspected links may still be shown. A cursor presented with an oversized anchor/current is rejected, just as other unusable cursors are; permission checks remain first. Explicit direct URLs still check permissions and return the uninspected page. Whitespace-bearing long reasons can be perfectly valid, so no inconsistency is inferred solely from transfer length.

The cap limits transfer of selected text, not other fields, database work/decompression, exact bytes, writer-side locked reads, all request paths or concurrent changes. Lineage remains a bounded sequence of separate reads, not a snapshot or proof of provenance, completeness, rights or clinical validity.

## Evidence

Synthetic PostgreSQL tests cover current and immediate-parent fields, a genuinely valid long reason, children and lookahead, invalid POST/conflict refresh, disabled forms, permission/no-store behavior, stopped intermediate traversal and cursor rejection, SQL shape and existing lineage pagination. Opt-in Chromium covers oversized direct detail and lineage at four widths; automated contrast still requires manual review.
