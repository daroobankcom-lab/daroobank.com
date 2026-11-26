# 0230 — the MFA plan, and the measured price of a second factor this tree cannot hold

Date: 2026-11-26
Status: accepted
Suite: `daroobank/test_mfa_implementation_plan.py` (14 tests, ~0.9 s, no database)

## Context

Three documents ask for a second factor, and a fourth refuses to pretend one exists.
[SECURITY.md](../SECURITY.md) lists *"MFA for administrators"*, *"Argon2-compatible password
hashing"* and *"lockout/recovery controls"* among the controls the staff portal needs, then states
*"This is **not a production security model**. No MFA."*
[PHASE1_RELEASE_EVIDENCE.md](../PHASE1_RELEASE_EVIDENCE.md) leaves *"MFA for the sixteen guarded
write services"* unchecked, and [AUTHORIZATION_REVIEW.md](../AUTHORIZATION_REVIEW.md) carries
*"There is no MFA"* as a residual risk and *"Is MFA in scope for Phase 1, and which option in the
unreviewed plan is chosen?"* as an open question with no owner, no date and no answer.

The gap is already enforced rather than merely noted: `daroobank/settings.py` keeps the staff portal
debug-only with the comment *"The staff portal is restricted to development until MFA, throttling
and audit exist"*, and `daroobank/management/commands/check_deployment_readiness.py` fails its
`staff_portal_disabled` check with that reason, so the portal cannot be enabled outside debug
without closing it.

The document meant to close it, [MFA_IMPLEMENTATION_PLAN.md](../MFA_IMPLEMENTATION_PLAN.md), stated
no measurements. It listed five flows an implementation would have to satisfy and left its own
decisions open, which is the right posture and the wrong evidence: nobody could tell whether a
second factor was one model away or whether this tree had anywhere to put one. An earlier prototype
of it was reverted before review (commit `af4d99a`), and [ADR 0227](0227-read-audit-plan.md) and
[ADR 0229](0229-attribution-gap-plan.md) established the form this repository uses instead —
measure the surface, price the options, implement nothing until an owner chooses.

## Decision

Measure the authentication surface, rewrite the plan so that every option carries a counted price,
and implement no factor.

1. **The plan now states measurements instead of adjectives.** It grew from 26 lines to 168: a
   `## What is true today, measured` section of twelve counted facts, a
   `## Candidate approach and decisions required` section of seven numbered decisions, and an
   `## Options and what each costs` table of six options — A leave authentication as documented,
   B a TOTP second factor, C WebAuthn or a passkey, D an account-aware lockout, E delegation to an
   identity provider, F declaring MFA out of Phase 1 scope — each with a price counted from pins
   and files, and a column stating what the option still does not answer. The original plan's four
   sections became six: `Required flows`, `Secret and session boundaries` and `Verification before
   any enablement` are byte-identical to the 26-line original, and the heading
   `Candidate approach and decisions required` is kept with its content rewritten as the seven
   numbered decisions.
2. **Nothing was prototyped this time, and the plan says so.** ADR 0227 priced its option by
   building a model, a migration and a middleware, running nine suites against them and reverting.
   That was not repeated: a factor sits in the login flow 41 test modules exercise, and the options
   here are priced from the schema, migration, lock, environment and browser-harness inventories
   instead. The plan states *"no factor was built and reverted, so no cascade was run and no test
   in this tree exercises a second factor"*.
3. **`daroobank/test_mfa_implementation_plan.py` pins both halves.** That the plan is an unowned
   proposal with six sections, seven numbered decisions and six priced options; that it still
   quotes the requirements it answers; that every module, file, tool and decision record it names
   exists; and that the twelve measurements stay true — one login view rendering two credential
   fields, no factor state in any model or module, a stock `auth.User`, nothing between the
   password and the session, two address-keyed opt-in limiters that are not lockouts, no
   cryptographic library, a hash-pinned audited lock, stateless signed tokens, a browser harness
   with no authenticator, and a 33-table schema built by 17 project migrations.

## Measured behavior

Counted with a live `django.setup()` under `daroobank.synthetic_test_settings`, `pgserver` and the
synthetic data of [ADR 0225](0225-populated-rollback-drill.md) (seed 475502), plus file reads.

