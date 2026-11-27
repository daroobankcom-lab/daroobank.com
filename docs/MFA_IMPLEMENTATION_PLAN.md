# The staff MFA plan, and why the repository has no second factor

`docs/SECURITY.md` asks for "MFA for administrators", "Argon2-compatible password hashing" and
"lockout/recovery controls", and then says plainly that none of it exists: "This is **not a
production security model**. No MFA." `docs/PHASE1_RELEASE_EVIDENCE.md` leaves the line "MFA for the
sixteen guarded write services" unchecked, and `docs/AUTHORIZATION_REVIEW.md` keeps "There is no
MFA" as a residual risk with "Is MFA in scope for Phase 1" as an open question nobody has answered.

That makes this document load-bearing: it is the only artifact between the requirement and the gap,
and [ADR 0230](ARCHITECTURE_DECISIONS/0230-mfa-implementation-plan.md) records what it says and
what it measures. It is not a threat model, not a design review, not a production readiness
claim, and not an implemented or approved authentication control. The earlier prototype was
reverted before review (commit `af4d99a` of 2026-11-26) and nothing was implemented.

This document is a **proposal**. It has no owner and no approval, so it must not be read as a
decision, and it must not treat the existing password form as anything other than the single factor
it is. Its prices are counted from the pins and files below, not prototyped: no factor was built and
reverted, so no cascade was run and no test in this tree exercises a second factor.

## What is true today, measured

The numbers below were counted on this tree with a live `django.setup()` under
`daroobank.synthetic_test_settings`, `pgserver` and the synthetic data of ADR 0225 (seed 475502),
plus file reads. They are pinned by `daroobank/test_mfa_implementation_plan.py`.

* **The gate is already written down.** `daroobank/settings.py` keeps the staff portal debug-only
  with the comment "The staff portal is restricted to development until MFA, throttling and audit
  exist", and `daroobank/management/commands/check_deployment_readiness.py` fails its
  `staff_portal_disabled` check with that reason. Enabling the portal outside debug is therefore
  already refused, for exactly this gap.
* **One login entry point, one factor.** `staff/login/` resolves to `StaffLoginView`, the only
  `LoginView` subclass among the 127 non-test project modules, and `staff/logout/` to the only
  `LogoutView`; of 55 routes the generated review counts 43 staff rows and 12 public rows. The
  login template renders exactly two credential fields, `username` and `password`. 46 of the
  242 test modules, excluding the suite that pins this plan, name that route, so changing its
  flow is not a local edit.
* **No factor state exists anywhere.** A scan of every field name on every installed model for
  `mfa`, `totp`, `webauthn`, `passkey`, `otp`, `factor`, `device`, `credential`, `challenge` and
  `recovery` returns nothing, and no project module mentions TOTP, WebAuthn, a passkey or an OTP.
  The four modules that mention `MFA` mention it to exclude it: the two comments and the portal
  gate in `daroobank/settings.py`, plus the scope notes of `daroobank/session_guard.py`,
  `daroobank/actor_recheck.py` and
  `daroobank/management/commands/check_deployment_readiness.py`.
* **The account model is stock Django.** `AUTH_USER_MODEL` is not set in project settings, so the
  user model is `auth.User` with its 11 stock columns, and 19 of the 24 project models point at it
  through a protected foreign key (ADR 0220). A factor needs either a new project model holding an
  actor foreign key or a custom user model, and Django does not swap `AUTH_USER_MODEL` after the
  tables exist.
* **Nothing interposes between the password and the session.** `AUTHENTICATION_BACKENDS` is not set
  either, so the default `ModelBackend` runs alone; no project module calls `authenticate()` or
  `login()`, none calls `cycle_key`, and none calls `check_password`. The session key is cycled
  only by Django's own `login()`. Exactly one project receiver is connected to `user_logged_in`
  (`session_guard._bind_fingerprint`) and none to `user_login_failed` or `user_logged_out`, so
  nothing in the application observes a failed login except the optional throttle window.
* **A copied session cookie is not detectable.** The only request-time comparison is
  `daroobank/session_guard.py`, whose fingerprint is a keyed digest of `is_active`, `is_staff`,
  `is_superuser`, the session-auth hash and the sorted permission set — nothing about the client,
  the device, the address or the request. No project code rotates a session key,
  `SESSION_SAVE_EVERY_REQUEST` is `False` and the key lives an hour, so a cookie replayed from
  anywhere while the account state is unchanged passes the guard. That is the replay gap
  `docs/PHASE1_RELEASE_EVIDENCE.md` lists as open, and none of the options below closes it on its
  own.
