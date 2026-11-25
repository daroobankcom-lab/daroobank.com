# ADR 0157: bound candidate JSON in staff queues

Status: synthetic-data development defense; no schema, write, authorization, filtering or pagination changes.

## Decision

Product and price staff queues each read 20 candidate rows per page and previously transferred the full `source_fields` JSON for every row. A bypassed write can make that field much larger than expected. The queue SELECT now defers the field and conditionally returns it only if PostgreSQL's JSON textual representation is at most 65,536 characters, using the same bounded helper as ADR 0156. The selected value replaces the deferred field before any normal validation; larger content is neither read into Python nor validated. Each oversized candidate remains in place and is explicitly marked uninspected, not inconsistent, with its detail link withheld. Bounded malformed values still use existing inconsistent handling. Counts, filter selections, ordering, latest-decision labels and price statistics are unchanged and are not independently validated by this change.

This does not bound database work, decompression, other fields, other endpoints including a directly requested detail page, or writes; it does not establish authenticity, identity, source rights or clinical validity. Page counts and rows can change between queries. Hiding a link is not access control.

## Evidence

Synthetic PostgreSQL tests cover both queues, oversized rows on multiple pages, SQL projection shape, validator bypass, normal malformed and null JSON, preserved pagination, filtering and price counts, and private headers. Existing queue tests remain applicable. Opt-in Chromium checks oversized rows at four widths; automated contrast findings need manual review.