| Measurement | Result |
|---|---|
| Login surface | `StaffLoginView` is the only `LoginView` subclass among 127 non-test project modules, `pricing/staff_views.py` the only module with a `LogoutView`; of 55 routes the generated review counts 43 staff rows and 12 public rows; `templates/staff/login.html` renders exactly `username` and `password`; 41 of 236 test modules name the route |
| Factor state | no field on any installed model matches `mfa`, `totp`, `webauthn`, `passkey`, `otp`, `factor`, `device`, `credential`, `challenge` or `recovery`; no project module names a factor mechanism; the 4 modules that mention `MFA` mention it to exclude it; `staff_security` holds 2 models, `PublicReadWindow` and `StaffLoginWindow` |
| Account model | `AUTH_USER_MODEL`, `AUTHENTICATION_BACKENDS`, `PASSWORD_HASHERS`, `SESSION_ENGINE`, `CACHES` and `LOGGING` are all unset in project settings; `auth.User` keeps its 11 stock columns; 19 of the 24 project models point at it through a protected foreign key |
| Between password and session | no project module calls `authenticate()`, `login()`, `cycle_key` or `check_password`; the connected project receivers are `user_logged_in` → `session_guard._bind_fingerprint`, `user_login_failed` → none, `user_logged_out` → none; `LOGGING` is `{}` and no project module imports `logging` |
| Pending-challenge storage | sessions use the database engine with `SESSION_COOKIE_AGE = 3600`, `SESSION_EXPIRE_AT_BROWSER_CLOSE = True`, HttpOnly, SameSite=Lax and Secure only outside debug; `CACHES` is a per-process `LocMemCache` another worker cannot read |
| Limiters | `staff_security/throttle.py` allows 10 attempts per 60 s per HMAC of `REMOTE_ADDR`, its key function takes only `remote_addr`, its window columns are `client_key, started_at, attempts`, it fails open as `unavailable` and runs only with `STAFF_LOGIN_THROTTLE_ENABLED = DEBUG and ...`; `staff_security/read_limit.py` allows 120 reads per 60 s and is opt-in. Neither is account-aware, so neither stops one compromised credential |
| Cryptography | `argon2-cffi`, `cryptography`, `pyotp`, `fido2` and `webauthn` are not installed; `get_hasher('default').algorithm` is `pbkdf2_sha256`; 4 validators with `min_length=12` against the 4096-character `STAFF_PASSWORD_MAX_CHARACTERS`; keyed digests already exist — `salted_hmac` in 9 project modules, `constant_time_compare` in 7, `hashlib` in 9, `hmac` in 1 |
| Dependency and configuration gate | `requirements.in` pins 4 requirements, `requirements.txt` 94 lines / 7 names / 78 hashes, installed with `pip install --require-hashes`, verified by `tools.verify_runtime_lock` and audited by `pip-audit --strict`; `.env.example` documents 12 variables, 6 of them `DAROOBANK_*`, and `compose.yaml` sets the same 6 |
| Signed tokens | `catalog/projection_repair.py` (`TOKEN_AGE = 600`, `MAX_TOKEN_LENGTH = 512`) and `daroobank/signed_cursors.py` mint stateless signed values with no consumption record, and both are unreached by any route or test — the dead surfaces ADR 0229 measures |
| Browser harness | `tests/browser/smoke.cjs` is 1564 lines with zero mentions of an authenticator or `webauthn`, on `playwright-core 1.65.1`, `@sparticuz/chromium 153.0.0` and `@axe-core/playwright 4.14.0`; `daroobank/test_browser.py` holds one test function |
| Price of one factor table | today 33 tables, 279 columns, 111 indexes, 138 constraints, 50 foreign keys and 32 applied migrations from 17 project migrations (catalog 8, clinical 2, ingestion 2, pricing 2, sources 1, staff_security 2); one model makes it table 34, a third `staff_security` migration, 18 project migrations, 33 applied, and 20 attributed models of 25 |

## Why a plan and not a feature

Seven decisions have to be made before an implementation is defensible, and each one changes what
the code must do:

* **Which factors are mandatory** — and whether a fallback may be weaker than the primary, since a
  recovery path is itself an authentication factor. TOTP and WebAuthn differ in phishing
  resistance, browser requirements and dependency surface.
* **Where the pending challenge lives** — the cache is per-process, so a cached challenge vanishes
  between workers and between test processes; the database is shared and already holds sessions, at
  the cost of a table and a migration ([ADR 0216](0216-migration-reversibility.md)).
* **Where the factor secret lives and who holds the key** — a seed or credential needs storage at
  rest and a key that is not `SECRET_KEY`, and `cryptography` is not installed, so the choice is a
  Django-signed value or a new pin in an audited lock.
* **Which interposition point** — a custom backend, a `LoginView` override, a `user_logged_in`
  receiver or middleware each change what the 41 login-route test modules observe, and each is
  invisible to the `daroobank/authorization_review.py` scan of URL patterns and decorators.
