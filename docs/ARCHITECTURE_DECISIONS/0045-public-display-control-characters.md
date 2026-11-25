# ADR 0045: reject selected malformed public display text

Status: development implementation, 23 November 2026.

## Context and decision

Public catalog reads recheck source metadata and required values even when direct database writes bypass model validation. However, a published presentation containing control characters in its displayed fields could still be returned. The shared `is_public_presentation` predicate now rejects non-string values and Unicode control (`Cc`) or surrogate (`Cs`) characters in every displayed presentation string, including optional English name and IRC and both source fields. The existing search and detail HTML/JSON paths use that predicate; invalid records are omitted or receive the existing generic 404. Persian zero-width non-joiners and other format characters are not removed or rejected by this specific check. The change does not edit database rows, projection fields, the SQL prefilter, pagination, source URLs or publication state.

## Evidence and limits

Tests use a synthetic published record and direct ORM updates that leave its search projection unchanged. They exercise every displayed field with a control character, both search representations and both detail representations, no-echo errors and privacy headers. Separate in-memory checks cover non-string values, surrogates and C0/C1 controls; a valid Persian zero-width non-joiner and optional empty fields remain supported. The existing bounded quality inspection reports unsafe text but does not repair it. Search still scans at most 150 candidates per page, so corrupt rows may produce an empty page with a continuation cursor.

This is a narrow read-side guard, not a complete Unicode spoofing, bidirectional-text, phishing, content-quality, provenance, authorization or clinical verification system. It does not validate other endpoints or writes, remove problematic records, prevent bulk SQL, authenticate the displayed source, or prove production readiness. Legitimate multiline data containing control characters also becomes ineligible for these public reads; operators should investigate data rather than treating rejection as a repair.
