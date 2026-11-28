# 0238 — the secrets and access plan, and what this repository can prove about its one key

Date: 2026-11-28
Status: accepted
Suite: `daroobank/test_secrets_access_plan.py` (41 tests, ~0.3 s, all of them database-free)

## Context

`docs/PHASE1_RELEASE_EVIDENCE.md` leaves the gate open in one sentence — *"Shape checks do not
demonstrate entropy or secrecy."* — and names four things that are missing: *"secret manager, key
generation/rotation and recovery, least-privilege accounts and access review"*. Three records had
already measured around those four and each recorded what it did not measure.

[ADR 0183](0183-nondebug-config-guards.md) built `require_nondebug_secret` and its own docstring
limits it: *"Reject obvious unsafe shapes; this cannot determine randomness or secrecy."*
[ADR 0231](0231-secret-rotation-plan.md) counted the key surface — one environment variable, 9
`salted_hmac` sites in 9 modules with 9 literal salts and none passing its own `secret=`, 6
modules signing through `django.core.signing`, a session store that signs its own rows — measured
the cascade a rotation produces on one real login, and left three things open in its own
Limitations: *"**Key custody was not measured because there is none to measure.** No secret
manager, KMS, HSM or key file exists in this tree"*, *"**Nothing was measured about recovery.**"*,
and no measure of how much of the key an attacker would have to guess.
[ADR 0236](0236-database-connection-plan.md) measured the database half of least privilege, and
`docs/SECURITY.md` carries its verdict: *"The database half of the least-privilege requirement
above is measured rather than met"*, because *"every connection this application makes uses the
cluster's one non-system role, a superuser that owns all 33 tables"*.
[ADR 0226](0226-ci-artifact-gate.md) pinned the workflow's shape,
[ADR 0217](0217-deployment-readiness-report.md) pinned the readiness instrument that reports *"its
entropy and secrecy are not measured here"*, [ADR 0237](0237-monitoring-response-plan.md)
established that nothing would notice a key being misused, and
[the authorization review](../AUTHORIZATION_REVIEW.md) derived an endpoint inventory whose own
status line reads *"**Status: the inventory is derived and drift-checked; the judgement is
unsigned.**"*

