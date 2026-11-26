# 0224 — the documentation graph resolves: links, anchors, index entries and named suites

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_document_links.py` (7 tests, ~0.09 s, no database)

## Context

This repository documents itself heavily. Before this record it held 250 markdown documents, of
which 223 were numbered decision records, cross-linked to each other, to the four operator
documents, to `SECURITY.md` and to the test suites that measure each decision. Recent records
added more links: ADR 0219 tied the command surface to the guides, ADR 0222 tied the environment
to a new deployment reference, ADR 0223 tied abuse protection to it as well.

A broken link in that graph fails quietly, and the failure modes are ordinary rather than
exotic: a decision record that keeps citing a suite after the file was renamed, an index that
forgets the newest record because the bullet was added by a script that replaced instead of
inserted (which `docs/CHANGELOG.md` suffered twice, and ADR 0195's structure suite now guards),
a section anchor that stops matching because a heading was reworded, and a document that survives
after the thing it described was deleted, linked from nowhere.

None of these is visible in a test run, a diff review or CI. All of them are visible to the next
reader who follows the link.

## Decision

Hold the graph together mechanically with `daroobank/test_document_links.py`. Nothing was
repaired to make it pass: the graph was already intact, and this record pins that state so it
stays intact.

Text inside fenced code blocks is not prose. A shell comment beginning `# ` is not a heading —
`docs/DEVELOPMENT_GUIDE.md` contains three of them — and an example path in a code block is not a
link, so both are skipped when headings, anchors and links are collected.

## Measured behavior

| Measurement | Result |
|---|---|
| Documents | 251 markdown files: `README.md` plus everything under `docs/`, of which 224 are numbered decision records |
| Document shape | every document opens with a top-level heading on its first line and has exactly one |
| Decision-record numbers | 1 through 224, unique and contiguous: a number can be superseded but not silently removed |
| Links | 895 inline links, of which 31 are external (`http`, `https`, `mailto`) and the rest resolve to a file that exists, relative to the document that contains them |
| Anchors | 29 links carry a fragment; every one matches a heading slug in its target, using GitHub's rule (lowercase, letters and numbers kept, spaces to hyphens, backticks dropped) |
| Decision-record index | `docs/ARCHITECTURE_DECISIONS/README.md` lists all 224 records by filename, and every link in it resolves |
| Named suites | 14 decision records carry a `Suite:` line; every `.py` path named in one exists |
| Orphans | none: every document except `README.md`, the entry point, is linked from at least one other document |

## Red check

Six regressions, each applied alone and reverted (`git checkout` for tracked files, `rm` for the
probe document):

| Regression | Failures |
|---|---|
| The index's link to `0223-no-abuse-protection.md` retargeted at a file that does not exist | 3: the link scan, and the index check in both directions |
| The heading `## Development-only staff login throttle and window cleanup` reworded, which `docs/DEPLOYMENT.md` links to | the anchor check |
| The 0223 bullet deleted from the index | 2: the index check and the pinned link count |
| ADR 0223's `Suite:` line pointed at `daroobank/test_abuse_protection.py` | the named-suite check |
| A new `docs/ORPHAN_PROBE.md` that nothing links to | 2: the orphan check and the pinned document count |
| `docs/ARCHITECTURE_DECISIONS/0100-*.md` moved out of the tree | 6: the document count, the record count, contiguity, two dangling links and the index check |

After all six reverts the suite passed with only the new file untracked.

## Limits

- These are mechanical checks. Nothing here can tell whether a link points at the *right*
  document, whether an index summary still matches the record it summarizes, or whether a
  document says something true. A record can cite a suite that exists and no longer measures
  what the record claims.
- The slug rule approximates GitHub's. Letters in any script are kept and punctuation is dropped,
  which matches every anchor in use today; an exotic heading could produce a false pass or a false
  failure, and the anchor would still work or not work in a browser regardless of this suite.
- The pinned counts (251 documents, 224 records, 895 links, 31 external, 29 anchors, 14 suite
  lines) fail on legitimate growth, including the growth this record caused. That is deliberate
  friction: adding a document or a decision record is an event that should also update the pins.
- Only `README.md` and `docs/` are scanned. A markdown file elsewhere in the repository, or one
  added later outside those roots, is not checked.
- Links and headings inside fenced code blocks are ignored on purpose, so a wrong path in a
  documented example command is invisible here. `daroobank/test_backup_guide.py` covers the one
  documented block that matters most by executing it.
- The orphan check treats `README.md` as the root and asks only that every other document be
  linked from somewhere. It does not check that a document is reachable from `README.md` by a
  chain of links, so a cluster of documents linking only to each other would pass.
