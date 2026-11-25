# ADR 0156: bound related candidate JSON in comparisons

Status: development-only defensive reads using synthetic data; no schema, writes, permissions or matching rules change.

## Decision

Product same-source revisions and normalized-IRC candidate clues, and price same-source revisions, each read up to ten records plus a lookahead. Their queries previously transferred entire `source_fields` JSON. Each query now defers that column and selects it via a CASE only when its PostgreSQL text representation is no longer than 65,536 characters. Materialization uses that same SELECT; no lazy load or partial JSON reaches the validator. Longer related candidates are explicitly uninspected, not inconsistent: their detailed links and comparison/arithmetic are withheld. Product IRC clues track these separately from records actually classified inconsistent. The lookahead is bounded but unclassified. Existing order, cap, other validation and advisory-only semantics are preserved.

This is only a selected-field transfer bound. It does not bound database work, decompression, exact wire bytes, current candidate, other fields, public presentation reads, other endpoints or writes. Lists and comparisons can change between queries and do not prove identity, provenance, authenticity or clinical validity. This does not make the detail page safe against all oversized data.

## Evidence

Synthetic PostgreSQL tests exercise both candidate types, threshold equality and oversize, malformed null, SQL selection, validators not called on oversized objects, skipped counts, suppressed links, conditional arithmetic and 11th-row lookahead. Existing comparison query-count and semantic tests are retained. Opt-in Chromium tests cover selected related product and price data at four widths; automated contrast results still need manual checking.