So the shape of the key was checked, the cascade of changing it was measured, the endpoint surface
was inventoried and the database role was characterised — and nobody had measured how much key
there is, where the value can be read, what the debug branch does with a key that is committed to
a public repository, or who can read or change any of it. Four documents ask for those answers:
`docs/SECURITY.md` (*"Keep secrets in a secrets manager/environment, never in Git"*, *"isolated
managed keys and rotation; least-privilege DB/worker credentials"*, *"auditable permission grants,
revocation and periodic review"*), `docs/DEPLOYMENT.md` (*"Supply a unique randomly generated key
through an approved secret manager"*, and `access review` among its release gates) and
`docs/OPERATIONS_RUNBOOK.md` (*"define ownership ... according to business and legal requirements;
no values have been approved"*).

## Decision

Measure the four open items, price eight ways to close them, implement none of them, and pin the
measurements so they cannot drift.

1. **Nothing is implemented.** No entropy floor was added, no key was generated, no debug fallback
   was replaced, no database role was split, no secret was moved into a store, no decorator was
   added to a view, no review cadence was named and no access was granted or revoked. The one
   privileged role created to test whether `CREATE ROLE` is permitted was dropped inside the same
   session, and the one `ALTER SYSTEM SET` was reset by `ALTER SYSTEM RESET`.
2. **Entropy is measured as a property of the strings this tree can actually run with**, not as a
   property of a generator nobody uses: all nine key literals in tracked files, the four
   candidates that show the shape check judging against entropy rather than with it, and the
   effect a floor would have on the tree today.
3. **Secrecy is measured as a set of channels**, each answered separately: every argument-free
   route on a live server under both values of `DEBUG`, the server log, the process environment,
   the process listing, the command line, the tracked tree, the text of a failed start, and the
   rendered error page of the branch CI runs in.
4. **Least privilege is measured by attempting**, from the role the application connects with, the
   operations an application account should not have, and by counting what a split would have to
   grant. What [ADR 0236](0236-database-connection-plan.md) already measured is cited, not
   repeated.
5. **Access review is measured against the repository as it is configured**, through the GitHub
   API, and against the tree, by asking which command or document could answer *"who can read this
   key today"*. Those API observations are dated and are **not pinned**, because they are facts
   about a service and a token rather than about this tree.
6. **No option is chosen, recommended or excluded.** The plan's eight options are priced in
   counted files, pins and verdicts, and its eight decisions stay open for an owner.
7. **The measurements live in a suite of their own**, `daroobank/test_secrets_access_plan.py`,
   which re-derives every number that is a property of the tree and quotes every number that is a
   property of one run, one service or one machine.
8. **Neighbouring documents are patched with one sentence each** so that a reader of
   `docs/SECURITY.md`, `docs/DEPLOYMENT.md`, `docs/OPERATIONS_RUNBOOK.md`,
   `docs/TESTING_STRATEGY.md`, `docs/SECRET_ROTATION_PLAN.md` or `docs/PHASE1_RELEASE_EVIDENCE.md`
   reaches this record, and the changelog and the record index carry it.

## Measured behavior

Everything below was measured on 2026-11-28 against this tree, in the sandbox described under
Limitations. Numbers that the suite re-derives are marked **(pinned)**; numbers that come from one
run, one service or one machine are marked **(one run)**.

- **Nine key literals exist in tracked files and exactly one is accepted** by
  `require_nondebug_secret`: the 54-character test fixture at 249.3 bits, present in 4 tracked
  modules. The debug fallback `development-only-not-for-production` is 35 characters and 130.5
  bits and is rejected for length; `.env.example`'s placeholder is 33 characters and 127.3 bits
  and is rejected for length. **(pinned)**
- **The key every `DEBUG=1` process runs with is committed to a public repository.**
  `daroobank/settings.py:22` supplies it when the environment does not, both CI jobs set
  `DAROOBANK_DEBUG: '1'`, the `django` job sets no key at all, and
  `daroobank/synthetic_test_settings.py` does `from .settings import *`, so all 1,828 tests sign
  with that string. **(pinned)**
- **The shape check is not monotonic in entropy.** It accepts a 50-character key carrying 28.1
  bits (0.562 bits per character, one character repeated 46 times) and rejects keys carrying 96.1
  bits (4 distinct characters) and 156.1 bits (46 characters). It is 7 lines,
  `configuration.py:10-16`, of a 75-line module. **(pinned)**
- **A minimum-entropy floor would change nothing in this tree.** At floors of 100, 150 and 200
  total bits, 3, 8 and 8 of the nine literals fall below; at 3.0 and 3.5 bits per character, 0 and
  2 fall below — and in every case **0 of those literals are accepted today**, because length
  already rejects them. For scale, one `get_random_secret_key()` call produced 50 characters from
  a 50-character alphabet: 282.2 bits of key space, 243.9 bits of measured Shannon entropy.
  **(pinned)**
- **Nothing in the tree can produce a key.** `get_random_secret_key`, `secrets.token_urlsafe` and
  `openssl rand` appear in **0 tracked files**, and **0 of the 12 management commands** generate
  key material, while 6 document lines ask an operator to obtain a key from *"an approved secret
  manager"* and **0 documents** name a mechanism. **(pinned)**
- **The key value leaves the process in exactly one measured channel.** On a live server under
  `DEBUG=0` with a sentinel key: 29 argument-free routes, 10 statuses of 200 and 19 of 404, 27,192
  bytes of headers and body, and the value in **0** of them; a 1,817-byte server log without it;
  `/proc/<pid>/environ` (834 bytes) **with it in clear**, readable by the uid the server runs as;
  `ps -wwE` (196 bytes), `/proc/<pid>/cmdline` (99 bytes), the first 4 KiB of `/proc/<pid>/maps`
  and the tracked tree all without it; 0 child processes. **(one run)**
- **A failed start echoes nothing.** Five refused shapes — missing, 20 characters, 600 characters,
  the committed constant, a `django-insecure-` prefix — all exit 1 with the identical single
  sentence, the refused value appears in 0 of the 5 outputs, and no other environment variable is
  named. `daroobank/test_nondebug_configuration.py` already pins the absence of echo. **(one
  run)**
- **Under `DEBUG=1` the same 29 routes answer 31,230 bytes and the staff portal is live** — 17
  redirects, `/staff/login/` 200, `/staff/logout/` 405 — with the committed constant in **0**
  responses. 19 of the 29 answer differently between the two settings, all of them under
  `/staff/`. **(one run)**
- **Seven non-comment lines of `settings.py` mention `DEBUG`** (8, 10, 14, 20, 34, 37, 63), and
  line 10 is `STAFF_PORTAL_ENABLED = DEBUG`: the portal is enabled exactly when the shape check is
  skipped. Six of the twelve commands refuse to run unless `settings.DEBUG`, and
  `check_deployment_readiness.py:45` reports `DEBUG` being on as a failed check. `compose.yaml`
  sets `DAROOBANK_DEBUG: ${DAROOBANK_DEBUG:-1}`, so the only container path demands a secret at
  line 26 and defaults to the branch that never checks it. **(pinned)**
- **Django's masking of an error page is by name, not by value.** `hidden_settings` is
  `API|AUTH|TOKEN|KEY|SECRET|PASS|SIGNATURE|HTTP_COOKIE`; 154 uppercase settings are rendered and
  10 are masked. `DAROOBANK_SECRET_KEY`, `POSTGRES_PASSWORD` and the nested database `PASSWORD`
  are masked, while a setting named `PEPPER` or `SIGNING_SALT` — neither of which this tree
  defines, both of which were injected to observe the page — would be printed in clear, and seven
  tracked modules already assign a constant whose name the pattern misses, `CURSOR_SALT` in five
  of them plus `SALT` and `SALTS`, whose values the page would print for the same reason. Every
  POST field is printed in clear, including one named `password`, and every frame local is printed
  in clear whatever it is called, because masking those needs `@sensitive_post_parameters` and
  `@sensitive_variables` — and **0 tracked files** use either. The page publishes the database
  engine, host, port, name, user and test-database name. Under `DEBUG=0` the same exception
  produces a 145-byte page with none of it. **(pinned, except the byte counts)**
- **The committed debug key makes signatures reproducible.** A search cursor minted offline under
  that constant with the salt the search route uses, `catalog.search.cursor.v1`
  (`catalog/services.py:23`), is verified by `loads_nonfuture`, and the same token raises
  `BadSignature` under any other key. The login throttle's client key for `127.0.0.1` is
  computable offline and equals
  `4fa85bb6678ee5abeec5557def6ceb583fa2cac0f1f4a2e7793135fa8a143278`. **(pinned)**
- **From the role the application connects with, four operations an application account should not
  have are permitted**: `COPY (SELECT 1) TO PROGRAM`, which runs a program on the database host;
  `pg_read_file('postgresql.conf')`, which returned 29,655 bytes of a server-side file; `CREATE
  ROLE ... LOGIN`; and `ALTER SYSTEM SET log_statement = 'all'`. A query of `pg_authid` was
  permitted and returned 0 rows, because this cluster authenticates by `trust` and stores no hash.
  The cluster has 1 login role, a superuser, and 0 login roles that are not superusers. **(one
  run)**
- **A split role is cheap in migrations and expensive in roles.** Across the 17 project migration
  modules there are **0 privileged SQL statements** — no `CREATE EXTENSION`, `CREATE ROLE`, `ALTER
  ROLE`, `GRANT`, `REVOKE`, `OWNER TO`, `ALTER SYSTEM`, `SET ROLE`, `SUPERUSER` or `COPY` — and
  the 24 `CreateModel` operations that produce the pinned 33 tables need an owner and `CREATE` on
  the schema. What a non-superuser is refused is already measured, including creating the test
  database the runner needs. **(pinned)**
- **No credential in CI comes from a secret store.** The workflow holds **0 `secrets.`
  references** and interpolates exactly two expressions, `${{ github.run_id }}` 7 times and `${{
  github.run_attempt }}` 4 times, from which it builds the application key, the database user and
  the database password. The repository is public, has 3 collaborators and all 3 can push, 0
  rulesets and 0 deployment environments; branch protection and secret-scanning enforcement could
  not be read with the available token (HTTP 403 and HTTP 404) and are recorded as unknown.
  **(pinned for the workflow, dated for the API)**
- **Nothing in the tree can answer who holds the key.** 0 of the 12 commands read `pg_authid`, a
  secret value or a CI secret; `daroobank/postgresql_access.py` reads `pg_roles` flags for
  `current_user` and `session_user`, `pg_stat_ssl` and one `has_database_privilege` call and
  reports no password material; `docs/AUTHORIZATION_REVIEW.md` is 207 lines and mentions
  `SECRET_KEY`, the word `secret`, a PostgreSQL role, `collaborator` and `GitHub` **0** times
  each; and across the tracked `.md` documents other than the ten this delivery writes 5 lines
  pair a cadence word with an access word, none of them about who holds the key or who can push,
  while no line in any of the other documents prescribes a custody review. **(pinned)**

## Red checks

After the plan, the record, the neighbour patches and the recounted pins existed, fifty-one
mutations were applied one at a time to the tree, each followed by a run of
`daroobank/test_secrets_access_plan.py` and each required to fail. The tree was held
byte-identical throughout: a `sha256sum` manifest of all tracked files was written before the
first mutation, `sha256sum -c` returned rc=0 after every restore, and the suite was green at both
ends, before the first mutation and after the last restore. Every mutation went red.

One mutation went green on the first sweep, and it was a defect in the suite rather than a bad
mutation: replacing this record's `**No option is chosen, recommended or excluded.**` with a claim
that option D had been chosen passed, because the `Decision` section was pinned for everything it
says was not done and not for the one sentence that refuses to choose.
`test_the_record_names_nothing_it_did_not_do` now requires that sentence too, and the sweep was
re-run from the beginning rather than patched. One mutation was not a mutation at all:
`@sensitive_variables` without parentheses raises `TypeError` at import, so that run died before
any test executed and proved nothing; the decorator is applied as `@sensitive_variables()` and the
pin catches it. Three anchors were retargeted before the clean sweep — two prose fragments that
sit across a line break in a hard-wrapped document, and one whose failure is reported by
`test_no_command_can_answer_who_holds_the_key`, which quotes the readiness message, rather than by
the debug-coupling test that was predicted. The sweep the list below comes from ran 51 mutations
in 47 s, a mean of 0.9 s each, on the machine that measured everything else in this record.

1. `configuration.py`: the shape check stopped requiring five distinct characters —
   `test_the_shape_check_is_not_monotonic_in_entropy`.
2. `configuration.py`: the shape check accepted a short key —
   `test_the_debug_fallback_is_the_key_ci_runs_with`.
3. `configuration.py`: the insecure prefix stopped being refused —
   `test_a_refused_start_echoes_no_value_and_names_no_other_variable`.
4. `configuration.py`: a refusal started echoing the value it refused —
   `test_a_refused_start_echoes_no_value_and_names_no_other_variable`.
5. `configuration.py`: an entropy floor was implemented — `test_nothing_this_plan_prices_exists`.
6. `settings.py`: the committed debug fallback was replaced —
   `test_the_debug_fallback_is_the_key_ci_runs_with`.
7. `settings.py`: the staff portal stopped following the one boolean —
   `test_seven_settings_lines_branch_on_debug_and_the_portal_follows_it`.
8. `settings.py`: settings read an environment name the inventory does not pin —
   `test_the_environment_names_the_application_reads_are_the_ones_another_suite_pins`.
9. `.env.example`: the documented placeholder key was reworded —
   `test_nine_key_literals_exist_and_exactly_one_is_accepted`.
10. `test_projection_repair.py`: a synthetic test key moved out of one module —
    `test_nine_key_literals_exist_and_exactly_one_is_accepted`.
11. `throttle.py`: the login throttle changed its salt —
    `test_the_committed_debug_key_makes_signatures_reproducible`.
12. `services.py`: the search cursor changed its salt —
    `test_the_committed_debug_key_makes_signatures_reproducible`.
13. `staff_views.py`: a view started masking its frame locals —
    `test_request_data_and_frame_locals_are_printed_in_clear_without_the_decorators`.
14. `compose.yaml`: the container stopped defaulting to the branch that skips the check —
    `test_compose_demands_a_secret_and_defaults_to_the_branch_that_skips_the_check`.
15. `compose.yaml`: the container grew a default key —
    `test_compose_demands_a_secret_and_defaults_to_the_branch_that_skips_the_check`.
16. `checks.yml`: continuous integration started reading a secret store —
    `test_ci_builds_every_credential_from_two_public_numbers`.
17. `checks.yml`: a CI credential stopped being built from the two public numbers —
    `test_ci_builds_every_credential_from_two_public_numbers`.
18. `checks.yml`: both CI jobs started supplying a key —
    `test_the_debug_fallback_is_the_key_ci_runs_with`.
19. `inspect_postgresql_access.py`: the privilege inspection command stopped refusing a non-debug
    configuration —
    `test_the_only_privilege_inspection_command_refuses_a_non_debug_configuration`.
20. `postgresql_access.py`: the access module started reading password material —
    `test_the_only_privilege_inspection_command_refuses_a_non_debug_configuration`.
21. `list_staff_sessions.py`: a session command stopped refusing to run outside debug —
    `test_six_commands_refuse_to_run_outside_debug_and_one_reports_it_as_a_failure`.
22. `check_deployment_readiness.py`: the readiness report stopped saying what it does not measure
    — `test_no_command_can_answer_who_holds_the_key`.
23. `list_staff_sessions.py`: a command started reading the secret store —
    `test_no_command_can_answer_who_holds_the_key`.
24. `0001_initial.py`: a migration started needing a superuser —
    `test_no_migration_statement_requires_a_superuser`.
25. `browser_test_diagnostics.py`: a tool started generating key material —
    `test_nothing_in_the_tree_can_produce_a_key_and_nothing_names_a_mechanism`.
26. `test_projection_repair.py`: a second database role appeared in a fixture —
    `test_nothing_this_plan_prices_exists`.
27. `requirements.txt`: a secret manager dependency appeared —
    `test_nothing_this_plan_prices_exists`.
28. `AUTHORIZATION_REVIEW.md`: the authorization review started covering repository access —
    `test_the_authorization_review_does_not_cover_secrets_or_repository_access`.
29. `DATA_SOURCES.md`: a document started prescribing a custody review cadence —
    `test_no_document_names_a_cadence_for_reviewing_who_holds_the_key`.
30. `DEPLOYMENT.md`: an instruction to obtain a key was reworded —
    `test_nothing_in_the_tree_can_produce_a_key_and_nothing_names_a_mechanism`.
31. the plan: a measured entropy was restated in the plan —
    `test_the_plan_states_the_numbers_it_measured`.
32. the plan: a subsection was deleted from the plan — `test_the_plan_states_its_own_shape`.
33. the plan: an option was deleted from the priced table — `test_the_plan_states_its_own_shape`.
34. the plan: the plan chose an option instead of pricing it —
    `test_no_option_is_presented_as_chosen`.
35. the plan: a quoted requirement was reworded in the plan —
    `test_the_plan_quotes_the_requirements_it_is_priced_against`.
36. the plan: the plan stopped calling itself a proposal —
    `test_the_plan_is_an_unowned_proposal_that_implements_nothing`.
37. the plan: a dependency was named without the path that finds it —
    `test_every_module_document_and_record_the_plan_names_exists`.
38. the plan: a record the plan depends on was unlinked —
    `test_the_plan_links_the_records_it_depends_on`.
39. the record: the record restated a suite it does not have —
    `test_the_record_has_the_sections_a_decision_record_needs`.
40. the record: a pin delta was restated in the record —
    `test_the_pins_that_count_the_tree_moved_with_this_plan`.
41. the record: the record started calling a dated observation current —
    `test_the_record_marks_what_is_pinned_and_what_is_one_run`.
42. the record: a measured bullet lost the mark that says it is pinned —
    `test_the_record_marks_what_is_pinned_and_what_is_one_run`.
43. the record: the record claimed an option was chosen —
    `test_the_record_names_nothing_it_did_not_do`.
44. the record: a limitation was restated as a measurement —
    `test_the_record_limits_what_it_claims`.
45. the record: a measured number in the record was restated —
    `test_the_record_states_the_numbers_it_measured`.
46. the record: the record stated a red-check count it does not carry —
    `test_the_record_carries_the_red_checks_it_names`.
47. `SECURITY.md`: a neighbouring document stopped naming the plan —
    `test_the_neighbouring_documents_name_the_plan_and_what_it_measured`.
48. `README.md`: the record index stopped listing the record —
    `test_the_decision_index_summarizes_this_record`.
49. `PHASE1_RELEASE_EVIDENCE.md`: the evidence row stopped carrying a measured number —
    `test_the_release_evidence_row_answers_the_gate_and_stays_open`.
50. `CHANGELOG.md`: the changelog entry stopped naming the plan —
    `test_the_changelog_entry_is_newest_first_and_names_the_plan`.
51. `test_document_links.py`: a shared pin was moved without the tree moving —
    `test_the_counts_the_pins_state_are_the_counts_the_tree_has`.

## Consequences

- Entropy stopped being an adjective. The plan states a number for every key this tree can run
  with, and the number that matters is not the smallest one: the shape check accepts 28.1 bits and
  rejects 156.1, so a reader can now see that the guard is a shape guard, and can see what a floor
  would cost — nothing in the tree changes verdict at 100, 150 or 200 bits.
- The debug branch is now described from measurements instead of from intent. One boolean decides
  the shape check, the staff portal, HSTS, SSL redirect, proxy-header trust, six commands'
  willingness to run and whether an error page publishes 154 settings; the same boolean is `1` in
  both CI jobs and is the default of the only container path in the repository.
- A concrete forgery boundary is recorded rather than implied: with the committed constant, a
  cursor signed offline is accepted and a throttle key is predictable. That is a property of the
  debug branch, and the plan says so, but it is now measured instead of assumed harmless.
- Masking on an error page is pinned as the name-based rule it is, together with the two
  decorators that would change it and the fact that nothing in the tree uses them. A future view
  that holds key material in a local variable fails a pin if it also adds a decorator expectation,
  and the plan names the gap in the meantime.
- Least privilege gained three permitted operations that
  [ADR 0236](0236-database-connection-plan.md) did not list — program execution on the database
  host, server-side file reads and role creation — and a price for splitting the account that
  starts from 0 privileged statements in 17 migration modules rather than from an opinion.
- Access review is now a dated observation with a named blind spot: 3 push-capable actors on a
  public repository, no rulesets, two endpoints this token could not read, and 0 commands or
  documents that could answer the question from an inventory. The next lane that touches
  governance can compare against these numbers instead of starting from silence.
- Custody is recorded as an instruction with no mechanism: 6 lines ask for an approved secret
  manager, 0 name one, and 0 tracked files can produce a key. That is the whole finding, and it is
  now pinned so that adding a generation path fails a test until the documents are updated with
  it.
- Seven neighbours carry one sentence each, the changelog carries the entry and the record index
  carries this record, so the measurement is reachable from the documents that ask for it.
- The counting pins this delivery moves are restated here and recounted in the suites that own
  them, so a later lane inherits the numbers as they are rather than as they were:
  `DOCUMENT_COUNT` 273 to 275, `ADR_COUNT` 237 to 238, `LINK_COUNT` 1,254 to 1,293 and
  `SUITE_LINE_COUNT` 27 to 28 in `daroobank/test_document_links.py`, whose `EXTERNAL_COUNT` 31 and
  `ANCHOR_COUNT` 29 did not move; `DOCS_MARKDOWN_COUNT` 272 to 274 in the migration and backup
  suites; `TEST_MODULE_COUNT` 244 to 245 in `daroobank/test_database_migration_plan.py` and
  `TEST_MODULE_COUNT` 243 to 244 in the MFA and secret-rotation suites, which hold it one behind;
  `CORPUS_COUNT` 261 to 263 and `TREE_FILE_COUNT` 747 to 750 in
  `daroobank/test_database_connection_plan.py`; and `CORPUS_COUNT` 264 to 266 in
  `daroobank/test_monitoring_response_plan.py`. `LOGIN_ROUTE_TESTS` 46 to 47 in
  `daroobank/test_mfa_implementation_plan.py`, which counts the test modules downstream of the
  staff login route and gains this suite because this suite pins `/staff/login/`; and the two
  document corpora that exclude only the documents their own delivery edits gained both documents
  here, so `DOC_TOKEN_COUNTS` moves `alert` 17 to 19 in
  `daroobank/test_monitoring_response_plan.py` and `replica` 11 to 13, `superuser` 19 to 21 and
  `least privilege` 2 to 4 in `daroobank/test_database_connection_plan.py`, the plan quoting
  *"monitoring/alerts"* from `docs/DEPLOYMENT.md` and both documents naming the superuser role and
  the least-privilege requirement they measure. Those four counts are counts of documents, so
  naming the tokens in this record is itself the last increment: `alert` and `replica` each appear
  in one document more because this sentence appears in one, and the numbers above are the fixed
  point rather than a step towards one. Two documents and one suite joined the populations those
  pins count, which is the whole of the movement.

## Limitations

- **The privileged operations were attempted against one synthetic cluster.** It has a single
  superuser login role, `trust` authentication for local and loopback connections, no stored
  password hash and no application tables at all — the real database in this sandbox has 0 tables.
  The results say what that role was permitted to do there; they are not a survey of a production
  cluster, and a deployment with a least-privilege account would answer differently.
- **The GitHub API facts are dated and unpinned.** They were read on 2026-11-28 with the token
  available in this sandbox. Two endpoints refused it (branch protection with HTTP 403, secret
  scanning with HTTP 404) and are recorded as unknown rather than absent; collaborators, rulesets
  and environments can change without any commit in this repository, and the suite does not
  attempt to re-read them.
- **The live-server numbers are one run on one machine.** 29 routes, 27,192 and 31,230 bytes, an
  834-byte environment, a 1,817-byte log and a 145-byte error page are measurements of a
  `runserver` process in this sandbox under `--noreload`. They are not budgets, not latencies and
  not a claim about a deployed process manager, a WSGI server or a container.
- **Shannon entropy is a property of a string, not of a generator.** A 249.3-bit fixture is not a
  249.3-bit secret, and a committed 130.5-bit constant has 0 bits of secrecy whatever its text
  entropy says. The plan states both numbers for exactly that reason; neither is a measure of how
  a value was produced.
- **No secret manager, KMS, HSM, second cluster, non-superuser application account or production
  deployment was available**, so options B, F, G and H are priced from counts and refusals rather
  than prototyped, and the prices are inventories of what moves rather than measured totals.
  `docker` is not installed in this environment, so the `compose.yaml` facts were read from that
  file and never run.
- **Key recovery was not re-measured.** [ADR 0231](0231-secret-rotation-plan.md) measured a
  rotation and [ADR 0232](0232-backup-recovery-plan.md) measured the database side; a lost key
  with no copy has no escrow, no second copy and no re-issue path in this tree, and nothing here
  exercises one.
- **The suite cannot tell whether the eight decisions will ever be answered**, whether the answers
  will be adequate, or whether a key produced under them would survive review. It pins
  measurements, quotations and absences; forcing the questions is all this record does.
