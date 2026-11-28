# The secrets and access plan, and what this repository can prove about its one key

`docs/SECURITY.md` asks for three things this tree does not have. On secrets: *"Keep secrets in a
secrets manager/environment, never in Git; the existing `.env.example` contains placeholders
only."* and, in the same table row, *"encryption at rest where appropriate with isolated managed
keys and rotation; least-privilege DB/worker credentials."* On access: *"Users may hold multiple
roles; implement auditable permission grants, revocation and periodic review."*
`docs/DEPLOYMENT.md` turns the first of those into an instruction with no mechanism behind it —
*"those checks cannot establish randomness or secrecy. Supply a unique randomly generated key
through an approved secret manager."* — and repeats it in its variable table, where
`DAROOBANK_SECRET_KEY` is *"a unique randomly generated value from an approved secret manager,
never in Git or shell history. In debug an empty value falls back to a fixed development string"*.
Its release gates then hand the remainder outward: *"Provision TLS, secure headers, database
backups and off-host encrypted retention, monitoring/alerts, access review and restore drills."*
`docs/OPERATIONS_RUNBOOK.md` concedes the same ground from the recovery side — *"Before
deployment, define ownership, encrypted backup cadence, off-host retention, RPO/RTO and recovery
environment according to business and legal requirements; no values have been approved."* — and
the code that reads the database password says only *"Empty password is allowed for
peer/certificate authentication; deployments using password authentication must provide it through
their environment/secret manager."*

`docs/PHASE1_RELEASE_EVIDENCE.md` states the gap in one sentence: *"Shape checks do not
demonstrate entropy or secrecy."* The instrument agrees with it. `check_deployment_readiness`
answers *"the secret has a supported non-debug shape; its entropy and secrecy are not measured
here"*, and the function that produces that answer is documented as *"Reject obvious unsafe
shapes; this cannot determine randomness or secrecy."*

The neighbouring records measured everything except these four things, and each said so.
[ADR 0183](ARCHITECTURE_DECISIONS/0183-nondebug-config-guards.md) built the shape guards.
[ADR 0231](ARCHITECTURE_DECISIONS/0231-secret-rotation-plan.md) and
[the secret-rotation plan](SECRET_ROTATION_PLAN.md) counted the key surface — one variable, 9
`salted_hmac` sites in 9 modules with 9 literal salts and none passing its own `secret=`, 6
modules signing through `django.core.signing`, a session store that signs its own rows — measured
what rotating that one key does to a live login, and then left three things unmeasured on purpose:
*"**Key custody was not measured because there is none to measure.** No secret manager, KMS, HSM
or key file exists in this tree, so nothing here says where a production key should live or how it
should be generated"*, *"**Nothing was measured about recovery.**"*, and, for the key itself, no
measure of how much of it an attacker would have to guess.
[ADR 0236](ARCHITECTURE_DECISIONS/0236-database-connection-plan.md) measured the database half of
least privilege and `docs/SECURITY.md` records it: *"The database half of the least-privilege
requirement above is measured rather than met"*, because *"every connection this application makes
uses the cluster's one non-system role, a superuser that owns all 33 tables"*.
[ADR 0226](ARCHITECTURE_DECISIONS/0226-ci-artifact-gate.md) pinned the shape of the one workflow.
[The authorization review](AUTHORIZATION_REVIEW.md) derived an endpoint-by-endpoint inventory and
labels its own verdict *"**Status: the inventory is derived and drift-checked; the judgement is
unsigned.**"* [ADR 0237](ARCHITECTURE_DECISIONS/0237-monitoring-response-plan.md) established that
nothing in the repository would notice any of this happening.

This document is a **proposal**. It has no owner and no approval, and it must not be read as a
decision. **Nothing is implemented.** It measures the four things the gate line leaves open —
entropy, secrecy, least-privilege accounts and access review — prices eight ways to close them,
and adds a suite that keeps the measurements from drifting. No secret manager was chosen, no key
was generated, no role was split, no review was scheduled and no access was granted or revoked.

## What is true today, measured

### The entropy of every key this tree can run with

Nine distinct key literals appear in tracked files. Exactly one of them is a value
`require_nondebug_secret` accepts, and it is a test fixture. Entropy below is Shannon entropy of
the character distribution, which is a property of the string and not of how it was produced; a
value that is committed to a public repository has that many bits of text and **0 bits of
secrecy**, because the guessing space for a reader of the repository is one value.