* **A pending challenge has nowhere obvious to live.** Sessions use the database engine, with
  `SESSION_COOKIE_AGE = 3600`, `SESSION_EXPIRE_AT_BROWSER_CLOSE = True`, HttpOnly, SameSite=Lax
  and Secure only outside debug. `CACHES` is not configured, so the default is a per-process
  local-memory cache that another worker cannot read, and `LOGGING` is empty — no project module
  imports `logging`, the absence ADR 0221 measured and `docs/READ_AUDIT_PLAN.md` priced.
* **The limiters are address-keyed, opt-in and not lockouts.** `staff_security/throttle.py` allows
  10 attempts per 60 seconds per HMAC of the peer address, fails open as `unavailable`, and is
  enabled only in debug with `STAFF_LOGIN_THROTTLE_ENABLED = DEBUG and ...`;
  `staff_security/read_limit.py` allows 120 reads per 60 seconds per scope and is opt-in by
  environment variable. `staff_security/models.py` documents both windows as holding an "HMAC of
  normalized REMOTE_ADDR, not a raw IP or account identifier". Neither is account-aware, so
  neither stops one compromised credential, and neither records a refusal.
* **No cryptographic primitive is available for a secret at rest.** `argon2-cffi` and
  `cryptography` are not installed, `get_hasher('default').algorithm` is `pbkdf2_sha256`, and
  `AUTH_PASSWORD_VALIDATORS` is four stock validators with `min_length=12` against the
  4096-character form limit `STAFF_PASSWORD_MAX_CHARACTERS` in `daroobank/forms.py`. The tree
  already contains keyed digests — `django.utils.crypto.salted_hmac` in 9 project modules and
  `constant_time_compare` in 7, `hashlib` in 9 and `hmac` in 1 — so signing is available, and
  `docs/SECURITY.md` says so; what is not available is storage for a TOTP seed or a WebAuthn
  credential, nor a hasher upgrade.
* **A dependency is a gated event.** `requirements.in` pins four direct requirements and
  `requirements.txt` pins 7 names across 78 hashes in 94 lines, installed with
  `pip install --require-hashes`, verified by `tools.verify_runtime_lock` and audited by
  `pip-audit --strict` in CI (`.github/workflows/checks.yml`). A TOTP library is a new pin with a
  new audit surface; a WebAuthn library is a much larger one.
* **Signed tokens exist, but none is a single-use challenge.** `catalog/projection_repair.py`
  (`TOKEN_AGE = 600`, `MAX_TOKEN_LENGTH = 512`, `signing.loads(..., max_age=TOKEN_AGE)`) and
  `daroobank/signed_cursors.py` both mint stateless signed values with no consumption record, so
  they are the wrong shape for replay protection. Both are unreached by any route and any test,
  the dead surfaces `docs/ATTRIBUTION_GAP_PLAN.md` measures; being stateless, neither is a
  challenge that a replay cannot reuse.
* **The browser harness cannot test an authenticator.** `tests/browser/smoke.cjs` is 1564 lines of
  `@axe-core/playwright` checks driven by `playwright-core 1.65.1` and `@sparticuz/chromium
  153.0.0`, installed with `npm ci --ignore-scripts` and audited with `npm audit
  --audit-level=info`. It contains no mention of an authenticator and no `webauthn` step, and
  `daroobank/test_browser.py` has one test function, so a WebAuthn factor would need a virtual
  authenticator this harness does not have.
* **A factor table has a counted price.** The schema is 33 tables, 279 columns, 111 indexes, 138
  constraints, 50 foreign keys and 32 applied migrations, built by the project's 17 migrations
  (catalog 8, clinical 2, ingestion 2, pricing 2, sources 1, staff_security 2). One more model is
  table 34, a third `staff_security` migration, project migrations 17 → 18 and applied 32 → 33.

### Dependencies and configuration

`.env.example` documents 12 variables, 6 of them `DAROOBANK_*`, and `compose.yaml` sets the same
6; `daroobank/test_environment_documentation.py` counts both, so a factor secret or issuer is a
new documented and counted variable.

## Candidate approach and decisions required

The measured starting point is a single-factor password form on a stock `auth.User`, with no
factor state, no account-aware limiter, no challenge store, no logging, no crypto library and a
hash-pinned, CI-audited dependency lock. Everything below is contingent on the decisions it names,
and none of them is answered here.

