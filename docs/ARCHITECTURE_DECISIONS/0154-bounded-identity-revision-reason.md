# ADR 0154: bound selected identity revision-link reason reads

Status: development-only defensive reading, synthetic data. No schema, permissions, writes or validator rules change.

## Decision

The private detail pages and parent-path inspector for ingredient, formulation, product and package revisions selected full `change_reason` TextFields for each link, including an extra child-list lookahead. A bypassed write can exceed the existing 1,000-character reason validation. These reads now select at most 1,001 characters in the same SELECT, defer the original and replace the deferred attribute before the existing structural validator runs. A value over the limit cannot pass: a 1,001-character prefix either has more than 1,000 non-edge characters or has noncanonical edge whitespace, both rejected by the existing validator. Thus it remains an inconsistent link, with details suppressed, without loading the full reason into Python. It is not an authorization, identity, provenance or authenticity decision.

Link order, current-page sentinel, parent traversal, signed cursor, permission checks and no-snapshot warning remain unchanged. The lookahead is bounded but not classified. Database substring processing can still read or decompress the full value; the bound counts characters, not exact wire bytes or database work. Other fields, graph contents, links fetched elsewhere and write paths remain outside this policy. A separately read link can change after inspection.

## Evidence and limitations

Synthetic PostgreSQL tests exercise all four kinds in parent and child detail and lineage, huge reasons, whitespace boundary cases, 1,000/1,001-character boundaries, SQL shape and non-reflection, the extra child sentinel and continuation. Existing lineage and revision tests are rerun; Chromium checks one synthetic oversized ingredient link and lineage at four selected widths. This does not test every race, data corruption case, device or screen reader. Some automated contrast results require manual review.
