# ADR 0119: require an explicit boolean for intake commit mode

Status: development-only validation, 24 November 2026.

## Problem and decision

The product and price intake services previously used Python truthiness for `commit`. Passing the string `"False"` alongside an explicit rights attestation unexpectedly entered write mode rather than preview mode. Both service boundaries now accept only the actual booleans `False` and `True`; other values raise the existing domain validation error before file reads, callbacks or database writes. Product authorization still runs before this mode check. Preview remains the default; `True` still requires a separate literal `True` rights attestation. The web UI and command-line flags use booleans already.

The synthetic projection-repair management command also checked programmatic `commit` with truthiness: `call_command` could accept `"False"` with a valid preview token and literal synthetic confirmation and actually repair a row. Its two flags now require booleans and its token must be a string; malformed option combinations fail before any query. Normal argparse flags are unchanged. The service's independent literal synthetic-confirmation check remains in place.

## Evidence and limits

Synthetic tests pass selected truthy and falsey non-booleans, with and without callbacks, and check that the stream position, candidate count and callback list do not change. They also exercise ordinary preview and attested commit. Before the fix, selected truthy values entered staging in both services. A synthetic test also reproduced the string `"False"` causing a repair before the command fix; after the fix, selected malformed `call_command` options make zero database queries and a valid preview/commit still works. This is an intentional compatibility change for direct Python callers that passed integers, strings or other non-booleans; it is not a new authorization system, proof of source rights, protection against direct database writes, or protection from external effects inside a callback in a valid commit. No clinical or pricing data was introduced.
