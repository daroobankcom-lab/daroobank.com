# The secret-rotation plan, and what rotating the one key this project has actually does

`docs/SECURITY.md` asks for *"encryption at rest where appropriate with isolated managed keys and
rotation"* and for *"least privilege"*; `docs/DEPLOYMENT.md` tells an operator to *"Supply a unique
randomly generated key through an approved secret manager"* and then admits *"Changing a key affects
existing signatures and sessions; no production rotation policy is implemented"*;
`docs/OPERATIONS_RUNBOOK.md` tells an incident responder to *"rotate exposed credentials"* with no
procedure, no owner and no deadline; and `docs/PHASE1_RELEASE_EVIDENCE.md` carries the whole subject
as an open gate: *"secret manager, key generation/rotation and recovery, least-privilege accounts
and access review. Shape checks do not demonstrate entropy or secrecy."*

So the requirement is written down four times and the procedure exists nowhere.
[ADR 0231](ARCHITECTURE_DECISIONS/0231-secret-rotation-plan.md) records what this document says and
what it measures. It is not a threat model, not a design review, not a production readiness claim,
and not an implemented or approved key-management control.

This document is a **proposal**. It has no owner and no approval, so it must not be read as a
decision, and it must not treat the single environment variable this project has as a key-management
system. Its prices are counted from the pins and files below, not prototyped: no rotation was
implemented and reverted, so no cascade of pin failures was run — but the rotation itself **was**
performed, on synthetic data in a throwaway database, and every number below is the result of that
run.

## What is true today, measured

Counted on this tree with a live `django.setup()` under `daroobank.synthetic_test_settings`,
`pgserver` and synthetic accounts, plus file reads. They are pinned by
`daroobank/test_secret_rotation_plan.py`.

### The key surface

* **There is one secret, and it comes from one environment variable.**
  `daroobank/settings.py` sets `SECRET_KEY = os.environ.get('DAROOBANK_SECRET_KEY', '')`. In debug
  an empty value falls back to the published 35-character constant
  `'development-only-not-for-production'`; outside debug the value goes through
  `require_nondebug_secret`, which demands 50–512 printable ASCII characters, at least 5 distinct
  ones and no `django-insecure-` prefix. The debug constant fails that check, so a debug key can
  never be promoted, and the check's own docstring says it *"cannot determine randomness or
  secrecy"*.
* **Every keyed digest in the project is keyed by that one secret.** Of the 127 non-test project
  modules, 9 call `django.utils.crypto.salted_hmac` — `catalog/identity_lineage.py:48`,
  `catalog/projection_repair.py:61`, `catalog/quality_irc.py:45`, `catalog/services.py:36`,
  `clinical/lineage.py:35`, `daroobank/session_guard.py:66`,
  `staff_security/management/commands/list_staff_sessions.py:32`, `staff_security/read_limit.py:42`
  and `staff_security/throttle.py:25` — and **none of the 9 passes an explicit `secret=`**, so all
  of them take `settings.SECRET_KEY`. They use 9 literal salts, 8 of them named constants
  (`catalog.identity.lineage.v1`, `catalog.quality.irc.cursor.v1`, `catalog.search.cursor.v1`,
  `catalog.synthetic-projection-repair.v1`, `clinical.draft.lineage.v1`,
  `daroobank.staff.session.inventory.v1`, `daroobank.staff.session.v1`,
  `staff_security.public_read.v1`) plus one inline (`staff_security.login.client.v1`), and 5 of the
  9 compose a per-purpose suffix onto the salt.
* **Six modules also sign values with it.** `catalog/identity_lineage.py`,
  `catalog/projection_repair.py`, `catalog/quality_irc.py`, `catalog/services.py`,
  `clinical/lineage.py` and `daroobank/signed_cursors.py` import `django.core.signing`, whose
  default key is the same secret.
