# ADR 0178: distinguish missing authors in clinical child previews

Status: development-only internal display correction; no clinical or identity verification.

The clinical detail page already stops showing a draft's content when its current author account cannot be found. Its direct-child preview, however, checked the child's content and parent consistency but not its author, so a child appeared unqualified while its own detail page could not be shown. The bounded direct-child preview now reports `author_missing` separately, after oversized and invalid content checks. It retains links for inspectable rows and the existing ten-child display cap; no child author ID or content is added to the page. A single existence-only query covers valid displayed children; invalid, oversized and the lookahead row are excluded. Existing inactive/non-staff accounts still count as present.

This is a current observation, not an account lock, a historical identity claim, a complete lineage inspection, a source/evidence verification or authorization to make a clinical decision. Parent-author, child evidence, future changes and other lists retain their documented independent semantics. The new status is a clue for staff, not proof of availability at the next request.

Synthetic tests cover missing, invalid, oversized and available children, privacy and the cap, plus a mocked batched lookup. Existing clinical inspection, detail and evidence regressions exercise neighboring behavior.
