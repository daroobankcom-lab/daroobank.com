# ADR 0126: bound the returned projection for synthetic repair

Status: development-only safeguard, 24 November 2026; not production repair authorization.

## Context and decision

The one-row synthetic projection repair already refuses a stored `search_text` longer than 8192 characters, but previously fetched the entire text into Python before checking that limit. A bypassed write could therefore transfer an arbitrarily oversized value even though it would be rejected.

Both preview and locked commit recheck now select a PostgreSQL substring of at most 8193 characters instead of the complete `search_text`. If the extra character is present, the existing unsafe/stale path rejects the row without generating a token or writing. At 8192 or fewer characters, the entire stored projection is still available for validation and the signed state hash; all other row fields used by that hash are unchanged. Commit still obtains a row lock and rechecks the state. The operation remains restricted to explicit synthetic development use.

## Evidence and limitations

PostgreSQL tests use a million-character Persian projection, check the returned prefix length and selected SQL, and show preview rejects it without a token. They also check the 8192/8193 character boundary, full-state equality and hashing within the limit, a changed last character, and growth after preview with a locked recheck and no update. Existing rollback, lock, conflict and token tests are retained. Tests cover selected examples only.

This bounds the projection returned to Python, **not** PostgreSQL's storage, decompression, memory or work evaluating the substring. It does not by itself bound other paths that read the projection, other row fields or all drivers/configurations. Catalog-quality inspection was subsequently changed separately; see ADR 0127. It is not a backup, performance guarantee, general data-integrity check or authorization to repair real data; crashes, privileged writes and external transactions still matter.
