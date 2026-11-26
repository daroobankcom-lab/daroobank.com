# 0231 — the secret-rotation plan, and what rotating this project's one key actually does

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_secret_rotation_plan.py` (20 tests, ~7.4 s, 6 of them on a synthetic database)

## Context

Four documents ask for key rotation and not one of them describes it.
[SECURITY.md](../SECURITY.md) lists *"encryption at rest where appropriate with isolated managed
keys and rotation"* among the controls the staff side needs. [DEPLOYMENT.md](../DEPLOYMENT.md) tells
an operator to *"Supply a unique randomly generated key through an approved secret manager"* and
then concedes *"Changing a key affects existing signatures and sessions; no production rotation
policy is implemented."* [OPERATIONS_RUNBOOK.md](../OPERATIONS_RUNBOOK.md) tells an incident
responder to *"rotate exposed credentials"* inside a checklist that describes itself as *"mostly a
prospective checklist"*, in a system with *"No production services, dashboards, alerts or on-call
rotation"*. [PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) carries the whole subject as
an open gate: *"secret manager, key generation/rotation and recovery, least-privilege accounts and
access review. Shape checks do not demonstrate entropy or secrecy."* And
[CHANGELOG.md](../CHANGELOG.md) records the one consequence anyone had measured: session-inventory
*"aliases are keyed on `SECRET_KEY`, so a rotation breaks correlation between reports"*.

The requirement is therefore written down four times and the procedure exists nowhere, which leaves
an operator with an instruction and no knowledge of its blast radius. The only thing the tree
enforces about the key is its shape: [ADR 0183](0183-nondebug-config-guards.md) refuses a
non-debug start with an empty, over-long, low-variety or `django-insecure-` secret, and its own
docstring says it *"cannot determine randomness or secrecy"*.
[ADR 0217](0217-deployment-readiness-report.md) reports that check as `secret_key_shape` with the
message *"its entropy and secrecy are not measured here"*. Nothing anywhere says what happens next.

The document meant to close the gap, [SECRET_ROTATION_PLAN.md](../SECRET_ROTATION_PLAN.md), followed
the form [ADR 0227](0227-read-audit-plan.md), [ADR 0229](0229-attribution-gap-plan.md) and
[ADR 0230](0230-mfa-implementation-plan.md) established: an unowned proposal, priced options,
numbered decisions, no implementation. Unlike those, this subject could be measured directly rather
than priced from an inventory — rotating a key needs no new code, only a changed setting — so the
rotation was performed on synthetic data in a throwaway database and every number in the plan is its
result.

## Decision

Measure the key surface, perform one rotation and record its cascade, rewrite the plan so that every
option carries a counted price, and implement no rotation control.

1. **The plan now states measurements instead of adjectives.** A `## What is true today, measured`
   section in three subsections — the key surface, the cascade measured on one real login, and what
   the repository already says — a `## Candidate approach and decisions required` section of eight
   numbered decisions, an `## Options and what each costs` table of seven options, a
   `## Required behavior before any rotation` list of seven items and a
   `## Verification before any enablement` list.
2. **The seven options are A leave key handling as documented, B write the procedure down only,
   C add a read-only pre-rotation impact command, D make rotation graceful with
   `SECRET_KEY_FALLBACKS`, E give each purpose its own key material, F take the key from an external
   secret manager or KMS, and G declare rotation out of Phase 1 scope.** Each carries a price
   counted from this tree and a sentence saying what it still does not answer.
3. **`daroobank/test_secret_rotation_plan.py` pins both halves.** Fourteen tests are database-free
   and pin the plan's structure and the static key surface; six run on the synthetic PostgreSQL
   database and re-perform the rotation, so a change to the guard, the limiters, the session
   commands or the shape check fails here rather than in production.
4. **Nothing was implemented.** No rotation command, no `SECRET_KEY_FALLBACKS` entry, no
   fallback-aware guard, no per-purpose key, no logging configuration and no new dependency. The
   suite's `NothingImplementedTests` pins each absence, including the four direct pins in
   `requirements.in`.

## Measured behavior

All of it from the suite, on synthetic accounts and a throwaway database.

