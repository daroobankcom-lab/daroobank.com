# ADR 0108: bound direct price conversion input

Status: development-only implementation, 24 November 2026.

## Decision

The price conversion helper itself now rejects a non-string amount or an amount over the existing 50-character CSV field limit before normalization. It also rejects non-string currencies without leaking a Python type error. Previously CSV parsing already enforced its field limit, but direct calls could supply a much longer fractional amount; the fixed 80-digit decimal context could round a nonintegral value to a whole rial. That is a helper-level defect; no evidence here shows that the bounded CSV path accepted that particular long input.

Conversion now uses decimal digit strings: for toman it shifts one fractional digit into the integer part, requires all remaining fractional digits to be zero, strips leading zeroes, and compares the result to the 64-bit rial maximum before converting the small integer. Unicode normalization can expand the input; the conversion does not rely on decimal context precision or exponent limits and does not round. It still accepts only the established normalized plain-digit grammar and explicit RIAL/TOMAN, rejecting zero, fractions of a rial and overflow. The limit is applied to the input string before normalization; the existing CSV parser strips CSV field whitespace before calling the helper. The helper's new direct-call limit is a compatibility change. No existing candidates or prices are modified.

## Evidence and limits

Before the change, a direct call with `1.` followed by 80 zeroes and a final `1` returned 1 rial, and a 51-character direct value was accepted; non-string inputs could raise a type error. Synthetic tests cover these cases, a 50-character boundary, normalization expanding to 98 characters, explicit currencies, a restrictive ambient decimal context and 3,000 seeded compatibility-digit examples compared with integer division. Existing bounded decimal oracle and workflow tests also pass. These finite examples do not prove all Unicode versions or all runtime configurations; the normalization routine permits some compatibility digit characters, not just ASCII/Persian digits. Validation is not price verification, source rights, approval or publication, and privileged writes can bypass it. Use only synthetic data.