| Value | Where it comes from | Characters | Distinct | Bits/char | Bits | Shape check |
| --- | --- | --- | --- | --- | --- | --- |
| `synthetic-only-not-a-real-key-0123456789-abcdefghijklm` | a fixture in 4 tracked test modules | 54 | 30 | 4.617 | 249.3 | accepted |
| `development-only-not-for-production` | `daroobank/settings.py:22`, the debug fallback | 35 | 16 | 3.729 | 130.5 | rejected (length) |
| `replace-with-a-long-random-secret` | `.env.example:4`, the operator template | 33 | 17 | 3.859 | 127.3 | rejected (length) |
| `synthetic-projection-conflict-key` | one test module | 33 | 16 | 3.779 | 124.7 | rejected (length) |
| `synthetic-bounded-projection-key` | one test module | 32 | 17 | 3.906 | 125.0 | rejected (length) |
| `synthetic-concurrent-test-key` | one test module | 29 | 13 | 3.483 | 101.0 | rejected (length) |
| `synthetic-test-secret-key` | 3 tracked test modules | 25 | 11 | 3.175 | 79.4 | rejected (length) |
| `different-local-test-key` | one test module | 24 | 15 | 3.689 | 88.5 | rejected (length) |
| `django-insecure-short` | one test module, a negative control | 21 | 15 | 3.821 | 80.2 | rejected (prefix) |

Three consequences follow, and each is a measurement rather than an opinion.

* The key every `DEBUG=1` process runs with is the second row: 130.5 bits of text that is
  committed to a public repository. Both CI jobs set `DAROOBANK_DEBUG: '1'`, the `django` job sets
  no `DAROOBANK_SECRET_KEY` at all, so all 1,828 tests and every check this repository runs sign
  with a string a reader can copy out of `daroobank/settings.py:22`.
* `compose.yaml` refuses to start without `DAROOBANK_SECRET_KEY` and supplies no value for it, and
  `.env.example` supplies a 33-character placeholder the shape check rejects. Nothing in the tree
  produces a key: `get_random_secret_key`, `secrets.token_urlsafe` and `openssl rand` appear in
  **0 tracked files**, and **0 of the 12 management commands** generate key material.
* For scale, one call to Django's own `get_random_secret_key()` produced 50 characters drawn from
  a 50-character alphabet — 282.2 bits of key space, 243.9 bits of measured Shannon entropy in
  that sample — and `require_nondebug_secret` accepts it.

### The shape check is not monotonic in entropy

`require_nondebug_secret` is 7 lines of one 75-line module and tests four things: length between
50 and 512, at least 5 distinct characters, no `django-insecure-` prefix, and printable ASCII
only. None of those is entropy, and the check's verdicts run against entropy rather than with it:

| Candidate | Characters | Bits | Verdict | Why |
| --- | --- | --- | --- | --- |
| `'a' * 46 + 'bcde'` | 50 | 28.1 | **accepted** | 5 distinct characters, printable, long enough |
| `'daroo' * 10` | 50 | 96.1 | rejected | only 4 distinct characters |
| `'changethis-' * 4 + 'xx'` | 46 | 156.1 | rejected | 4 characters short of the length floor |
| `'abcde'` cycled to 50 characters | 50 | 116.1 | accepted | 5 distinct characters, evenly spread |
| a generated key | 50 | 243.9 | accepted | — |

So the guard accepts a key carrying 28.1 bits — 0.562 bits per character, one character repeated
46 times — while rejecting two keys that carry 96.1 and 156.1 bits. A minimum-entropy floor is
therefore not a tightening that breaks the tree: at floors of 100, 150 and 200 total bits, 3, 8
and 8 of the nine literals above fall below, and **0 of those are accepted today**, because length
already rejects every one of them. At floors of 3.0 and 3.5 bits per character, 0 and 2 fall below
— the 25-character and the 29-character test keys, at 3.17 and 3.48 bits per character — again
with 0 accepted today. The price of a floor is a change to one 7-line function and to the two
suites that call it directly — `daroobank/test_nondebug_configuration.py` (6 tests, 17 assertions)
and `daroobank/test_secret_rotation_plan.py` (20 tests) — and nothing else in the tree moves.

### Where the key value is, and is not, readable

