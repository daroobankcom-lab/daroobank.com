# ADR 0015: Bounded inspection of synthetic correction ancestry

Status: development-only, 2026-11-22.

## Decision

Provide a read-only staff inspection of the recorded immediate-parent correction path for one ingredient, formulation, product or package. It uses the same active staff and `catalog.view_identityworkspace` permission as the private identity workspace; the web route also requires the development staff gate and applies private/no-store/noindex and same-origin referrer headers. Direct service calls enforce the user permission but do not enforce the web gate. Use synthetic, nonconfidential data only.

From the selected record, inspect at most 20 parent links per request using the existing type-specific immediate-link and graph validators. Validated child and parent IDs and the relative step count are displayed; source fields, names, change reasons and raw graph hashes are not deliberately rendered. An invalid/missing graph or link stops the traversal and suppresses that link's details. No recorded incoming link is reported as such, not as proof of a true origin or complete history. No records, reviews, flags or public content are changed. Parallel child branches are not inspected; the path follows only the selected child's one immediate parent at each step.

Continuation cursors are signed, time-limited to one hour, bounded in size, and bound to record type, anchor ID, keyed anchor/current graph digests, current ID and depth. Anchor and continuation graphs are revalidated when a cursor is used. A changed graph, malformed token, wrong type/anchor or expired cursor fails closed. Tokens contain IDs and keyed digests and are signed but not encrypted, can appear in logs, and are not authorization or confidentiality grants. Each request enforces permissions. A new inspection may be started from the record detail page.

## Limits

This is a bounded diagnostic, not proof of identity, clinical equivalence, source rights, correctness, completeness, authenticity, a tamper-proof audit or review of correction provenance. The unkeyed underlying hashes and model guards can be bypassed or recomputed by privileged database writers. Pages and graph reads are not a consistent snapshot: earlier links are not rechecked on later pages and out-of-band changes, concurrent operations or already-corrupt links can alter results. Even a fully traversed currently consistent path can be fabricated; a missing link can reflect unrecorded or removed history. Cursor validity alone does not prove that earlier pages remain unchanged. Existing review, revision, source-validation, publication and public catalog semantics are unchanged. Query plans and large datasets have not been benchmarked; browser/accessibility, clinical, legal and production security review remain outstanding. See [ADR 0013](0013-synthetic-package-revisions.md) and [ADR 0014](0014-synthetic-component-revisions.md).
