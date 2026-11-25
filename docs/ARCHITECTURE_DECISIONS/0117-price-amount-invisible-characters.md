# ADR 0117: reject hidden and combining characters in price amounts

Status: development-only validation change, 24 November 2026; extends [ADR 0108](0108-price-conversion-input-bound.md).

## Problem and decision

Search normalization intentionally removes Unicode format characters and combining marks. Using it for money meant inputs such as `1` + zero-width space + `2` became `12`, and a combining mark could disappear. CSV parsing also stripped control whitespace at the cell boundary before amount validation. These observations are synthetic; they do not establish that real prices were ingested or published.

Amount conversion now rejects Unicode categories `Cc`, `Cs`, `Cf`, `Mn`, `Me`, `Zl` and `Zp` in both the original bounded input and its NFKC form, then maps Arabic/Persian digits and the Arabic decimal separator without search-specific mark removal. The CSV parser checks the raw amount cell before stripping, so tabs, newlines and line separators at the edge are rejected as well. Ordinary outer spacing and previously supported NFKC compatibility digits remain accepted where they resolve to a plain decimal. Arithmetic remains exact and currency-explicit.

## Evidence and limits

Direct and CSV tests demonstrate rejected zero-width, bidirectional, control and combining examples, including a spacing character that NFKC expands into a combining mark. A two-row invalid synthetic CSV leaves no candidates; a previously plausible, internally consistent synthetic legacy candidate with a hidden character becomes unavailable to comparison/review rather than being silently reinterpreted. Existing 5,000 seeded decimal and 3,000 compatibility-digit oracle cases and 20,000 two-decimal examples still run. A test traverses every Unicode codepoint in the host's Unicode database, embedded in one selected amount pattern, and rejects those with the listed raw or normalized categories. A one-off comparison of the old and new algorithms on 2,228,224 one-character prefix/suffix cases found 4,376 formerly accepted cases now rejected and no newly accepted or changed accepted value in that sample.

This is a deliberate compatibility change: historical candidate data containing such characters may now fail integrity checks and need independent human review. It is not an exhaustive proof over all Unicode strings, CSV dialects, data corruption, pricing semantics, unit identity or financial accuracy, and it does not publish or approve prices. Other text fields and direct database/bulk writes have separate behavior. Do not use tests or examples as evidence of source rights or production readiness.