A server was started with `DEBUG=0`, a sentinel key that appears nowhere in the tree, and
`DAROOBANK_TRUST_PROXY_SSL_HEADER=1` with `DAROOBANK_TRUSTED_PROXY_CIDRS=127.0.0.1/32`, because
without the proxy header `SECURE_SSL_REDIRECT` answers every request with a 301 and no body is
measured at all — the first attempt at this measurement fetched 0 bytes and proved nothing.

* **29 routes take no argument** in the resolver of the settings the server ran with. Under
  `DEBUG=0` they answer 10 statuses of 200 and 19 of 404, 27,192 bytes of headers and body in
  total, and the key value appears in **0 of them** and in the 1,817-byte server log **0 times**.
  Under `DEBUG=1` with no key supplied, the same 29 routes answer 31,230 bytes, the staff portal
  is live (17 redirects, `/staff/login/` 200, `/staff/logout/` 405) and the committed constant
  appears in **0 responses**.
* On the host, the value is readable in exactly one place: `/proc/<pid>/environ`, 834 bytes, in
  clear, readable by uid 1001 — the uid the server itself runs as, so any code that can run as the
  application user reads the key without touching the database or the network. It is **not** in
  `ps -wwE -p <pid>` (196 bytes), **not** in `/proc/<pid>/cmdline` (99 bytes), **not** in the
  first 4 KiB of `/proc/<pid>/maps`, **not** in the server log, and after the run it is in **0
  files** of the tree. With `--noreload` the server has **0 child processes**.
* A start that fails says nothing. Five shapes were refused — no variable at all, 20 characters,
  600 characters, the committed debug constant, and a `django-insecure-` prefix — and all five
  exit 1 with the same single sentence, `'DAROOBANK_SECRET_KEY must be a non-debug secret with a
  supported shape.'`. The refused value appears in **0 of the 5** outputs and no other environment
  variable is named in any of them; `daroobank/test_nondebug_configuration.py` pins that absence
  of echo.

### What one boolean decides

Seven non-comment lines of `daroobank/settings.py` mention `DEBUG`, and they decide things that
have nothing to do with each other: line 8 reads it, line 10 is `STAFF_PORTAL_ENABLED = DEBUG` —
and the comment on line 9 states the intent that line reduces to a copy of one boolean, *"The
staff portal is restricted to development until MFA, throttling and audit exist."* — line 14 gates
the login throttle on it, line 20 opens the branch that skips `require_nondebug_secret`, line 34
zeroes HSTS, line 37 gates proxy-header trust and line 63 opens the block that turns on
`SECURE_SSL_REDIRECT` and the rest of the non-debug hardening. Measured consequences:

* 19 of the 29 argument-free routes answer differently between the two settings — all of them
  under `/staff/`, because the portal is enabled exactly when the shape check is skipped. Of the
  55 routes and 43 staff routes `daroobank/test_monitoring_response_plan.py` pins, the 29 and 19
  here are the argument-free subsets.
* Under `DEBUG=1` a raised exception produces Django's technical 500 page. Under `DEBUG=0` the
  same exception through the same handler produces a **145-byte** page with no settings and no
  variables.
* Six of the twelve management commands refuse to run at all unless `settings.DEBUG` —
  `inspect_postgresql_access.py:16`, `inspect_postgresql_schema.py:17`,
  `repair_catalog_projection.py:58`, `cleanup_staff_login_windows.py:24`,
  `list_staff_sessions.py:42` and `revoke_staff_sessions.py:36` — and the seventh,
  `check_deployment_readiness.py:45`, reports `DEBUG` being on as a **failed** check with the
  reason *"DEBUG is on; detailed errors, the staff portal and insecure cookies follow from it"*.
  The only command that can report what privileges the application's database role holds is
  therefore the one that cannot be pointed at a production configuration.
* `compose.yaml` sets `DAROOBANK_DEBUG: ${DAROOBANK_DEBUG:-1}`. The only container path in this
  repository demands a secret at line 26 and then defaults to the one branch that never checks it,
  while `docs/DEPLOYMENT.md` tells an operator the variable *"must stay unset or `0`"*.

### What a debug error page publishes

The technical 500 page was rendered through the real handler, with the test client told not to
re-raise, and one sentinel value injected per run, so that the channels are told apart: one value
that only ever reaches frame locals, and a different value that only ever reaches a setting or a
POST field. Masking in Django 5.2.19 is by **name**, not by value: `hidden_settings` is
`API|AUTH|TOKEN|KEY|SECRET|PASS|SIGNATURE|HTTP_COOKIE` and the substitute is
`********************`.

