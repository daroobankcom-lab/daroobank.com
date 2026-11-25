# ADR 0061: necessary depth bound for identity lineage cursors

Status: development-only, 23 November 2026. Narrows a cursor-validation edge in [ADR 0015](0015-synthetic-lineage-inspection.md); it does not make lineage a proof of identity or history.

## Decision

Each valid immediate correction link has a positive parent ID strictly smaller than the child ID. Therefore, an identity-lineage continuation that claims `depth` steps from `anchor` to `current` is arithmetically impossible when `depth > anchor - current`. Reject such a cursor as invalid before fetching the continuation graph, after the usual signature, type, page-size and anchor checks. This applies to ingredient, formulation, product and package paths, and matches an existing check in the clinical lineage inspector.

Existing honestly issued tokens from valid paths satisfy this necessary bound even when IDs contain gaps. Satisfying the bound is not sufficient to prove a path or its depth: earlier pages are still not revalidated and a suitably signed, arithmetically plausible token can claim a path never traversed. No cursor format or lifetime changes.

## Evidence and limits

A synthetic test re-signed an otherwise valid continuation with an impossible depth and reproduced the earlier false relative step numbers; the new check rejects it, returns a private nonreflecting HTTP 400 and does not fetch the continuation graph. Decoder tests cover all four kinds, including an arithmetically possible but unverified depth; existing pagination tests exercise normally issued tokens. Creating such a modified valid signature requires the signing key; the development fallback key is not secret and must not be treated as a production credential. Permission checks remain required on every request.

A signature is not encryption or authorization, and cursor URLs may be logged. The check does not prove skipped links, historical authorship, source rights, clinical correctness or a consistent snapshot. Bulk writes and privileged signers remain outside its guarantee. Only synthetic data is suitable.
