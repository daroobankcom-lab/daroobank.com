# ADR 0047: reject future-dated signed cursors

Status: development implementation, 23 November 2026.

## Context and decision

Django timestamp signing validates `max_age` by subtracting the embedded timestamp from the local clock. A correctly signed future timestamp has a negative age and is not rejected by that check alone. Cursor lifetime documentation should not imply that a future-dated signed cursor is automatically limited to one hour from the verifying host's current time.

The four existing time-limited, uncompressed cursor decoders for public search, catalog IRC inspection, identity lineage and clinical lineage now use a common helper. Each caller still enforces its existing type, length and no-compression checks and validates its own signed payload. The helper verifies the signature and Django's maximum age first, then rejects a timestamp later than the verifying host's clock. Existing generic invalid-cursor responses, permissions, signing salts, formats, page limits and one-hour maximum ages are unchanged. Projection repair already separately rejects future tokens and is not modified.

## Evidence and limits

Clock-controlled unit tests exercise all four decoders at issuance, exactly one hour, one second in the future and one second beyond expiry, and check tampered signatures and wrong salts. Synthetic HTTP tests check public and each private cursor error without reflecting its token; authorization and privacy headers remain separate checks. This is not proof of all clock, pagination or concurrency behavior. These tokens are signed, not encrypted or access grants; no patient data belongs in them.

Host clocks may move backwards or differ between workers: a valid cursor created by a host whose clock is ahead can now be rejected until the verifying clock catches up. Synchronization, monitoring and operational clock policy are deployment responsibilities; this change does not implement them. Wall-clock rollback can affect maximum age, and signing keys, permissions, access logs and network controls still need their own protections. No production security approval is implied.