* 154 uppercase settings are rendered and **10** are masked by name. `DAROOBANK_SECRET_KEY`,
  `POSTGRES_PASSWORD` and the nested `DATABASES['default']['PASSWORD']` are masked. A setting
  named `PEPPER` or `SIGNING_SALT` is printed **in clear**, because neither name matches the
  pattern; the tree has no such setting today, and nothing would notice if one were added.
* The page publishes the database `ENGINE`, `HOST`, `PORT`, `NAME`, `USER` and the generated test
  database name, and masks only the password.
* Every POST field is printed in clear, including one named `password`, because masking request
  data needs `@sensitive_post_parameters`. Every frame local of the raising view is printed in
  clear whatever it is called — `material`, `secret_material` and `key_material` all rendered the
  same value — because masking locals needs `@sensitive_variables`. **0 tracked files** use either
  decorator.
* None of this reaches a client in a correctly configured deployment, where `DEBUG` is off and the
  page is 145 bytes. It reaches anyone who can see an error page in development and in CI, which
  is where every measurement in this document was taken.

### What the committed debug key makes reproducible

Because the debug key is public, its signatures are public. A search cursor was minted offline
with `signing.dumps` under `development-only-not-for-production` and the salt the search route
actually uses, `catalog.search.cursor.v1` from `catalog/services.py:23`: `loads_nonfuture`
**verifies** it, and the same token raises `BadSignature` under any other key. The login
throttle's client key for `127.0.0.1` is likewise computable offline —
`staff_security/throttle.py:25` passes no `secret=`, so
`salted_hmac('staff_security.login.client.v1', '127.0.0.1', algorithm='sha256')` under that
constant is `4fa85bb6678ee5abeec5557def6ceb583fa2cac0f1f4a2e7793135fa8a143278`, which is what a
debug process stores. This is a property of the debug branch, not of a deployment that supplies
its own key; it is measured here because the debug branch is what this repository runs, in CI and
in every test.

### The account the application connects with

[ADR 0236](ARCHITECTURE_DECISIONS/0236-database-connection-plan.md) measured the superuser and
what a throwaway `LOGIN NOSUPERUSER` role was refused. This lane adds three operations that
measurement did not list, each attempted from the role the application connects with and each
**allowed**:

| Attempted from the application's role | Result |
| --- | --- |
| `COPY (SELECT 1) TO PROGRAM 'id -un'` | allowed — runs a program on the database host |
| `pg_read_file('postgresql.conf')` | allowed — 29,655 bytes of a server-side file |
| `CREATE ROLE lane_e_probe_role LOGIN PASSWORD 'x'` | allowed — a new login role, dropped again |
| `ALTER SYSTEM SET log_statement = 'all'` | allowed — a persistent server configuration change, reset again |
| `SELECT ... FROM pg_authid WHERE rolpassword IS NOT NULL` | allowed, and returned **0 rows** here |
| `SELECT count(*) FROM pg_database` | allowed — 3 databases |

Two facts about this sandbox belong with those numbers, because they limit them. The cluster has
**1 login role**, `postgres`, with `rolsuper`, `rolcreaterole`, `rolcreatedb`, `rolreplication`
and `rolbypassrls` all true, and **0 login roles that are not superusers**, alongside 14 built-in
non-login roles. And its `pg_hba.conf` is `trust` for `local` and for `127.0.0.1/32`, so no role
has a stored password hash and the password this probe supplied was never verified — the
`pg_authid` result above says the query was permitted, not that a hash was read.
`docs/SECURITY.md` records the case where a hash was read, from a cluster that had one.

Pricing a split role starts from what the migrations need. Across the 17 project migration modules
`daroobank/test_database_migration_plan.py` pins there are **0 privileged SQL statements**: no
`CREATE EXTENSION`, `CREATE ROLE`, `ALTER ROLE`, `GRANT`, `REVOKE`, `OWNER TO`, `ALTER SYSTEM`,
`SET ROLE`, `SUPERUSER` or `COPY`. The 24 `CreateModel` operations that produce the 33 tables of
the pinned schema need an owner and `CREATE` on the schema, not a superuser. What a non-superuser
cannot do is already measured: it *"could not run migrations without `CREATE` on the schema, could
not create the test database the runner needs"*, so a split costs at least two roles and a grant,
and the test runner keeps needing one that can create a database.

