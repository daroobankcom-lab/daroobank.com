# ADR 0056: current author presence in clinical technical inspection

Status: development-only, 23 November 2026. This extends the bounded technical inspection of ADRs 0016/0017 and the creator observations of ADR 0033; it does not approve or authenticate clinical content.

## Decision

After validating each scanned draft and its immediate parent payload, the private clinical technical scan checks whether the selected draft's current author ID resolves to an account. A missing author is now reported as the filterable `author_missing` status, with no author name or ID displayed, and supplementary references for that draft are not examined. A structurally invalid draft takes precedence and neither its author nor references are checked. Drafts with an existing author proceed to the existing bounded reference checks; an existing account is accepted even if inactive or nonstaff. This is deliberately an existence observation, not a statement of identity, activity, qualification or historical authorization.

The scan reads at most 50 drafts plus one lookahead. One page-local account lookup is added for at most 50 distinct author IDs, and only eligible drafts enter the existing per-parent capped reference lookup. The scan now makes at most four SELECTs (drafts/parents, current authors, references and their recorders) for the configured PostgreSQL backend, fewer if an earlier stage has no qualifying rows. Bounds are on rows returned to Python, not bytes, database scan/sort work or time. Category filtering still applies after scanning, and the next position remains the last scanned ID.

## Evidence and limits

Synthetic tests use a deferred foreign-key mismatch restored before transaction end; they cover missing authors, inactive existing accounts, status precedence, skipping references, private output, authorization inherited from the existing page, filtered pagination, query bounds, and a child whose parent author's account is absent. A test-only account-lookup override illustrates changing observations but does not simulate every race. The page's selected warning and filter are exercised in Chromium. Existing creator-presence checks in writers remain independently authoritative for that operation.

The draft, author, reference and recorder reads are separate, unlocked observations, not a snapshot. Account existence can change after the lookup; an account present now is not proof of who authored the draft or of permission or qualification. The author's account of the immediate parent and earlier ancestors, review history, source rights, clinical accuracy, and full ancestry are not checked. Available does not mean a user can review, revise, publish or safely use the draft. Other paths, including the source date inspector, have their own semantics. No repairs or writes are performed. Use only synthetic data.
