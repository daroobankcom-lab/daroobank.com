# 0213 — Durable staff-session invalidation derived from account state

Date: 2026-11-26
Status: accepted; closes the revival scenario ADR 0191 named, with the residuals listed below
Code: `daroobank/session_guard.py`, `daroobank/middleware.py::StaffSessionGuardMiddleware`,
`daroobank/settings.py` (middleware list), `staff_security/management/commands/revoke_staff_sessions.py`
Suite: `daroobank/test_staff_session_guard.py` (12 tests, ~6 s)
Supersedes in part: [ADR 0191](0191-staff-session-revocation-gap.md)

## Context

Django invalidates a session when the password changes, through the session-auth hash.
Nothing else about an account is covered: deactivating it, clearing `is_staff`, removing
a permission or changing a group leaves an unexpired session in the store, and each
staff view then denies that session *per request*. ADR 0191 recorded the consequence as
an unresolved production release blocker: deny while the flag is off, restore the flag,
and the same session works again.

Two measurements shaped the design.

First, the gap reproduced exactly as documented: after
`User.objects.filter(pk=…).update(is_active=False)` a staff request answered 302, and
after `update(is_active=True)` the same cookie answered **200**.

Second, the obvious fix does not work. A guard written against `request.user` cannot see
the change at all: for an inactive account `ModelBackend.get_user` returns no user, so
`request.user` is already anonymous, there is no account to compare, and the session is
left in place — reactivation still returned 200. The guard has to read **the account the
session names**, not the user the request resolved to.

A signal-based counter was also considered and rejected: the project's own tests, and any
incident-response script, change account state with `QuerySet.update()`, which emits no
`post_save`, so an event-driven epoch would be blind to exactly the writes that matter.

## Decision

Bind each session to a digest of the authorization state it was created against, and
compare that digest with the account's current state on every staff request.

`authorization_fingerprint(user_pk)` returns
`salted_hmac('daroobank.staff.session.v1', payload)` over

```
is_active | is_staff | is_superuser | get_session_auth_hash() | sorted(get_all_permissions())
```

and `None` when there is no such account or the key is not a positive integer.
`get_all_permissions()` covers direct and group grants, so a change to a group's
permissions reaches every member without enumerating groups.

A `user_logged_in` receiver stores the digest in the session under
`staff_auth_fingerprint`. `daroobank` is not an installed app, so there is no
`AppConfig.ready()` to hang it on; `daroobank.middleware` imports the module, which Django
loads at startup, and the connection is made once under a `dispatch_uid`.

`StaffSessionGuardMiddleware` runs last, after `AuthenticationMiddleware`, and **only on
staff paths**: it reads `_auth_user_id` from the session, recomputes that account's
digest, and calls `logout(request)` when the digest differs, when it is absent, or when
the account no longer exists. Flushing the session makes the rest of the request
anonymous, so every staff route answers with the same 302 to the login page that an
expired session already produced — no route gained a new denial path and no view changed.
Public read paths are not touched and pay no extra queries.

The comparison is fail-closed and deliberately coarse: **a grant ends a session exactly
as a revocation does**. Distinguishing them would require ordering permission sets, and
the property being bought is that removed access stays removed until the account
authenticates again.

Because the guard only fires when a request arrives, removing access also needs an
explicit mechanism: `revoke_staff_sessions` deletes rows from the database session store
— `--username` for one account or `--all`, exactly one required, read-only unless
`--apply`, scanning at most 5 000 sessions and deleting at most 500 per batch, reporting
JSON, and refusing to run outside a synthetic development environment like the rest of
the maintenance tooling. A deleted row means a cookie the client still holds resolves to
nothing.

## Measured behavior

`daroobank/test_staff_session_guard.py` pins:

| Change to the account | Session afterwards | Restoring the state |
| --- | --- | --- |
| `is_active=False` (via `.update()`) | ended, row deleted, 302 everywhere | still 302; a fresh login works |
| `is_staff=False` | ended | still 302 |
| one or all direct permissions removed | ended | still 302 after re-grant |
| a group's permissions cleared | ended for **every** member | — |
| member removed from a group | ended | — |
| account deleted | ended | — |
| password changed, flags untouched | ended | — |