* **A rotation also denies guarded writes rechecked with an old hash.**
  `daroobank/actor_recheck.py` compares a caller-supplied `session_auth_hash` with
  `current.get_session_auth_hash()` and raises `PermissionDenied` on any difference; 54
  references in 14 non-test modules pass one, and that module's own docstring lists
  "rotation" among the things its check is out of scope for.
* **The session store signs its own rows with it.** `SESSION_ENGINE` is the database backend, whose
  `key_salt` is `django.contrib.sessions.SessionStore`, whose `encode` is
  `signing.dumps(..., compress=True)` and whose `decode` is `signing.loads(...)`. A row whose
  signature does not verify decodes to an empty dict, and Django logs `"Session data corrupted"` to
  the `django.security.SuspiciousSession` logger while it does so.
* **Nothing else holds key material, and nothing rotates it.** `SECRET_KEY_FALLBACKS` is `[]` and no
  project module mentions it; `argon2-cffi` and `cryptography` are not installed; the 12 management
  commands include no rotation or rekey command; `cleanup_staff_login_windows` is debug-only and
  deletes at most 500 login windows older than 24 hours, and no command names `PublicReadWindow` at
  all. The deployment readiness report's only secret check is `secret_key_shape`, which reports
  *"the secret has a supported non-debug shape; its entropy and secrecy are not measured here"*.
* **A rotation would be recorded nowhere.** `LOGGING` is `{}`, no project module imports `logging`,
  and the `django.security.SuspiciousSession` logger has no handlers — the absence ADR 0221
  measured and `docs/READ_AUDIT_PLAN.md` priced.

### The cascade, measured on one real login

A synthetic staff account was created, logged in through `staff/login/`, granted
`pricing.view_pricecandidate`, and read `staff/prices/` for 200. One login attempt and one public
read had each written one keyed window row. Then `SECRET_KEY` was changed and everything was
measured again.

* **Every stored session silently becomes anonymous.** The existing `django_session` row still
  decodes to `{}` — the four keys it held (`_auth_user_id`, `_auth_user_hash`,
  `_auth_user_backend`, `staff_auth_fingerprint`) are gone — so the same request that answered 200
  before the rotation answers **302 to the login page** after it, with no message and no error.
* **One warning is emitted and nothing keeps it.** Exactly 1 record, `"Session data corrupted"`,
  reaches `django.security.SuspiciousSession`; that logger has 0 handlers and `LOGGING` is `{}`, so
  the only trace of a mass invalidation is a line on a process's stderr.
* **The rows survive, emptied.** The session row keeps its key and gains empty data and a refreshed
  expiry. `list_staff_sessions` then reports `scanned: 1, sessions_matched: 0, sessions_unbound: 0`
  and an empty `accounts` list — the sessions a rotation invalidated **disappear from the inventory**
  rather than appearing in it — and `revoke_staff_sessions --all --apply` reports
  `matched: 0, revoked: 0, scanned: 1` and leaves the row in place, so the runbook's remediation
  command cannot see or remove them.
* **Both limiters are reset and their old rows orphaned.** The login throttle's client key and the
  read limiter's client key both change, so `StaffLoginWindow` went 1 → **2** rows and
  `PublicReadWindow` 1 → **2**: the pre-rotation rows are unreachable and the counts restart at
  zero. `cleanup_staff_login_windows --apply` then reported `{"deleted": 0, "limit": 500}`, because
  its retention is 24 hours and the orphans are minutes old; the read windows have no prune command
  at all.
* **Every signed value in flight dies.** A cursor signed before the rotation under
  `catalog.search.cursor.v1` raises `BadSignature` afterwards, which the public search route turns
  into a 400 — the one behavior the repository already pins, in
  `catalog/test_pagination.py::test_key_rotation_invalidates_old_cursor`.
* **Guarded writes in flight are denied too.** `recheck_actor` accepted the account with its
  pre-rotation hash before the change and raises `PermissionDenied` afterwards, and it still
  raises with `SECRET_KEY_FALLBACKS` populated, because it compares the primary hash only.