1. **Which factors are mandatory, and may a fallback be weaker than the primary?** The evidence
   checklist asks for MFA over sixteen guarded write services. TOTP and WebAuthn have different
   phishing resistance, different browser and harness requirements and different dependency
   surfaces, and a recovery path is itself an authentication factor.
2. **Where does the pending challenge live?** `CACHES` is a per-process `LocMemCache`, so a cache
   challenge disappears between workers and between test processes. The database is shared and
   already holds sessions, at the cost of a table and a migration (ADR 0216).
3. **Where does the factor secret live, and who holds the key?** A TOTP seed or a WebAuthn
   credential needs storage at rest and a key that is not `SECRET_KEY`; `cryptography` is not
   installed, so either the seed is stored under a Django-signed value or a new dependency lands
   in the audited lock.
4. **Which interposition point?** A custom `AUTHENTICATION_BACKENDS` entry, a `LoginView` override,
   a `user_logged_in` receiver or middleware each change what the 41 login-route test modules
   observe, and each is invisible to the `daroobank/authorization_review.py` scan of URL patterns
   and decorators.
5. **Who may recover a factor, on what proof, and how is that not a bypass?** Recovery is the
   weakest factor by construction, and there is no email infrastructure: `EMAIL_*` is unset, so the
   backend is in-memory.
6. **What is recorded about an authentication event?** `LOGGING` is empty and no project module
   imports `logging`; ADR 0221 measured that absence, `docs/READ_AUDIT_PLAN.md` priced it, and
   `daroobank/actor_recheck.py` says an authentication event is "out of scope" for its window.
   Recording enrollment, factor use and failure needs a model, a retention rule and a privacy
   position.
7. **What is the lockout policy?** The throttle is address-keyed, fails open and is debug-gated, so
   it cannot stop one compromised credential. Making it account-aware is a security decision with
   a denial-of-service cost against staff, and it needs an always-on setting rather than a
   debug-only one.

## Options and what each costs

Prices are counted from the pins and files above, not prototyped.

| Option | What changes | Price, counted | What it still does not answer |
| --- | --- | --- | --- |
| **A. Leave authentication as documented** | nothing | 0 routes, 0 modules, 0 schema pins and 0 lock lines touched; this plan, the residual in `docs/AUTHORIZATION_REVIEW.md` and the failing `staff_portal_disabled` check stay exactly as they are | whether a debug-only portal is the intended production shape, which the review already asks and nobody has answered |
| **B. TOTP second factor, standard library only** | one model holding an actor foreign key and a signed seed, a pending-challenge store, an interposed step in `StaffLoginView`, enrollment and revocation routes, an account-aware lockout, and 41 test modules downstream of the login flow re-run | project migrations 17 → 18, `staff_security` 2 → 3, applied 32 → 33, schema 33 → 34 tables and 19 → 20 attributed models of 25; `requirements.in` 4 → 5 pins, `requirements.txt` 94 lines / 7 names / 78 hashes all move, `pip-audit --strict` and `tools.verify_runtime_lock` re-run; `AUTHENTICATION_BACKENDS` and `CACHES` become project settings; `.env.example` 12 → 13+ variables, `compose.yaml` 6 → 7, both counted by `daroobank/test_environment_documentation.py` | decisions 5, 6 and 7: recovery proof, what an authentication event may record, and whether a shared seed store is acceptable |
| **C. WebAuthn or passkey primary** | everything in B, plus a challenge and credential ceremony, an RP identifier, and a browser harness that can present a virtual authenticator | B's prices, plus a `cryptography`-scale dependency in a lock CI installs with `--require-hashes` and audits with `pip-audit --strict`; `tests/browser/smoke.cjs` (1564 lines, `playwright-core 1.65.1`, `@sparticuz/chromium 153.0.0`, audited by `npm audit --audit-level=info`) gains authenticator steps it has never had, against the one test in `daroobank/test_browser.py` | whether a passkey can be mandatory for staff who have none, and who issues the first one |
| **D. Account-aware lockout, always on, no second factor** | the throttle keys on the account as well as the peer address, loses its debug gate, and records refusals | `staff_security/throttle.py` rewritten, `STAFF_LOGIN_THROTTLE_ENABLED = DEBUG and ...` becomes an always-on setting, `daroobank/test_deployment_readiness.py` and every login-route test in the 41 modules re-run; the "HMAC of normalized REMOTE_ADDR, not a raw IP or account identifier" documentation of both window models becomes false | that it is still one factor, so it does not satisfy the MFA line in `docs/PHASE1_RELEASE_EVIDENCE.md` |
| **E. Delegate authentication to an identity provider at the edge** | the portal trusts a proxy or an OIDC session instead of its own password form | no factor code here, but it contradicts the measured posture: `TrustedProxySchemeMiddleware` maps only the scheme and only outside debug with `DAROOBANK_TRUST_PROXY_SSL_HEADER=1`, the throttle deliberately ignores forwarded headers, and `daroobank/session_guard.py` plus 54 `session_auth_hash=` call sites in 15 modules are keyed to a Django session and a password hash an external provider would not produce | who operates the provider, how a revocation there reaches a session here, and whether anything in this repository can still observe an authentication event |
| **F. Declare MFA out of Phase 1 scope** | `docs/SECURITY.md`, `docs/PHASE1_RELEASE_EVIDENCE.md` and `docs/AUTHORIZATION_REVIEW.md` stop asking for it | 0 code files, 0 schema pins, 0 lock lines and 0 routes move; 3 documents are reworded, and the review's residual-risk and 8-row open-question tables change with them — `daroobank/test_authorization_review_drift.py` (13 tests) pins those tables phrase by phrase | whether the sixteen guarded write services may be reachable with one factor, which is a decision for an owner, not for this file |