- **One secret, one variable, nine inheritors.** `SECRET_KEY` is
  `os.environ.get('DAROOBANK_SECRET_KEY', '')`, and `daroobank/settings.py` is the only project
  module that reads it. Of the 127 non-test project modules, 9 call `salted_hmac` —
  `catalog/identity_lineage.py:48`, `catalog/projection_repair.py:61`, `catalog/quality_irc.py:45`,
  `catalog/services.py:36`, `clinical/lineage.py:35`, `daroobank/session_guard.py:66`,
  `staff_security/management/commands/list_staff_sessions.py:32`, `staff_security/read_limit.py:42`
  and `staff_security/throttle.py:25` — and **none of the 9 passes an explicit `secret=`**, so all of
  them take `settings.SECRET_KEY`. They use 9 salts, 8 named constants and one inline literal, and 5
  of the 9 compose a per-purpose suffix onto theirs. Six modules sign values through
  `django.core.signing`, whose default key is the same secret.
- **The session store signs its own rows.** `SESSION_ENGINE` is the database backend, its `key_salt`
  is `django.contrib.sessions.SessionStore`, and a row that does not verify decodes to `{}` while
  `"Session data corrupted"` goes to `django.security.SuspiciousSession` — a logger with no
  handlers, because `LOGGING` is `{}` and no project module imports `logging`.
- **A rotation is a silent mass logout.** One synthetic staff account logged in, read `staff/prices/`
  for 200, and wrote one login window and one read window. After the key changed, the same request
  answered **302 to the login page**; the `django_session` row kept its key and its expiry and
  decoded to `{}`; exactly **1** warning was emitted and nothing kept it.
- **The invalidated rows become invisible to the tools that manage them.** `list_staff_sessions`
  reported `scanned: 1, sessions_matched: 0, sessions_unbound: 0` and an empty account list, and
  `revoke_staff_sessions --all --apply` reported `matched: 0, revoked: 0` and left the row in place.
  `cleanup_staff_login_windows --apply` reported `{"deleted": 0, "limit": 500}`, because its
  retention is 24 hours and the orphans were minutes old; no command prunes `PublicReadWindow` at
  all.
- **Both limiters restart and orphan their rows.** The throttle key and the read key both moved, so
  `StaffLoginWindow` went 1 → 2 and `PublicReadWindow` 1 → 2, and both counters read zero again.
- **Guarded writes in flight are denied too.** `recheck_actor` accepted the account with its
  pre-rotation hash and raised `PermissionDenied` afterwards, and still raised with
  `SECRET_KEY_FALLBACKS` populated; 54 `session_auth_hash=` references in 14 non-test modules pass
  one, and `daroobank/actor_recheck.py` lists *"rotation"* among the things its check does not cover.
- **Passwords survive.** The `password` column was byte-identical and the same passphrase still
  verified, because PBKDF2-SHA256 uses a per-password salt. What changed was
  `get_session_auth_hash()`, and with it the session fingerprint and the inventory alias printed for
  the same session key.
- **`SECRET_KEY_FALLBACKS` is a partial rescue this project defeats.** With the old key listed, the
  row decoded fully again, the signed cursor loaded and Django's own `get_user` accepted the stored
  hash — the staff route still answered **302**, because `authorization_fingerprint` embeds
  `get_session_auth_hash()` only. The inventory then showed the session as `bound: true,
  guard_would_end_it: true` under a different alias, and after the guard ran it showed `scanned: 0`:
  Django cycles the session key when a fallback matches and this project's guard deletes the cycled
  row. The limiter keys moved regardless, because `salted_hmac` takes no fallback.
- **The shape check accepts a phrase with no entropy.** The 53-character
  `the-quick-brown-fox-jumps-over-the-lazy-dog-in-tehran` passes `require_nondebug_secret`, while the
  published 35-character debug constant fails it, so a debug key cannot be promoted and a guessable
  production key can.

## Why a plan and not a feature

- Every option is a policy decision before it is code. Who holds the key, what triggers a rotation,
  whether a mass logout may happen silently, how a new key is generated and where the event is
  recorded are the eight decisions the plan numbers, and none of them is answerable by a diff.
- The cheapest honest step is documentation. Option B changes no code and no pin except the document
  links, and it is the only option whose price is zero in a repository that has no owner, no secret
  manager and no production process.
- The graceful option is not graceful here. Option D would have to change
  `daroobank/session_guard.py` and `daroobank/actor_recheck.py` as well as populate a setting, and
  it would still not stabilize the limiter keys or the inventory aliases — so describing
  `SECRET_KEY_FALLBACKS` as a grace period would be a claim this tree contradicts.
- Per-purpose keys multiply the invalidation. Option E moves 9 call sites, the 16-variable inventory
  `daroobank/test_environment_documentation.py` pins, the 12 names Compose sets, the deployment
  guide's configuration reference and possibly one readiness check per key — and its first
  deployment performs every invalidation measured above, once per purpose.