### Who can read or change the key

Read from the GitHub API for this repository on 2026-11-28. These are dated observations of a
service, not properties of the tree, and the suite does not pin them.

* The repository is **public**. It has **3 collaborators and all 3 can push**: `Bamaviitt`
  (write), `daroobankcom-lab` (admin) and `dermatoplus` (write). There are **0 rulesets**, **0
  deployment environments**, and `security_and_analysis` is none. Branch protection on `main` and
  secret scanning enforcement are **not readable with this token** (HTTP 403 and HTTP 404), so
  this document says they are unknown rather than absent.
* No credential in CI comes from a secret store. The workflow contains **0 `secrets.`
  references**, and the complete set of expressions it interpolates is `${{ github.run_id }}` (7
  times) and `${{ github.run_attempt }}` (4 times). From those it builds the application key
  `ci_key_<run_id>_<attempt>` — 20 characters, 72.9 bits of text entropy, and **one candidate**
  for anybody who opens the public run page — plus the database user `runner_<run_id>` and the
  database password `ci_<run_id>_<attempt>`. The five most recent run ids of this repository are
  46144733324, 46155694081, 46159362442, 46159480008 and 46160970236, a span of 16,236,912, and
  every one of them is public.
* What is already good is worth stating precisely, because it is the reason the above matters:
  [ADR 0226](ARCHITECTURE_DECISIONS/0226-ci-artifact-gate.md) pins one workflow of two jobs and 22
  steps that holds exactly `contents: read` and pins all five action references to 40-character
  commit SHAs. A pushing actor cannot widen the token, but any of the 3 can add a `run:` step that
  prints the environment, and the log of a public repository is public.
* Nothing in the tree can answer the question. **0 of the 12 management commands** read
  `pg_authid`, a secret value or a CI secret; the only one that names `SECRET_KEY` is
  `daroobank/management/commands/check_deployment_readiness.py`, and it names it to check its
  shape. `daroobank/postgresql_access.py` reads `pg_roles` flags for `current_user` and
  `session_user`, `pg_stat_ssl` and `has_database_privilege(..., 'CREATE')`, and reports no
  password material.
* `docs/AUTHORIZATION_REVIEW.md` is 207 lines and mentions `SECRET_KEY` **0** times, the word
  `secret` **0** times, a PostgreSQL role **0** times, `collaborator` **0** times and `GitHub`
  **0** times. Its subject is the endpoint surface, and its own status line says the judgement is
  unsigned. Across the tracked `.md` documents other than the ten this lane writes or edits, **5
  lines** pair a cadence word with an access word, and not one of them is about who holds the key
  or who can push to this repository: they are about permission review in
  [the API and permissions plan](API_PERMISSIONS_PLAN.md) and its record, a periodic
  reconciliation in the crawler architecture, how often a data source is updated, and a shell flag
  in the development guide. Over every document in the tree other than those ten, no line
  prescribes a custody review: nothing pairs a cadence with an instruction about who holds the key
  or who can push.

### Custody: an instruction with no mechanism

Six document lines tell an operator to obtain a key from *"an approved secret manager"* or supply
*"a unique randomly generated value"*, in `docs/DEPLOYMENT.md` twice,
`docs/SECRET_ROTATION_PLAN.md` twice,
[ADR 0231](ARCHITECTURE_DECISIONS/0231-secret-rotation-plan.md) and `docs/CHANGELOG.md`.
`docs/SECRET_ROTATION_PLAN.md` states what the absence leaves an operator with: the key is the one
variable the instruction covers, *"No client library"* exists for any manager, and
`daroobank/test_secret_rotation_plan.py` already pins that `requirements.txt` holds no
key-management dependency. **0 documents** name a mechanism as a procedure — no command, no
product, no script, no snippet. Four documents name one in order to report that nothing in the
tree uses it: this plan, its record, `docs/DEPLOYMENT.md` and `docs/CHANGELOG.md`, each of them
naming `get_random_secret_key`, `secrets.token_urlsafe` and `openssl rand` in the same sentence
that says they appear in **0 tracked files**. The instruction and the absence are both measured,
and the absence is the whole of lane E's custody finding: `daroobank/test_secret_rotation_plan.py`
already pins that no key-management dependency exists in `requirements.txt`, and this adds that no
generation path exists in the tree either, so the only way to satisfy the instruction today is to
invent a procedure that nothing records.

