# ADR 0064: unsafe presentation text in advisory price matching

Status: development-only, 23 November 2026. Narrows matching in [ADR 0021](0021-price-irc-candidate-cache.md).

## Decision

Before a presentation can be the unique advisory price suggestion, require its five matching fields to satisfy the same bounded, nonempty normalized and Cc/Cs-free text checks used for incoming price matching fields. Also require its displayed Persian name to be a string with a nonempty normalized value and without Cc/Cs. This is deliberately narrower than full catalog validation or public eligibility; unpublished presentations may still be suggested. Persian zero-width non-joiners remain allowed.

If a fetched presentation's matching fields can be normalized to an identity but fail these checks, or its displayed name fails, treat that identity as ambiguous, including when it is the only match. Do not ignore it and incorrectly treat another presentation as unique. If a matching field is not a string, the identity cannot safely be determined, so treat the whole fetched IRC group as ambiguous. A stale IRC projection with a different current normalized IRC is still skipped as before; it may conceal a true match. The existing over-100 group remains ambiguous before these checks.

This applies to staging, detail/CLI suggestions and the locked acceptance recheck through the shared index, including per-call cache behavior. Existing stored snapshots and receipts are not rewritten. It does not make suggestions verified, authenticate names, resolve stale negative projections, detect spoofing or guarantee uniqueness against concurrent inserts. Source rights, public readiness and clinical correctness remain outside scope. Only synthetic data is suitable.

## Evidence

Synthetic direct-update tests reproduced suggestions for control characters in a matching field or the displayed name, including a preliminary acceptance with the current fingerprint. The new cases check ambiguous output for all matching fields and the name, no display of a canary name, absence of acceptance writes, unsafe duplicate conservatism, a different identity in the same IRC, allowed Persian joiners and unpublished rows, and cached duplicate-row receipt outcomes. These cases do not cover every Unicode or database behavior and are not a clinical or security certification.
