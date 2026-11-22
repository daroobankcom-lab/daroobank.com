# ADR 0005: private clinical statement drafts, not publication

Status: development-only implementation, 22 November 2026.

## Decision

Introduce a narrowly scoped clinical editorial domain with private statement drafts, a single asserted citation and independent preliminary triage. Each draft records a free-text subject, intended audience, title, a text field intended for one statement, reference title, exact location and HTTPS URL, optional reference author/version and asserted publication/access dates. No seed medical statements or real references are provided. It is not attached to a product or ingredient, because those identities and clinical governance are not yet established. Citation metadata and content are unverified assertions; URLs are not fetched and source rights are not authorized by this workflow.

Each correction is a new draft linked to an immediate parent and its payload hash, with a change reason. Subject and audience must remain exactly the same within a revision link; branching and identical versions are allowed, no linear or complete history is implied. On revision/review, check the draft and its immediate parent for valid fields and hash consistency, but do not traverse or certify the full ancestry. A distinct active staff reviewer can record a reasoned referral for further review, rejection or deferral, with a snapshot and sequential optimistic review version. There is intentionally no approval or publish action. Reviews are specific to that version and do not carry over to revisions.

Use separate clinical view/add/review permissions, DEBUG-only staff routes, CSRF, private headers and scoped navigation. The optional exact-URL source-claim hint is separately permission-gated and never controls authoring or review. No clinical content is exposed by the public site or API. Use only synthetic, non-sensitive local data.

## Limitations

The system cannot enforce that a text field contains only one statement. One reference is insufficient for comprehensive clinical evidence; dates and citations are not verified, and no reviewer qualifications, conflicting-evidence assessment, final approval, source licence, structured drug identity, scheduled re-review, correction/withdrawal publication, tamper-resistant audit or public version projection exists. Hashes are not signatures and exclude actor/time; bulk ORM/SQL bypass model guards. SQLite `select_for_update` does not serialize concurrent writers; optimistic checks protect sequential stale requests only. Parent integrity checking is one level only; branching is not a conflict-resolution workflow. Production requires clinical, legal, security, retention and concurrency design before real use.