- An external manager needs a network path this repository does not have. Option F adds a dependency
  to a lock CI installs with `--require-hashes` and audits with `pip-audit --strict` (7 names, 78
  hashes today), plus a custody model and a startup failure mode nobody has specified.

## Red checks

Fourteen mutations were applied to a byte-identical backup of the tree, one at a time, and the
suite was run after each. Every file was restored and re-hashed afterwards, and the final run was
green.

| Mutation | Result |
| --- | --- |
| the plan drops its proposal disclaimer | exit 1, 2 of 20 tests fail |
| the plan drops a measured cascade number | exit 1, 1 of 20 tests fail |
| the plan drops a numbered decision | exit 1, 1 of 20 tests fail |
| the plan drops an option row | exit 1, 1 of 20 tests fail |
| the plan stops quoting the release-evidence gate | exit 1, 1 of 20 tests fail |
| the plan misnames one of the nine keyed sites | exit 1, 1 of 20 tests fail |
| `daroobank/settings.py` configures a fallback key | exit 1, 2 of 20 tests fail |
| `daroobank/settings.py` replaces the debug constant | exit 1, 1 of 20 tests fail |
| `daroobank/session_guard.py` learns about fallback hashes | exit 1, 8 of 20 tests fail |
| `daroobank/actor_recheck.py` learns about fallback hashes | exit 1, 1 of 20 tests fail |
| a keyed digest passes its own `secret=` | exit 1, 3 of 20 tests fail |
| `staff_security/read_limit.py` renames its salt | exit 1, 2 of 20 tests fail |
| `daroobank/configuration.py` starts measuring entropy | exit 1, 1 of 20 tests fail |
| `docs/DEPLOYMENT.md` claims a rotation policy exists | exit 1, 1 of 20 tests fail |

All fourteen were caught: the suite exited 1 every time, with between 1 and 8 of its 20 tests
failing, and the widest catch was the guard becoming fallback-aware, which broke the plan
pins, the guard pins and three of the six live rotation measurements at once. After every file
was restored from its backup and re-hashed, the suite ran green again (20 tests, exit 0) and
no file differed by a byte.


## Consequences

- The instruction and its blast radius are now in one place. Whoever authorizes a rotation reads
  what it does — 200 → 302, emptied session rows, an inventory that reports `sessions_matched: 0`, a
  revoke that reports `revoked: 0`, both limiters restarting, guarded writes denied and one
  unhandled warning — and records the decision.
- Introducing a rotation control quietly is no longer possible: a `SECRET_KEY_FALLBACKS` entry, a
  fallback-aware guard or recheck, an explicit `secret=` at a keyed digest, a renamed salt, a
  rotation command, a changed debug constant, a stricter shape check or a key-management dependency
  fails this suite.
- The seven options are priced against counts, so "we should rotate the key" can be answered with
  what it moves: 12 management commands, 9 keyed digests, 6 signing modules, 54 recheck references,
  a 16-variable inventory and a 7-name lock.
- Nothing about the application changed. There is still one secret, no rotation procedure, no
  fallback, no record of a rotation, and the deployment guide still says no production rotation
  policy is implemented — now with a link to what that means.

## Limitations

- **The rotation was performed on synthetic data, once.** One account, one session, one login window
  and one read window in a throwaway database. It says nothing about the volume a real rotation
  produces, how long a mass logout takes to drain, or what an operator sees while it happens.
- **No option was evaluated for security or lawfulness.** Whether a pharmacy staff portal may log
  every operator out without notice, whether a fallback key is an acceptable second exposure, and
  who is allowed to hold the secret are questions for an owner and a reviewer, not for this record.
- **The prices are counted, not run.** No rotation command was prototyped, so no cascade of pin
  failures was measured the way [ADR 0227](0227-read-audit-plan.md) measured 20 failures across 7
  suites. The counts in options C to F are an inventory of what moves, and the real total is unknown
  until an implementation exists.
- **Key custody was not measured because there is none to measure.** No secret manager, KMS, HSM or
  key file exists in this tree, so nothing here says where a production key should live or how it
  should be generated; the plan's decisions 1 and 6 stay open.
- **Nothing was measured about recovery.** A lost key and a rotated key are the same event for
  sessions and signed values and neither touches a password hash, but no restore, re-issue or
  re-login path was exercised, and
  [ADR 0225](0225-populated-rollback-drill.md) covers database rollback rather than key loss.
- The suite pins documents, counts and one measured cascade. It cannot tell whether the eight
  decisions will ever be answered, whether the answers will be adequate, or whether a rotation
  performed under them would succeed; forcing the questions is all this record does.