Recovery is not re-measured here. [ADR 0231](ARCHITECTURE_DECISIONS/0231-secret-rotation-plan.md)
measured what a rotation does — a staff 200 becomes a 302, the session rows it invalidates are
emptied and hidden from both session commands, both address-keyed limiters restart and orphan
their rows, guarded writes rechecked with the old hash are denied, and one `Session data
corrupted` warning is left on a logger with no handlers — and
[ADR 0232](ARCHITECTURE_DECISIONS/0232-backup-recovery-plan.md) measured the database side. What
neither measured, and what this lane does not either, is a lost key with no copy: there is no
escrow, no second copy and no re-issue path to exercise.

## Candidate approach and decisions required

Eight decisions. Each one is a question this document cannot answer, and none is answered here.

1. **How much entropy is enough, and who says so?** The guard's floor today is 28.1 bits. A number
   between that and 282.2 bits has to be chosen, defended and written down, or the guard stays a
   shape check. Nothing in this repository can supply the authority for that number.
2. **Where does a production key live, and who holds it?** A secret manager, a KMS, an HSM, a file
   with filesystem permissions, or an environment injected by a platform. ADR 0231's decision 1 is
   still open, and this lane measured only that no mechanism exists.
3. **How is a key produced?** A command in this tree, a platform feature, or a documented snippet
   an operator runs elsewhere. Every option has a different answer to who sees the value.
4. **Does the debug fallback stay?** It is what makes development and CI work with no
   configuration, and it is a public string that signs everything a debug process signs.
   Alternatives — generating one per run, refusing to start, keeping it but disabling signing —
   each break something measured above.
5. **Which account does the application connect with?** A superuser is what exists. A split needs
   an owner role, a runtime role, `CREATE` on the schema, and a role that can create the test
   database; the refusals a non-superuser meets are already measured.
6. **Who reviews access, on what cadence, and against what inventory?** The repository has 3
   push-capable actors, 0 rulesets and no readable branch protection; the tree has no command that
   lists any of it and no document that names a cadence.
7. **Do CI credentials come from a store?** They are built from two public numbers today. Moving
   them changes what a fork or a public run can see, and changes the compose job's database
   service.
8. **What is printed on an error page in development?** The masking is by name; two decorators
   exist and are used nowhere. Whether to use them, or to stop rendering settings at all, is a
   decision about development ergonomics that this document only prices.

## Options and what each costs

Eight options, priced against the measurements above. No option is chosen here, none is
recommended and none is excluded; the ordering is by what has to be true first, not by preference.
Prices are counted from the files and pins above, not prototyped.

| Option | What changes | Price, counted | What it still does not answer |
| --- | --- | --- | --- |
| **A. Leave the key surface exactly as measured** | nothing | 0 code files, 0 settings, 0 documents. The gate stays open and the absence stays unmeasured | everything below |
| **B. Write the measured absence into the documents only** | this document, its record, and one sentence in each of seven neighbours, the changelog and the record index | 2 new documents, 8 edited, 1 suite, and the counting pins that move with them | why the key is weak, where it should live, or who holds it |
| **C. Pin the entropy, secrecy and access surface in a suite of its own** | `daroobank/test_secrets_access_plan.py`, which this delivery adds | 1 suite; every number in it is derived from the tree or quoted from this document | nothing changes at runtime; a pin is not a control |
| **D. Add a minimum-entropy floor to the shape check** | `daroobank/configuration.py`, 7 lines today, plus the two suites that call it | 0 of the 9 literals in the tree change verdict at 100, 150 or 200 bits, or at 3.0 or 3.5 bits per character; 6 + 20 tests may need a new fixture | where the value came from, or whether it is secret |
| **E. Replace the debug fallback with a generated per-run key** | `daroobank/settings.py:19-22` and every test that asserts the constant | `daroobank/test_secret_rotation_plan.py` pins the constant as `DEBUG_SECRET`; 1,828 tests run in the branch that would change | production custody, which is a different branch of the same file |
| **F. Split the database account into an owner and a runtime role** | deployment configuration, `compose.yaml`, and the runner's database creation | 0 privileged statements in 17 migration modules; 24 `CreateModel` operations and 33 tables to grant; the measured refusals include `CREATE` on the schema and creating the test database | who creates the roles, who reviews them, or what a compromised runtime role can still read |
| **G. Move CI credentials into a secret store** | `.github/workflows/checks.yml`, 11 interpolations of two public numbers | 0 `secrets.` references today; 2 jobs and 22 steps pinned by ADR 0226, which a change must keep pinned | whether 3 push-capable actors can still read them, which a store does not change |
| **H. Name a secret manager, a generation procedure and a review cadence** | an owner, a product choice and a schedule | 6 document lines ask for it and 0 name a mechanism; 0 commands can report who holds it | whether the choice is lawful, affordable or staffed |

