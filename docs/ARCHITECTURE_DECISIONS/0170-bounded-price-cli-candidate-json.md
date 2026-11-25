# ADR 0170: bound candidate JSON in the local price-list command

Status: development-only diagnostic output change; no schema, write, matching or authorization change.

## Decision

The local `list_price_candidates` command already capped selected rows and suppressed fields for invalid payloads, but selected unrestricted `source_fields` JSON before checking them. It now uses the existing candidate JSON transfer bound: at most 65,536 characters in PostgreSQL's JSON textual representation are returned for each selected row. Oversized payloads are not validated, matched or printed; the reduced JSON row has `payload_status: oversized` and `current_suggestion.match_status: unknown`. This is distinct from a complete but inconsistent payload, which retains `invalid` status. SQL/JSON null remains invalid under the existing validator rather than being labeled oversized.

The row limit still counts all selected rows, and `--status` filters the originally stored status. Normal consistent output, ASCII escaping, no writes, and the absence of an in-command authorization system are unchanged. Existing consumers must handle the new reduced `oversized`/`unknown` shape. Consistent output can contain sensitive values and must remain local/restricted.

This is a per-row transfer bound in selected CLI reads, not exact bytes or a bound on SQL work/decompression, all fields, output channels, other commands or memory. The check does not prove authenticity, confidentiality, source rights or price/clinical validity.

## Evidence

Synthetic PostgreSQL tests cover selected SQL, 65,536/65,537 boundaries, JSON null, no partial validation or matching, non-echo, row limit and stored-status filtering, alongside existing command integrity tests. The tests do not establish security for arbitrary terminal or log consumers.
