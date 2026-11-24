# ADR 0118: reject raw controls in staged CSV and source upload fields

Status: development-only validation change, 24 November 2026; complements [ADR 0117](0117-price-amount-invisible-characters.md).

## Problem and decision

The product and price CSV parsers trimmed each cell before validating it. A leading tab or trailing newline could therefore disappear before the existing field rules saw it, yielding a different staged value and possibly a duplicate source ID. Both parsers now reject Unicode control and surrogate categories (`Cc`, `Cs`) in raw cells before trimming. The price service also checks raw source name and URL before its existing trim. Product and price upload forms inspect their raw source fields, including prefixed forms, so Django's form trimming cannot silently erase these controls before the service sees the values.

Ordinary surrounding spaces still follow existing trim behavior, and Persian zero-width joiners inside normal product text are not banned by this change. Amounts have the stricter separate policy in ADR 0117. A CSV with an invalid row is rejected before staging; error messages for parser controls identify the field and logical row, not the imported value.

## Evidence and limits

Synthetic direct preview/commit tests cover controls in selected identity, currency, unit and date cells and selected source arguments, with no candidate writes. Prefixed form tests cover raw source controls, spaces and a Persian joiner. Authenticated synthetic upload tests check selected source and CSV errors leave no candidate or import receipt. Tests on the earlier parser and form behavior accepted the selected boundary controls.

This intentionally rejects some formerly accepted CSV or source input. It does not reconstruct characters previously stripped, preserve the original file, verify provenance or rights, prevent Unicode spoofing, reject every format/line-separator character in every field, or cover every form or direct database/bulk writer. Forms can still render bound input, and privacy of web-server, proxy and application logs is outside these tests. All examples are synthetic; this is not a production-security or data-quality certification.