* **Passwords are untouched.** The `password` column is byte-identical and the same passphrase still
  verifies, because PBKDF2-SHA256 uses a per-password salt and not the project secret. What changes
  is `get_session_auth_hash()`, which is itself a `salted_hmac` over the password, and with it the
  session fingerprint and the alias `list_staff_sessions` prints for the same session key.
* **`SECRET_KEY_FALLBACKS` is a partial rescue that this project defeats.** With the old key listed
  as a fallback, the session row decodes fully again, the signed cursor loads, and Django's own
  `get_user` accepts the stored hash. The staff route still answers **302**, because
  `daroobank/session_guard.authorization_fingerprint` embeds `current.get_session_auth_hash()` —
  the primary hash only — and never consults `get_session_auth_fallback_hash()`, so
  `session_matches_account` returns False and the middleware logs the session out. The inventory
  then shows the session as `bound: true, guard_would_end_it: true` under a **different alias**.
  Read again after the guard has run, it reports `scanned: 0` and no accounts at all, because
  Django cycles the session key when a fallback hash matches and this project's guard then deletes
  the cycled row: the session is not preserved, it is replaced and removed. The throttle key and
  the read key change regardless, because `salted_hmac` has no fallback parameter at all.

### What the repository already says about it

* `docs/DEPLOYMENT.md`: *"Changing a key affects existing signatures and sessions; no production
  rotation policy is implemented."*
* `docs/OPERATIONS_RUNBOOK.md`: *"rotate exposed credentials"*, inside an incident checklist that
  describes itself as *"mostly a prospective checklist"*, with *"No production services, dashboards,
  alerts or on-call rotation"* existing.
* `docs/CHANGELOG.md`, on the session inventory: *"aliases are keyed on `SECRET_KEY`, so a rotation
  breaks correlation between reports"*.
* `docs/SECURITY.md`: cursors are *"signed with the Django secret"*, and the control list asks for
  *"isolated managed keys and rotation"*.

## Candidate approach and decisions required

The measured starting point is one secret, nine keyed digests and six signing modules that all
inherit it, a session store that signs its own rows with it, no rotation tooling, no fallback
configuration, no logging, and a guard that would defeat a graceful rotation even if the framework
offers one. Everything below is contingent on the decisions it names, and none of them is answered
here.

1. **Where does the key live, and who holds it?** One environment variable today, which
   `docs/DEPLOYMENT.md` already says should come from an approved secret manager. No client library
   for any secret manager is installed, and this repository has no outbound network path at all.
2. **What triggers a rotation, and who authorizes it?** A schedule, a suspected compromise, a
   personnel change and a lost key each imply a different urgency, and the runbook names the action
   without naming a trigger, an owner or a deadline.
3. **Is a silent mass invalidation acceptable?** Measured, a rotation logs every staff user out at
   their next request, empties their session rows, invalidates every cursor in flight and restarts
   both limiter counters, and the only evidence is one unhandled warning per session read.
4. **May `SECRET_KEY_FALLBACKS` be used at all?** It rescues signed values and Django's own session
   check but not this project's guard, not the limiter keys and not the inventory aliases, so a
   "grace period" would be partial in a way that is easy to misdescribe in a runbook — and each
   fallback is a second live secret with its own exposure window.
5. **What happens to the rows a rotation orphans?** Login windows become prunable only after 24
   hours and only through a debug-only command; read windows have no prune path; emptied session
   rows linger until their expiry and are invisible to both session commands.
6. **How is a new key generated, and how is its entropy verified?** The only check in the tree is a
   shape check that says in its own docstring that it cannot determine randomness or secrecy.
