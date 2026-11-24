# ADR 0150: bound selected current fields in review scans

Status: development-only defensive inspection using synthetic data; no change to writing, schema, retention or permissions.

## Decision

The source review scan previously selected the full current claim's `evidence_note` TextField, while the clinical review scan selected both the current draft and its immediate parent with their full `statement` and `change_reason` TextFields. Bypass-written values can be much larger than form and service validation limits. The scans now select prefixes of one character beyond those existing limits (1,001 for source note and clinical change reason; 4,001 for clinical statement), set them on each loaded object instead of the deferred original, then use the existing validators. Thus an oversized current value makes current comparison unknown without classifying a truncated parent as valid. The clinical join, parent relationship and separate reads are otherwise unchanged. A missing immediate parent still fails validation. This does not alter detail pages or other paths, and it is not a storage or database-work limit.

The product and price scan error endpoints previously fetched a full candidate, including its JSON, merely to decide whether an invalid-filter/cursor error should be a 400 or 404. They now perform an existence query after the same permission and ID checks, preserving the response distinction without selecting candidate fields. As before, the existence read and later response are not an atomic snapshot.

## Evidence and limitations

Synthetic PostgreSQL tests exercise million-character source and clinical fields, both current draft and immediate parent, exact validation boundaries, same/different/unknown comparison, joined SQL and absence of lazy reads, invalid cursor and filter, both candidate domains, missing parents/candidates, private headers and no response reflection. The query still reads other columns, and other detail, error, queue, scan and write paths remain outside this decision. Prefixes count database characters, not exact wire bytes; database decompression, work, time and storage are not bounded. A valid current comparison or digest is not authentication, approval, provenance or proof of chronology. The constraints do not make the project production ready or clinically valid.