## Required flows

1. **Enrollment:** An authenticated, separately authorized user starts enrollment over a verified TLS channel. Provisioning secrets or registration challenges are short-lived, single-use and never put into URLs or logs. Confirm possession before activating a device; incomplete enrollments expire and are revocable. Handle re-enrollment as a sensitive account change, with independent notification and audit policy. An enrollment bootstrap without an existing factor must be explicitly authorized.
2. **Password and challenge:** Successful password verification creates a short-lived, server-side pending challenge, not a fully authenticated privileged session. It must be bound to the intended account and session, invalidated on logout, expiry, password/factor change or successful use, and never be usable on other endpoints as full authentication. Cycle the session key at privilege changes. All applicable login entry points must enforce the same factor policy; middleware and direct backend/service calls cannot silently bypass it.
3. **Verification:** Reject malformed, expired, replayed or mismatched challenges without exposing whether an account, device or code exists. Verify against an approved library and controlled clock policy. For TOTP, define time-step and allowed skew, handle clock rollback, and atomically consume a per-device counter under concurrent requests. A reused step must not issue a second session; database timeout/error must fail closed. WebAuthn requires correct origin, RP ID, challenge, credential and authenticator checks according to the selected library and policy. Do not implement cryptographic primitives ad hoc.
4. **Recovery and revocation:** Define a separately authorized recovery procedure, short-lived single-use recovery credentials where approved, lost-device handling, revocation of pending challenges and sessions, and independent audit/notification. Recovery must not become an unmonitored bypass of normal MFA. Never store plaintext recovery codes. Define key compromise and emergency access procedures before enabling the feature.
5. **Abuse and operations:** Specify shared, account-aware and network-aware rate limits and failure behavior, considering distributed attacks, lockout denial of service, proxy identity and legitimate recovery. Set ownership for monitoring, alerts, clock synchronization, secret rotation, backups and incident response. The existing debug-only per-IP limiter is not sufficient.

## Secret and session boundaries

TOTP seeds must be encrypted at rest using reviewed authenticated encryption and keys from an approved secret-management system, not hard-coded or placed in version control. Bind ciphertext to the account/device context; define key rotation and old-key decryption, secure backup and disaster recovery. Encryption alone does not protect against a compromised application with key access. Protect device and recovery records from unauthorized changes, and ensure logs, exceptions, telemetry, templates and test fixtures do not expose secrets, codes, signed tokens or session identifiers. Data retention and access must be approved.

## Verification before any enablement

- Synthetic unit, PostgreSQL integration and browser tests cover enrollment, expiration, CSRF, session rotation, wrong user/device, missing/invalid/replayed factors, revocation, recovery, and disabled/default-off behavior. Include concurrent submissions proving at most one successful consumption for the tested replay schedule, plus transaction rollback and timeout handling.
- Test every supported authentication entry point and sensitive staff route, account changes while a challenge is pending, already-authenticated sessions, recovery attempts, key rotation and failure of the secret manager. Verify safe behavior with multiple application workers and a reverse proxy.
- Independently review protocol/library choice, dependency provenance, cryptographic key handling, anti-replay and race design, accessibility, logging and incident procedures. Exercise deployment and recovery in staging with synthetic data, including restoration of encrypted device state and separate key custody.
- Record named owners and evidence for operational, security, legal/privacy and release approval. No real accounts or data, production enablement, or claim of Phase 1 completion follows merely from implementing these tests.
