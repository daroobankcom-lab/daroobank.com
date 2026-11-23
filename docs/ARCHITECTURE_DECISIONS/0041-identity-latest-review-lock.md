# ADR 0041: lock the existing latest identity package review

Status: development-only, 23 November 2026. Extends selected identity package writers, not a full history lock or consistent audit snapshot.

## Problem and decision

Package correction checks the latest review's identity and structural consistency before writing a child and revision link; review creation checks only the latest review ID as its optimistic token. A selected PostgreSQL race showed a bulk update to the existing latest review could complete after correction read and validated it but before correction finished, leaving a child based on an already-mutated row. Model `save()` guards do not prevent bulk ORM or privileged SQL updates.

Package correction and review creation now lock and re-read the latest existing review using one `ORDER BY pk DESC LIMIT 1 FOR UPDATE` query on the package's database, after acquiring the package, product, formulation, component and ingredient locks. Its lock lasts until the outermost transaction ends. There is no review row to lock when none exists. Correction continues to validate the selected review structurally; review creation deliberately continues to check only its ID, not the integrity or current existence of the previous reviewer. This does not change permissions, self-review, or creator-account lookup rules. Other existing history rows are not locked. Display reads, lineage and other writer paths are unchanged.

## Evidence and limits

Synthetic separate-connection tests verify the timeout SQLSTATE for selected updates and deletes against both writers, rereading an update or deletion that precedes the lock, correction's consistency conflict, review's ID-only behavior, bounded SQL, atomic requirement and correction's outer transaction. An older review remains writable while correction holds the newest one. A selected test-only same-transaction bulk bypass can mutate the latest review after it is read, and an immediate-FK insertion blocks on the parent lock. A deferred-FK review insertion can instead occur concurrently and commit after correction, making a newer review visible later. These selected schedules do not establish general concurrency safety, deadlock freedom or snapshot isolation.

Neither the latest-row nor parent lock is a predicate/gap lock: new history, earlier rows, same-transaction bypass, mutations after commit, account changes and ABA remain possible. New locks can lengthen waits and add deadlock cycles; no automatic retry is introduced. The saved revision link does not record a latest-review snapshot or ID. Locks and hash checks do not establish reviewer identity, authorization at the historical time, provenance, source rights or clinical safety. Synthetic data only; no production-readiness or publication claim is made.
