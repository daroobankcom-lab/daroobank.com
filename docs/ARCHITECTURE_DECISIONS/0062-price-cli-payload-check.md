# ADR 0062: local price candidate list payload check

Status: development-only, 23 November 2026.

## Decision

Before showing a staged price candidate or computing its fresh advisory match in `list_price_candidates`, use the existing review payload/derived-value consistency check. For a candidate it rejects, emit only its ID, `review_required`, `payload_status: invalid`, and an invalid current suggestion with no product ID. For a consistent candidate, retain the existing output fields and add `payload_status: consistent`. A matching-fields check still independently governs the fresh suggestion. The limit counts all selected rows, including invalid ones; `--status` filters the originally stored match status, not the current suggestion or payload status. No database writes are performed.

This changes the local command's JSON shape for invalid records; consumers must branch on `payload_status` rather than assume all fields exist. CLI and database access remain local operating-system responsibilities, not protected by the web staff gate. Output may contain valid structured source data and is not appropriate for sensitive material.

## Evidence and limitations

Synthetic tests first reproduced how a changed amount could still receive a matching suggestion and a malformed payload could be echoed. Tests cover invalid derived data, malformed or changed JSON, the row limit and original-status filter, skipped matching on rejection, unchanged data, and a normal candidate. They also demonstrate that a coherent update with recomputed unkeyed hash can pass and be displayed. The current check is not authentication, a confidentiality filter, source-rights proof, review eligibility, or price approval. The source URL is checked for syntax, but is not included in the stored price payload digest. It does not check current account existence or the historical matching decision, is not a consistent database snapshot and does not change review/publication rules. Source-provided sensitive text can still appear in otherwise consistent output. Use synthetic data only.
