# ADR 0119: require an explicit boolean for intake commit mode

Status: development-only validation, 24 November 2026.

## Problem and decision

The product and price intake services previously used Python truthiness for `commit`. Passing the string `"False"` alongside an explicit rights attestation unexpectedly entered write mode rather than preview mode. Both service boundaries now accept only the actual booleans `False` and `True`; other values raise the existing domain validation error before file reads, callbacks or database writes. Product authorization still runs before this mode check. Preview remains the default; `True` still requires a separate literal `True` rights attestation. The web UI and command-line flags use booleans already.

## Evidence and limits

Synthetic tests pass selected truthy and falsey non-booleans, with and without callbacks, and check that the stream position, candidate count and callback list do not change. They also exercise ordinary preview and attested commit. Before the fix, selected truthy values entered staging in both services. This is an intentional compatibility change for direct Python callers that passed integers, strings or other non-booleans; it is not a new authorization system, proof of source rights, protection against direct database writes, or protection from external effects inside a callback in a valid commit. No clinical or pricing data was introduced.