* **Who may recover a factor, on what proof** — recovery is the weakest factor by construction, and
  there is no email infrastructure: `EMAIL_*` is unset, so the backend is in-memory.
* **What is recorded about an authentication event** — `LOGGING` is empty and no project module
  imports `logging`, the absence [ADR 0221](0221-no-read-audit.md) measured and
  [ADR 0227](0227-read-audit-plan.md) priced; recording enrollment, factor use and failure needs a
  model, a retention rule and a privacy position.
* **What the lockout policy is** — the throttle is address-keyed, fails open and is debug-gated, so
  making it account-aware is a security decision with a denial-of-service cost against staff and
  needs an always-on setting.

## Red checks

Ten, each applied alone to a working tree whose suite passed, and each reverted from a backup that
`filecmp` then proved byte-identical. Two were green on the first run — overstating option B's price
and changing the measured schema count both passed, because no test pinned the option table's price
cell or the measured sentence exactly — so both pins were added and both checks were run again. All
ten now fail, 15 failures in total, and the restored tree passes all 14 tests:

| Regression | Exit | Failures | Tests that noticed |
|---|---|---|---|
| a decision loses its number in the plan | 1 | 1 | `test_the_plan_is_an_unowned_proposal_with_seven_numbered_decisions` |
| the options heading is renamed | 1 | 2 | that test and `test_every_option_names_a_counted_price_and_something_it_does_not_answer` |
| the plan claims an owner | 1 | 2 | `test_the_plan_is_an_unowned_proposal_with_seven_numbered_decisions` |
| an option is renamed in the plan | 1 | 1 | `test_every_option_names_a_counted_price_and_something_it_does_not_answer` |
| option B's migration price is overstated | 1 | 1 | `test_every_option_names_a_counted_price_and_something_it_does_not_answer` |
| the measured schema count is changed | 1 | 2 | `test_the_schema_and_migration_prices_are_the_measured_ones` |
| the link to this record is removed | 1 | 1 | `test_every_module_document_and_record_the_plan_names_exists` |
| `daroobank/mfa.py` is created and names TOTP | 1 | 3 | `test_no_factor_exists_while_the_plan_says_so`, `test_no_factor_state_exists_in_the_schema_or_the_code`, `test_there_is_one_login_entry_point_rendering_two_credential_fields` |
| `AUTHENTICATION_BACKENDS` becomes a project setting | 1 | 1 | `test_the_account_model_is_stock_django_and_nineteen_models_point_at_it` |
| `ATTEMPT_LIMIT` is raised from 10 to 12 | 1 | 1 | `test_both_limiters_are_address_keyed_opt_in_and_neither_is_a_lockout` |

## Consequences

- The requirement, the gap and the price are now in one place. Whoever chooses an option writes an
  accepted record that supersedes this one and the plan, with every pin it names recomputed in the
  same change.
- Implementing a factor quietly is no longer possible: a model field, a module, a login field, an
  authentication backend, a session setting, a cache backend, a logging configuration, a dependency
  or a route named like a factor fails this suite.
- The six options are priced against counts, not adjectives, so "we should add MFA" can be answered
  with what it moves: 18 project migrations, 34 tables, a new audited pin, two settings that become
  project settings, a documented environment variable and 41 test modules re-run.
- Nothing about the application changed. There is still one factor, no lockout, no factor state and
  no authentication event record, and the portal is still refused outside debug for that reason.

## Limitations

- **The prices are counted, not run.** No prototype was built, so no cascade of pin failures was
  measured the way ADR 0227 measured 20 failures across 7 suites. The counts in option B are an
  inventory of what moves, not an observed failure list, and the real total is unknown until an
  implementation exists.
- **The schema numbers are quoted, not re-measured here.** This suite is database-free; it pins the
  plan's quotation of the 33-table schema and the migration inventory on disk. The live counts
  themselves are pinned by the database-backed suites of ADR 0225, ADR 0227 and ADR 0228.
- No option was evaluated for security. Whether TOTP is acceptable for a pharmacy staff portal,
  whether a passkey can be mandatory for staff who have none, and whether delegation to an identity
  provider is compatible with the throttle's deliberate refusal to trust forwarded headers are
  questions for an owner and a reviewer, not for this record.
- Nothing was measured about performance, availability or cost: no latency figure for an added
  factor, no behavior under a shared cache or multiple workers, no clock-skew tolerance and no
  recovery volume estimate.
- The suite pins documents and counts. It cannot tell whether the seven decisions will ever be
  answered, whether the answers will be lawful, or whether the resulting control will be effective;
  forcing those answers is the only thing the plan does.