7. **What is recorded about a rotation?** `LOGGING` is `{}`, the one relevant warning has no
   handlers, and ADR 0221 established that this application records no request at all, so any
   record of a rotation would have to come from outside the application or from a decision that
   `docs/READ_AUDIT_PLAN.md` prices.
8. **What is the recovery path when the key is lost rather than rotated?** Sessions and signed
   values die exactly as they do in a rotation, passwords survive, and nothing in this repository
   rehearses the difference.

## Options and what each costs

Prices are counted from the pins and files above, not prototyped.

| Option | What changes | Price, counted | What it still does not answer |
| --- | --- | --- | --- |
| **A. Leave key handling as documented** | nothing | 0 code files, 0 commands, 0 settings, 0 schema pins and 0 lock lines move; this plan, the open gate in `docs/PHASE1_RELEASE_EVIDENCE.md` and the sentence *"no production rotation policy is implemented"* in `docs/DEPLOYMENT.md` stay as they are | whether a single inherited secret with no rotation procedure is acceptable for the sixteen guarded write services, which nobody has answered |
| **B. Write the rotation procedure down only** | `docs/OPERATIONS_RUNBOOK.md` gains a dated procedure and `docs/DEPLOYMENT.md` a consequence list, both stating the measured cascade: 200 → 302, emptied session rows, an inventory that reports `matched: 0`, a revoke that reports `revoked: 0`, windows 1 → 2, a 24-hour prune delay and one unhandled warning | 0 code files and 0 pins except the document links `daroobank/test_document_links.py` counts, and the two documents' own structure pins; the cascade stays exactly as measured | decisions 1, 2, 6 and 7: custody, trigger, generation and record |
| **C. Add a read-only pre-rotation impact command** | a thirteenth management command that counts live sessions, bound and unbound, both window tables' rows, and reports that a rotation will invalidate them, without changing anything | `daroobank/test_command_documentation.py` `COMMANDS` 12 → 13 and the command must appear in the operator documents it scans; `daroobank/test_no_django_admin.py` `OPERATIONAL_COMMANDS` 5 → 6 and the phrase "the five operational commands" in `docs/PHASE1_RELEASE_EVIDENCE.md` and ADR 0218 become six; one new suite; the command itself needs `DEBUG` handling like the other two session commands | that seeing the impact is not the same as being allowed to cause it, and it still records nothing after the fact |
| **D. Make rotation graceful with `SECRET_KEY_FALLBACKS`** | the setting is populated during a grace window, and `daroobank/session_guard.py` learns to compare against `get_session_auth_fallback_hash()` as well as the primary hash | `daroobank/settings.py` gains a project setting that this plan's own suite pins as absent; `session_guard.authorization_fingerprint` changes shape, so `daroobank/test_staff_session_guard.py` (367 lines), the guard's residual-risk text in `docs/AUTHORIZATION_REVIEW.md` and the fingerprint pins in `daroobank/test_mfa_implementation_plan.py` all move; `daroobank/actor_recheck.py` needs the same treatment for the 54 `session_auth_hash=` references in the 14 non-test modules that pass one, or guarded writes keep failing through the grace window; the limiter keys and inventory aliases still change, because `salted_hmac` takes no fallback | how long a fallback is honoured, who removes it, and whether a second live secret is better than one logout |
| **E. Give each purpose its own key material** | the 9 `salted_hmac` sites pass an explicit `secret=` from new settings, and signing gets its own key, so rotating one purpose does not invalidate the others | 9 call sites in 9 modules change; the variable inventory `daroobank/test_environment_documentation.py` pins moves in four places at once — `READS` 16 → 17+, `.env.example` 12 → 13+, `compose.yaml` 12 → 13 names and the word "sixteen" in that suite's own docstring; `docs/DEPLOYMENT.md`'s configuration reference must document each new variable (ADR 0222); `check_deployment_readiness` may need a check per key, against the 10 required checks `daroobank/test_deployment_readiness.py` pins; and the first deployment of it performs every invalidation this plan measured, once per purpose | decisions 1, 6 and 7 unchanged, plus which purposes may share a key and who detects a partial rotation |
| **F. Take the key from an external secret manager or KMS** | the process reads the key from a manager at startup instead of from the environment | a new dependency in a lock CI installs with `pip install --require-hashes` and audits with `pip-audit --strict` (94 lines / 7 names / 78 hashes today), an outbound network path this repository does not have and `docs/DEPLOYMENT.md` does not describe, a custody and access-review model, and every pin in option E if the manager supplies more than one key | who holds the manager's own credentials, and what the application does when the manager is unreachable at startup |
| **G. Declare key rotation out of Phase 1 scope** | `docs/SECURITY.md`, `docs/DEPLOYMENT.md`, `docs/OPERATIONS_RUNBOOK.md` and `docs/PHASE1_RELEASE_EVIDENCE.md` stop asking for rotation and say what is accepted instead | 4 documents reworded plus the residual-risk and 8-row open-question tables of `docs/AUTHORIZATION_REVIEW.md`, which `daroobank/test_authorization_review_drift.py` (13 tests) pins phrase by phrase | whether an incident responder told to "rotate exposed credentials" may do it at all, which is a decision for an owner and not for this file |