The digest changes for `is_active`, `is_staff`, `is_superuser`, the password and every
change to *effective* permissions. It deliberately does **not** change for edits that
cannot alter effective access — clearing a superuser's own grants, or joining a group
that grants nothing — so those do not log anybody out.

Further pins: a session that names an account but carries no digest, carries a malformed
digest, names a missing account or names a non-integer is rejected (unit level; over HTTP
a non-integer `_auth_user_id` is rejected inside Django's own `AuthenticationMiddleware`
before this guard runs); a revoked session is denied on **all 41** matrix routes with a
302 to the login page, behind a positive control in which a fully permitted account is
redirected nowhere; public routes answer a stale session exactly as they answer an
anonymous caller and leave the session alone, so the staff-only scope is measured rather
than assumed; the command's read-only default, targeted and global revocation, skipping of
expired sessions and argument errors; and revocation changes none of the 14 counted
domain rows.

## Red checks

1. Removing `StaffSessionGuardMiddleware` from `MIDDLEWARE` fails **263** assertions
   across the 19 tests of the guard and revocation-boundary suites.
2. Rewriting the guard to compare `request.user` instead of the session's named account —
   the plausible wrong implementation — fails exactly **4** tests: deactivation with
   reactivation, account deletion, the ADR 0191 revival case, and the unbindable-session
   comparison. Both edits were reverted from backups and `git diff --stat` is clean.

## Consequences for existing tests

257 failures across 7 tests appeared when the guard was first enabled, all of them
assertions that encoded the old per-request denial. Five were updated, and the updates
are part of this change rather than a side effect:

- `daroobank/test_staff_revocation_boundary.py` — the two tests that *demonstrated* the
  ADR 0191 gap (`test_reactivation_can_revive_an_existing_unexpired_session`,
  `test_regranting_staff_can_reenable_an_existing_unexpired_session`) are renamed and
  inverted; three tests that expected `(403, 405)` per request now expect a 302 and assert
  the session is gone, including the one running a deliberately permissive backend.
- `daroobank/test_staff_workspace.py::test_revoked_permission_removes_link_and_destination_access`
  — the "link disappears, destination is 403" assertions now run behind a fresh login,
  because the first request after the removal ends the session.
- `pricing/test_staff.py::test_staff_without_domain_permission_can_login_but_not_read_domain`
  — a later demotion produces 302s instead of 403s, with a fresh-login control showing the
  account can still authenticate and still lacks the domain permission.

Cost: three additional queries per staff request (account row plus effective
permissions). Public reads are unaffected.

## Limitations

- **It fires only when a request arrives.** An off/on transition that no request observes
  leaves the stored state byte-identical to the bound state, so a *dormant* session
  survives it: nothing in the database records that the transition happened. Closing that
  needs a write-time counter — signals are bypassed by `QuerySet.update()`, so it would
  take a database trigger — or explicit revocation, which is what
  `revoke_staff_sessions` is for. The scenario ADR 0191 named (a denial observed, then the
  flag restored) is closed; the unobserved-transition variant is not, and is now a
  documented operating requirement rather than a silent gap.
- A request that has already passed the guard runs to completion. ADR 0192 serializes one
  write path against account-row changes; the others remain point-in-time.
- Removing a backend from `AUTHENTICATION_BACKENDS` is a settings change no request-time
  comparison can observe.
- Grants end sessions too. An administrator who adds a permission must expect the account
  to have to log in again; that is the chosen failure direction.
- Database-backed sessions only, and there is no UI.
  [ADR 0214](0214-session-inventory.md) adds the read-only per-account listing that was
  missing here; both commands still scan the store linearly and act on one bounded batch.
- The command is development-only, like the rest of the synthetic maintenance tooling. A
  production revocation procedure with audit and ownership remains an open operational
  gate.
- The digest identifies a *state*, not an account: two accounts in identical states share
  one digest. It is only ever compared against the state of the account the session
  names, so this is not a cross-account weakness, but it does mean the value cannot be
  used to tell sessions apart.
- `salted_hmac` keys on `SECRET_KEY`, so rotating the secret invalidates every session —
  the same consequence Django's own session-auth hash has.
- MFA factors, replay protection for a stolen cookie whose account state never changes,
  concurrent-worker session stores and account lifecycle auditing are all still out of
  scope. This is not an incident-response procedure.
