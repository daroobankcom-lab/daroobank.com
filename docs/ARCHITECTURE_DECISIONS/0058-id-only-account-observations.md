# ADR 0058: ID-only account existence observations

Status: development-only, 23 November 2026.

## Decision

When only current account existence is needed, a new bounded-by-caller helper obtains a set of primary keys via an ID-only SELECT, instead of materializing full user objects. Invalid IDs are excluded and an empty valid set performs no query; duplicate IDs are deduplicated. The caller supplies the database alias. Inactive and nonstaff accounts still count as present.

This change applies to the source queue recorder clue (ADR 0057), the clinical queue author clue, and both the author and supplementary-reference recorder checks in the clinical technical scan (ADRs 0017/0056). The clinical reference scan uses the draft's database alias. Display paths that require user objects and write workflows are not generally migrated, and normal session authentication still reads account attributes. These selected checks only need ID membership; no account name, email, password hash or status fields are fetched by their existence SELECTs.

## Evidence and limits

Synthetic tests cover empty and invalid input, duplicate IDs, inactive accounts, selected alias forwarding and the generated SELECT columns. Queue and inspection tests check the selected SQL columns as well as the prior one-query-per-page and scan bounds. Existing browser and service behavior is unchanged.

IDs can still appear in SQL and database logs, and other queries may retrieve full user records. No account lookup locks or verifies identity, historical authorship, authorization, qualification or source rights. Separate reads are not a snapshot; stale or concurrent state remains possible. This is data minimization for selected development paths, not a privacy, security or production certification.
