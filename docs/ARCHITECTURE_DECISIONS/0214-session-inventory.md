# 0214 — A read-only session inventory that names what the guard cannot see

Date: 2026-11-26
Status: accepted
Code: `staff_security/management/commands/list_staff_sessions.py`
Suite: `daroobank/test_staff_session_inventory.py` (7 tests, ~3 s)
Companion: [ADR 0213](0213-durable-session-invalidation.md)

## Context

ADR 0213 made session invalidation durable at the request boundary and named its own
residual: the guard fires only when a request arrives, so a transition nobody observed
leaves a **dormant** session in the store, byte-identical to the state it was bound to.
`revoke_staff_sessions` can delete such a session, but before 0213 nothing could answer
the questions an operator actually needs: which sessions exist, whose are they, does the
account still look entitled to them, and which of them would the guard end on the next
request? ADR 0213 listed "no session inventory, no per-account listing" as an open item.

The inventory also has to be safe to run and safe to read. A report that printed session
keys would be a credential dump: whoever holds the output holds the sessions.

## Decision

`list_staff_sessions` is **read-only**, refuses to run outside a synthetic development
environment like the rest of the maintenance tooling, scans at most 5 000 unexpired
sessions ordered by key, and writes one JSON report to stdout.

Per account: `account_id`, `username`, `account_exists`, `is_active`, `is_staff`,
`is_superuser`, `session_count` and the session list. Per session: `alias`, `bound`,
`expires_at` and `guard_would_end_it`.

- `alias` replaces the session key: the first 32 hex characters of
  `salted_hmac('daroobank.staff.session.inventory.v1', session_key)`. Two sessions can be
  told apart, two reports can be compared, and an alias can be correlated with a
  revocation run — but an alias cannot be used as a cookie. No session key, cookie value
  or stored fingerprint digest is ever emitted.
- `bound` reports whether the session carries the ADR 0213 fingerprint at all. An
  unbound session is one the guard will not trust, and it is counted separately as
  `sessions_unbound`.
- `guard_would_end_it` recomputes the account's current digest and compares, so the
  report distinguishes a live session from a dormant one **before** anybody makes a
  request. A missing account never matches, so an orphaned session is flagged too.
- Expired sessions are excluded. A session naming a non-integer identity is skipped; a
  session whose account was deleted is still listed, with `account_exists: false` and
  null flags, because that row is exactly what an operator needs to see.
- `--username` narrows the report to one account; the store is still scanned, and
  `scanned` says so. An unknown or empty username is a `CommandError`, not an empty
  report that looks like a clean store.

## Measured behavior

`daroobank/test_staff_session_inventory.py` pins the report for two accounts and three
sessions (one account holding two); that the raw session key, the client's `sessionid`
cookie value and the stored digest appear nowhere in the output, that an alias is 32 hex
characters, differs from the key, is stable for one key and distinct for another; the
dormant case end to end — deactivate an account **without making a request**, see the
session row still listed with `guard_would_end_it: true`, revoke it with
`revoke_staff_sessions --apply`, and see the report go empty; an unbound session reported
as unbound and flagged; an orphaned session listed against no account; expired sessions
absent; the `--username` filter and both argument errors; and that two runs over an
unchanged store agree byte for byte while the session count and all 14 counted domain
models stay where they were.

## Red check

Emitting `session.session_key` in place of `session_alias(session.session_key)` fails
`test_the_report_never_contains_session_material` with **3** assertion failures. The line
was restored from a backup.

## Limitations

- The alias is keyed on `SECRET_KEY`, so rotating the secret changes every alias and two
  reports taken across a rotation cannot be correlated. It is also a truncation: it
  identifies a session, and does not authenticate anything.
- The report contains usernames and account flags. It is sensitive operational output,
  not an artifact to paste into an issue, and it is development-only by design; a
  production inventory with access control, audit and retention is still an open
  operational gate.
- Scanning is linear over the session store with a 5 000 cap and no pagination cursor. A
  larger store is reported only up to the cap, which `scanned` and `scan_limit` make
  visible but do not fix.
- The inventory says what exists, not why anything should be revoked. It is not an audit
  log, it records no history, and a session that expired between two runs simply
  disappears.
- Database-backed sessions only. A cache- or cookie-backed session store would not appear
  here at all, and `guard_would_end_it` reflects the digest comparison only — not the
  in-flight window, backend removal or MFA, which ADR 0213 also leaves open.