## Required behavior before a key is called managed

Seven requirements. Each is written so that a reader can tell whether it is met, and none is met
today.

1. A key value in use has a measured amount of guessing work behind it, stated as a number and as
   the method that produced it, and the number is above a floor that is written down somewhere
   with a name attached.
2. The value is not committed, not printed by a failed start, not present in any response, log
   line, process listing or file outside the one place it is read from, and the place it is
   readable from is named together with who can read it.
3. Any signature the application accepts can be produced only by a holder of the value, which is
   demonstrably false in the debug branch today and demonstrably true of a deployment that
   supplies its own key.
4. The account the application connects with is the smallest one that runs the migrations, serves
   the routes and creates the test database, and what it can still do is enumerated by running it,
   not by reading a grant list.
5. Somebody can answer "who can read this key, who can change it, and when was that last checked"
   from an inventory, without asking a person to remember.
6. The configuration that skips the shape check, enables the staff portal and renders technical
   error pages is one setting, and a process that has it on cannot also be a process that serves
   the public.
7. Losing the key is a rehearsed event with a named holder of a second copy, or it is documented
   as unrecoverable with the consequences stated.

## Verification before any enablement

Seven checks. Each one is runnable in this repository, or says explicitly what it is not.

- `daroobank/test_secrets_access_plan.py` passes, and its pins are the ones this document quotes:
  the nine key literals with their lengths and verdicts, the entropy of each and of the four
  candidates the shape check judges against entropy, the floors that change 0 verdicts in the
  tree, the mask pattern and its 10 masked settings of 154, the two decorators used in 0 tracked
  files, the seven `DEBUG` lines and the six commands that refuse to run outside it, the 0
  privileged statements in the migration modules, the 0 `secrets.` references and the two
  interpolated expressions in the workflow, the compose default of `1` for `DAROOBANK_DEBUG`, the
  0 mentions of secrets in the authorization review, the 0 generation mechanisms in the tree, and
  the six document lines that ask for a secret manager.
- Every quotation in this document is present **verbatim** in the document, file or record it is
  quoted from, asserted by the suite in both places at once, so a reworded requirement fails a
  test instead of silently diverging from the plan that prices it.
- The suite's red checks were run one at a time on a byte-identical tree, each mutation restored
  and verified by checksum before the next, and every one of them failed the suite — the results
  are in the `Red checks` section of
  [ADR 0238](ARCHITECTURE_DECISIONS/0238-secrets-access-plan.md), and a mutation that no test
  caught is listed there as a gap rather than dropped.
- Nothing this document prices exists: no entropy floor is implemented, no key is generated, no
  second database role exists, no secret is stored in a manager, no decorator was added, no review
  cadence is named, and the throwaway role created to test `CREATE ROLE` was dropped inside the
  same session, as was the `log_statement` change reset by `ALTER SYSTEM RESET`.
- A control added later is caught by a test rather than by a reader: an entropy floor in
  `daroobank/configuration.py`, a generated debug key, a second login role in a fixture, a
  `secrets.` reference in the workflow, a `@sensitive_variables` decorator or a secret manager
  dependency each fails a named pin, and the failure message says which document has to be updated
  with it.
- Whatever is verified is verified the way CI verifies it: `DAROOBANK_DEBUG=1`, an explicit
  `PYTHONHASHSEED`, `--settings=daroobank.synthetic_test_settings` and `--noinput`, against a
  PostgreSQL server whose coordinates come from the environment, with the full suite run to
  completion on two seeds rather than a sample.
- What cannot be verified here is stated rather than approximated: the GitHub API facts are dated
  observations that need a token and are not pinned; branch protection and secret scanning could
  not be read at all; the live-server byte counts came from one `runserver` on one machine and are
  not budgets; no production deployment, no secret manager, no KMS or HSM, no second cluster and
  no non-superuser application account was available to measure, and `docker` is not installed in
  this environment, so the `compose.yaml` facts were read from that file rather than run.