## Required behavior before any rotation

1. **Announce the invalidation, or accept it in writing.** A rotation ends every staff session,
   invalidates every cursor in flight and restarts both limiter counters. Whoever authorizes it must
   have read that sentence and recorded the decision, because nothing in the application will report
   it afterwards.
2. **Read the impact before changing the key, not after.** Count live sessions, bound and unbound,
   and both window tables, while the old key can still decode them; after the change the inventory
   reports `sessions_matched: 0` and cannot describe what was lost.
3. **Treat the orphaned rows as part of the procedure.** Old `StaffLoginWindow` rows are prunable
   only after 24 hours and only by a debug-only command; `PublicReadWindow` rows have no prune path;
   emptied `django_session` rows survive until their expiry. State who removes them and with what
   authorization, in an environment where every one of those commands refuses to run outside debug.
4. **Do not describe `SECRET_KEY_FALLBACKS` as a graceful rotation.** It restores signed values and
   Django's own session check only. This project's guard still ends every staff session, and the
   keyed limiter digests and inventory aliases change regardless.
5. **Generate the new key with a stated source of entropy and verify it out of band.** The shape
   check in this repository accepts any 50–512 printable ASCII characters with 5 distinct values,
   which a dictionary phrase satisfies.
6. **Keep the debug constant out of every other environment.** `'development-only-not-for-production'`
   is published in this repository, is 35 characters long, and already fails the non-debug shape
   check; a non-debug process must never be able to start with it.
7. **Record the rotation somewhere that survives the process.** The application's own trace is one
   `"Session data corrupted"` warning per session read on a logger with no handlers, so the record
   has to come from configuration management, the secret manager or the deployment log — and the
   choice is decision 7, not an implementation detail.

## Verification before any enablement

- Rotate the key on synthetic data in a throwaway database and re-measure every number in this
  document: the staff route's status before and after, the session row's decoded keys, the warning
  count, the inventory and revoke outputs, both window tables' row counts, the prune command's
  output, the signed cursor's fate, the unchanged password column and the changed alias.
- Repeat with `SECRET_KEY_FALLBACKS` populated and confirm the partial rescue is still partial:
  signed values and Django's session check recover, the project's guard does not.
- Confirm that a lost key and a rotated key are the same event for sessions and signed values, and
  that neither touches a stored password hash.
- Verify that no command, setting or module this plan names as absent has appeared, and that the
  counts in `daroobank/test_secret_rotation_plan.py` are recomputed rather than deleted if a chosen
  option lands.
- Record named owners and evidence for operational, security and release approval. No production
  enablement, no claim of Phase 1 completion and no key-management certification follows from
  implementing these tests.
