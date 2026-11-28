# 0237 — the monitoring and response plan, and what this repository would notice

Date: 2026-11-28
Status: accepted
Suite: `daroobank/test_monitoring_response_plan.py` (33 tests, ~1.8 s, 2 of them against a live
database and 31 database-free)

## Context

Four documents ask this repository for a monitoring and response capability and none of them has
one. [SECURITY.md](../SECURITY.md) requires *"Define incident severity, containment, notification
and recovery owners before launch."*, asks that audit be protected *"from modification by
application roles"* and that the system *"monitor unauthorized access"*, forbids PHI *"in metrics,
search URLs, errors or analytics"* and asks for logging and redaction to be configured before
production. [The operations runbook](../OPERATIONS_RUNBOOK.md) concedes the area in its first
paragraph — *"No production services, dashboards, alerts or on-call rotation currently exist."*,
*"Create concrete commands, owners and escalation contacts before production."* — and then
instructs a responder to *"Escalate to data steward/source owner."*, to *"notify clinical lead and
affected users where legally appropriate"*, that *"For serious harm risk escalate through the
clinical incident protocol."* and to *"Define the on-call chain before enabling patient
accounts."* [DEPLOYMENT.md](../DEPLOYMENT.md) assigns the remainder outward: *"Network/proxy
restrictions, polling limits, host and HTTPS configuration, response deadlines, monitoring and
incident ownership remain external responsibilities."*
[The release evidence](../PHASE1_RELEASE_EVIDENCE.md) carries *"**Open:** private access
restrictions, network/request deadlines, monitoring, alert routing, on-call ownership and incident
response."*

Three records had already measured pieces of this and each one stopped at a boundary it named.
[ADR 0217](0217-deployment-readiness-report.md) built the only instrument and limited it: *"It is
not monitoring, alerting, MFA, TLS issuance, backup verification, network isolation, a penetration
test or an independent security assessment"*, *"nothing here aggregates or stores them; there is
no history, no alerting and no dashboard."* [ADR 0221](0221-no-read-audit.md) pinned the absence
of a read record from four directions and then wrote the sentence that defines this lane: *"A
reverse-proxy access log, PostgreSQL's `log_statement`, a host audit daemon or an APM agent would
all be invisible to it."* — an absence **inside the process**, with the outside explicitly left
open. [ADR 0227](0227-read-audit-plan.md) priced the in-application option,
[ADR 0228](0228-public-read-limit.md) refused to let a rate limiter become an access log because
*"A limiter that stored what was read, by whom, or when, would be an access log wearing a rate
limit's clothes."*, and [ADR 0223](0223-no-abuse-protection.md) recorded that monitoring was asked
for in the release gates while *"polling limits"* were mentioned once in passing.

So the inside of the process was measured, the read-audit option was priced, and nobody had
measured the outside: what the deployment does with a signal, who would be told, and which
artifact would prove afterwards that any of it happened. That is what
[`docs/MONITORING_RESPONSE_PLAN.md`](../MONITORING_RESPONSE_PLAN.md) measures, in thirty-one
quotes from the documents it is priced against and in the runs below.

## Decision

Write the absence down as a proposal with no owner, measure the deployment side ADR 0221 left
open, pin both with a suite, and route the one option that is a schema change to the lane that
owns schema.

Nothing is implemented. **Nothing is implemented.** No `LOGGING` dictionary, no handler, no
formatter, no logger name, no metric, no alert rule, no threshold, no severity level, no
escalation contact, no rota, no collector, no agent, no scheduler entry, no healthcheck, no log
driver, no rotation limit, no environment variable, no command, no table, no migration and no
dependency was added to this tree. The measurements were taken with the commands, the
`Dockerfile`, the `compose.yaml` and the workflow the tree already has, against a development
process on a loopback port, a synthetic PostgreSQL 16.2 server and a throwaway superuser account
that was deleted afterwards.

No option was chosen. The plan prices eight — leave the surface as measured, write the absence
into the documents, pin it in a suite, arrange the signal at the edge or the host, record the read
inside the application, give the deployment something to poll, configure logging, and choose a
collector with a severity scale and a rota — and lists eight decisions that have to be made before
any of them is defensible. The read-audit option is written as a **request to the database lane**
that carries [ADR 0236](0236-database-connection-plan.md), with ADR 0227's measured cascade quoted
rather than re-run, and this record writes no migration and proposes no model.

## Measured behavior

Every number is one measured run on one machine against synthetic data, quoted so a later run can
be compared with it. None is a budget, a threshold or a detection objective.

| Measurement | Result |
|---|---|
| `settings.LOGGING` | `{}`, with `LOGGING_CONFIG` left at `'logging.config.dictConfig'`, so the handlers that exist are Django's defaults and not a choice this project made |
| Who could be told | `ADMINS` and `MANAGERS` are both `[]`, so `AdminEmailHandler` — installed on the `django` logger and the only handler in the tree whose job is to reach a human — has no recipient and never sends |
| Loggers | root: no handler, level 30. `django`: `StreamHandler` + `AdminEmailHandler`, level 20, propagating. `django.request`: no handler of its own, level 0, propagating. `django.server`: `StreamHandler` |
| Emitters in project code | across the 120 non-test project modules, 0 `import logging` and 0 emitter call sites (`logger.`, `logging.`, `.warning(`, `.error(`, `.exception(`, `.critical(`, `.info(`, `.debug(`); the same AST scan finds `json` imports, so it is not a scan that finds nothing |
| Middleware | 13 entries, 8 of them this project's, and 0 whose name suggests recording; `daroobank/middleware.py` neither imports `logging` nor calls `getLogger` |
| The deployed command | `Dockerfile` line 10 is `CMD ["sh", "-c", "python -m tools.wait_for_database && python manage.py migrate --noinput && exec python manage.py runserver 0.0.0.0:8000"]` — the production command is the development server, with no `gunicorn` and no `uwsgi` anywhere in it |
| The only signal that leaves the process | six requests to that server produced 388 bytes on stderr in 8 lines: six request lines of the form `[28/Nov/2026 16:38:19] "GET /health/live/ HTTP/1.1" 404 0` and two `Not Found:` lines. A request line carries a second-resolution timestamp, a method, a path, a status and a byte count, and no account, session, route name, duration, request identifier or client address |
| Where that signal goes | `compose.yaml` is 44 lines with two services and one volume, `postgres_data`; it configures 0 `logging:` drivers, 0 `max-size` and 0 `max-file` keys and mounts nothing to hold a log |
| What polls the application | `compose.yaml` has exactly one `healthcheck:`, on `db` at line 15, and none on `web`. `.github/workflows/checks.yml` is 217 lines across two jobs, mentions `runserver` 0 times and `alert` and `monitor` 0 times, and its only liveness test is `curl -fsS http://127.0.0.1:8000/` twice — the home page, not either probe, once per push and once per pull request |
| The probes, disabled | with `HEALTH_PROBES_ENABLED` off, which is the default and what `compose.yaml` sets (`${DAROOBANK_HEALTH_PROBES_ENABLED:-0}`), both `/health/live/` and `/health/ready/` answer 404 with an empty body |
| The probes, enabled | both answer 200 with the identical three-byte body `ok\n`; `POST`, `PUT` and `DELETE` answer 405 with `Allow: GET, HEAD`; `HEAD` answers 200 with no body; a successful answer carries eight headers including `Cache-Control: no-store` and `X-Robots-Tag: noindex, nofollow`. Because the two bodies are byte-identical, a poller that reads the body learns nothing |
| What polling would cost | median latency over 25 requests each: 0.146 ms for `/health/live/` (minimum 0.122, maximum 1.361) and 0.417 ms for `/health/ready/` (minimum 0.369, maximum 0.926); a ten-second interval would spend about 0.15% of one second per hour, so cost is not why nothing polls |
| The probe trap, measured both ways | `database_ready()` answers False when `connection.in_atomic_block`, which ADR 0217 warns about: the same request answered **200 outside a transaction and 503 inside one**, so an instrument that wraps the probe measures its own wrapper and reports a healthy database as down |
| The one instrument | `manage.py check_deployment_readiness` exits 1 and prints one 2,131-byte JSON document on stdout with nothing on stderr, in a median of 306.4 ms over three runs (329.6, 306.4 and 302.0 ms) |
| What the instrument reads | 16 distinct settings — 6 as `settings.<NAME>` and 10 as names it looks up, 6 of those 10 through a tuple or dictionary it iterates — and 0 occurrences of `os.environ` in its 189 lines; `DATABASES` is not among the 16, because it reaches the database through the connection it is given |
| What the instrument reports | five keys, `ready` false, ten required checks of which four pass (`allowed_hosts_explicit`, `session_flags`, `migration_history_consistent`, `database_reachable`) and six fail, and a `review` list whose six identifiers are all conditional — this run reported three, so the count is taken from the source and not from one run's output. Which checks pass depends on the process that asks: the command-line run above had `DAROOBANK_DEBUG=1` against a database with migrations pending and passed four of the ten, while the same report inside a test process passes six, because `DEBUG` is off there and the runner has applied every migration — which is ADR 0217's point that a deployment needs one report per process |
| The environment behind it | `settings.py` performs 15 `os.environ` reads naming 13 distinct variables (`DAROOBANK_ALLOWED_HOSTS` and `POSTGRES_SSLMODE` are each read twice) and reaches 3 more through `required_database_setting`, which is the sixteen the evidence cell counts; 0 of the sixteen names a handler, level, sink, recipient, metric, threshold or retention period |
| Two sweeps of all 55 routes | anonymous: `{200: 9, 302: 41, 404: 4, 405: 1}` in 40.0 ms, 0.73 ms per request. Authenticated as a fully permitted superuser: `{200: 27, 404: 22, 405: 6}` in 201.1 ms, 3.66 ms per request. Both reached 55 of 55 routes |
| What the sweeps left behind | 33 tables with **0 rows moved** in either sweep, **0 files** created or modified anywhere in the tree, and 5 log records for the anonymous sweep against 28 for the authenticated one — every record a `django.request` WARNING, and every one of them from a failure |
| The measurement that matters | the 28 records are exactly the 22 routes that answered 404 plus the 6 that answered 405, so **the 27 reads that succeeded as a permitted superuser produced no record at all**: no row, no log record, no file. A successful read of clinical or price material by an identified staff account is indistinguishable from a read that never happened |
| What the sweep itself wrote | `auth_permission` 63, `auth_user` 1, `django_content_type` 29, `django_migrations` 32, `django_session` 1 — 5 of the 33 tables non-empty, all of them the experiment's own account and session, deleted afterwards |
| Schema that could hold a record | of the 24 project models, 0 have a name containing `audit`, `access`, `request`, `event`, `metric`, `session`, `record`, `track` or `visit`; the two whose names touch this area are counters, `StaffLoginWindow` and `PublicReadWindow`, each holding a keyed digest, a window start and a count |
| Absence as artifacts | of the files a tree scan counts, **0 have a name** containing `alert`, `oncall`, `on-call`, `incident`, `postmortem`, `monitor`, `observab`, `telemetry`, `paging` or `escalat`, and none of the 13 directories that would hold an operational artifact exists: `ops`, `operations`, `runbooks`, `oncall`, `incidents`, `alerts`, `monitoring`, `dashboards`, `terraform`, `ansible`, `k8s`, `helm`, `deploy` |
| Absence as dependencies | `compose.yaml`, `.github/workflows/checks.yml`, `requirements.in` and `requirements.txt` contain 0 occurrences of `alert`, `monitor`, `sentry`, `datadog`, `prometheus`, `grafana`, `opentelemetry`, `logzio`, `papertrail`, `slack` and `pagerduty` |
| Absence as documents, and why words prove nothing | over the 264-document corpus this delivery neither writes nor edits, `alert` appears in 17 documents, `incident` in 26, `dashboard` in 7, `alerting` in 4, `on-call` in 2, `severity` in 1 and `telemetry` in 1 — because those documents are the ones reporting the absence. What appears in 0 documents: `severity level`, `priority level`, `duty roster`, `alarm`, `oncall`, `escalation policy`, `postmortem`, `post-incident`, `observability`, `pager`, `page duty`, `detection window`, `MTTD`, `MTTR`, `mean time`, `within 24 hours`, `within 72 hours`, and every collector and vendor name checked |
| The response side | the runbook names `clinical lead`, `clinical owner`, `on-call chain`, `clinical incident protocol` and `escalation contact`, and **0 documents outside it** in the 264-document corpus name any of the five; `data steward` appears in 1 more. Nothing defines any of them, and no severity scale, acknowledgement time or detection window exists in any document |
| Who to contact | the only two email-shaped strings in the 264-document corpus are `checkout@v7.0.1`, an action reference, and `user@evil.example`, a test fixture. No document contains a person, an address or a number to escalate to |

## Red checks

After the plan, the record and the neighbour patches existed, thirty-nine mutations were applied
one at a time to the tree, each followed by a run of `daroobank/test_monitoring_response_plan.py`
and each required to fail. The tree was held byte-identical throughout: a `sha256sum` manifest of
all 750 tracked files was written before the first mutation, `sha256sum -c` returned rc=0 after
every restore, and the suite was green at both ends, before the first mutation and after the last
restore. Every mutation went red.

Three mutations went green on the first sweep, and each was a defect in the suite rather than a
bad mutation, so the suite was strengthened and the sweep re-run. Rewording one of the three
places the plan states the corpus size passed, because only the sentence about email-shaped
strings was pinned, and `MEASURED` now holds all three. Unlinking `docs/READ_AUDIT_PLAN.md` in the
plan passed, because a dependency named in prose survives its own link being deleted, and the
suite now pins the plan's eleven links and the nine dependencies that are links. Naming
`Prometheus` in `docs/DEPLOYMENT.md` and writing `oncall@hospital.example` into
`docs/OPERATIONS_RUNBOOK.md` both passed, because those two are among the nine documents this
delivery edits and so are outside the corpus the absence scan counts over; both were retargeted at
documents inside it, and the blind spot they exposed is recorded under Limitations.

1. `health.py`: the readiness probe stopped bounding its own statement —
   `test_the_probes_are_the_two_routes_health_py_defines`.
2. `health.py`: the probe body stopped being the three bytes both probes answer —
   `test_the_probes_answer_three_bytes_and_503_inside_a_transaction`.
3. `health.py`: the probe stopped noticing it was inside a transaction —
   `test_the_probes_are_the_two_routes_health_py_defines`.
4. `settings.py`: an administrator appeared, so AdminEmailHandler has a recipient —
   `test_the_logging_configuration_is_empty_and_nobody_is_addressed`.
5. `settings.py`: a logging configuration appeared —
   `test_the_logging_configuration_is_empty_and_nobody_is_addressed`.
6. `settings.py`: a middleware was removed from the request path —
   `test_no_middleware_records_a_request`, which also failed
   `test_the_probes_answer_three_bytes_and_503_inside_a_transaction`.
7. `middleware.py`: the middleware module took a logger — `test_no_middleware_records_a_request`,
   which also failed `test_no_project_module_imports_logging_or_calls_an_emitter`.
8. `session_guard.py`: a project module imported logging —
   `test_no_project_module_imports_logging_or_calls_an_emitter`.
9. `session_guard.py`: a project module gained an emitter call site —
   `test_no_project_module_imports_logging_or_calls_an_emitter`.
10. `check_deployment_readiness.py`: a review identifier was reworded —
    `test_the_readiness_command_reads_settings_and_never_the_environment`, which also failed
    `test_the_report_answers_not_ready_with_a_conditional_review_list`.
11. `check_deployment_readiness.py`: a required check was renamed out of the source —
    `test_the_readiness_command_reads_settings_and_never_the_environment`, which also failed
    `test_the_report_answers_not_ready_with_a_conditional_review_list`.
12. `check_deployment_readiness.py`: the report started reading the environment directly —
    `test_the_readiness_command_reads_settings_and_never_the_environment`, which also failed
    `test_the_report_answers_not_ready_with_a_conditional_review_list`.
13. `check_deployment_readiness.py`: a required check started answering passed while it fails —
    `test_the_report_answers_not_ready_with_a_conditional_review_list`, which also failed
    `test_the_readiness_command_reads_settings_and_never_the_environment`.
14. `compose.yaml`: compose gave the application a log driver —
    `test_compose_gives_the_database_a_healthcheck_and_the_application_none`.
15. `compose.yaml`: compose gave the application a healthcheck —
    `test_compose_gives_the_database_a_healthcheck_and_the_application_none`.
16. `Dockerfile`: the container command became a production server —
    `test_the_deployed_command_is_the_development_server`.
17. `checks.yml`: continuous integration started polling a probe —
    `test_ci_polls_the_home_page_and_neither_probe`.
18. `urls.py`: a health route was renamed — `test_the_route_inventory_the_sweeps_walk`.
19. `settings.py`: the public read limiter was switched on by default —
    `test_two_sweeps_of_all_55_routes_move_nothing_and_record_only_failures`.
20. `staff_views.py`: a staff route stopped being gated —
    `test_two_sweeps_of_all_55_routes_move_nothing_and_record_only_failures`.
21. the plan: an option was deleted from the priced table —
    `test_the_plan_prices_eight_decisions_and_eight_options`.
22. the plan: a subsection was deleted from the plan —
    `test_the_plan_has_the_sections_the_plan_family_uses`, which also failed
    `test_the_plan_prices_eight_decisions_and_eight_options`.
23. the plan: a measured absence was restated as a presence —
    `test_the_plan_states_the_measured_numbers`.
24. the plan: a corpus count in the plan was changed —
    `test_the_plan_states_the_measured_numbers`.
25. the plan: a dependency was unlinked in the plan —
    `test_the_plan_names_the_documents_records_and_suites_it_depends_on`, which also failed
    `test_the_record_states_the_pin_deltas_it_causes`.
26. the plan: a prose line was written wider than the house wrap —
    `test_the_plan_wraps_to_the_house_width`.
27. the plan: the plan chose an option instead of pricing it —
    `test_the_plan_is_an_unowned_proposal_that_implements_nothing`.
28. `DEVELOPMENT_GUIDE.md`: a collector was named in a corpus document —
    `test_the_absence_is_counted_over_documents_that_report_it`.
29. `READ_AUDIT_PLAN.md`: a contact was written into a corpus document —
    `test_the_roles_the_runbook_escalates_to_are_defined_nowhere`, which also failed
    `test_the_absence_is_counted_over_documents_that_report_it`.
30. `OPERATIONS_RUNBOOK.md`: a role the runbook escalates to was renamed —
    `test_the_roles_the_runbook_escalates_to_are_defined_nowhere`, which also failed
    `test_the_plan_quotes_the_requirements_it_is_priced_against`.
31. `OPERATIONS_RUNBOOK.md`: a quoted requirement was reworded in its source —
    `test_the_plan_quotes_the_requirements_it_is_priced_against`, which also failed
    `test_the_roles_the_runbook_escalates_to_are_defined_nowhere`.
32. `SECURITY.md`: a neighbouring document stopped naming the plan —
    `test_each_neighbour_document_names_the_plan`, which also failed
    `test_the_plan_is_linked_from_a_document_it_does_not_own` and
    `test_the_plan_quotes_the_requirements_it_is_priced_against`.
33. `PHASE1_RELEASE_EVIDENCE.md`: an evidence cell stopped naming the record —
    `test_both_evidence_cells_of_the_monitoring_row_name_the_plan`.
34. `README.md`: the index stopped listing the record —
    `test_the_record_index_names_the_record_in_number_order`, which also failed
    `test_the_record_states_the_pin_deltas_it_causes`.
35. the record: a required section was deleted from the record —
    `test_the_record_has_the_sections_a_decision_record_needs`.
36. `CHANGELOG.md`: the changelog entry stopped being newest first —
    `test_the_changelog_entry_is_newest_first_and_names_the_plan`.
37. `test_document_links.py`: a shared pin stopped being the count of the thing it counts —
    `test_the_record_states_the_pin_deltas_it_causes`.
38. the record: the record stopped stating a pin this delivery moves —
    `test_the_record_states_the_pin_deltas_it_causes`.
39. the record: the record stated a red-check count that is not the list it carries —
    `test_the_record_carries_the_red_checks_it_names`.

## Consequences

- The absence is now counted rather than described, and it is counted as artifacts: 0 file names,
  0 of 13 directories, 0 dependency or configuration mentions, 0 contacts in the 264-document
  corpus, the runbook the only document naming the clinical incident protocol, and 0 moved tables
  and 0 records for 27 successful authenticated reads. A future change that adds a sink, a
  healthcheck, a log driver, a collector or a record-shaped model fails a named pin instead of
  passing unnoticed.
- The deployment side ADR 0221 explicitly left open is now measured: the deployed command is the
  development server, its stderr is the only signal that leaves the process, nothing polls either
  probe, the `web` container has no healthcheck, and `compose.yaml` configures no log driver, no
  rotation and no volume to hold one. ADR 0221's limits stand — its pins still cannot see a proxy
  log, `log_statement`, a host audit daemon or an agent — and this record adds that none of them
  is arranged here either.
- The probe trap is documented where an operator will meet it. A 503 from `/health/ready/` has two
  causes, a database that does not answer inside one second and a caller that wrapped the probe in
  a transaction, and they were measured from the same code path as 200 and 503.
- The read-audit option is routed rather than decided. It is a schema change, so it belongs to the
  database lane that carries ADR 0236, and its price is quoted from ADR 0227 — 20 failures across
  7 of 9 sampled suites over 138 tests, a lower bound — rather than re-measured. No migration,
  model or setting was written here.
- No option was chosen and no decision was made. The plan is unowned, its eight decisions are
  open, and its eight options are priced against each other rather than ranked.
- `docs/PHASE1_RELEASE_EVIDENCE.md` gained a sentence in **both** cells of its `Monitoring and
  response` row, `docs/DEPLOYMENT.md`, `docs/OPERATIONS_RUNBOOK.md`, `docs/SECURITY.md` and
  `docs/TESTING_STRATEGY.md` each gained one sentence naming what was measured,
  `docs/CHANGELOG.md` gained an entry above the previous one and
  `docs/ARCHITECTURE_DECISIONS/README.md` gained its index bullet in number order, so the delivery
  is not orphaned. No README in this tree links a plan — the root one is a list of documents and
  the index lists records — so the plan is reached through the five neighbours and the changelog
  entry that name it, which is what `test_document_links.py` holds the tree to.

- The shared pins were recounted on the tree this branch merges into rather than copied, and every
  one of them was recomputed from the tree in the same change: `DOCUMENT_COUNT` 273, `ADR_COUNT`
  237, `LINK_COUNT` 1,254 and `SUITE_LINE_COUNT` 27 in `daroobank/test_document_links.py`, whose
  `EXTERNAL_COUNT` 31 and `ANCHOR_COUNT` 29 did not move; `TEST_MODULE_COUNT` 244 in
  `daroobank/test_database_migration_plan.py` and 243 in the MFA and secret-rotation suites;
  `DOCS_MARKDOWN_COUNT` 272 in the migration and backup suites; and in
  `daroobank/test_database_connection_plan.py` `CORPUS_COUNT` 261, `TREE_FILE_COUNT` 747, four
  document-token counts (`replica` 11, `superuser` 19, `pooling` 3 and `statement_timeout` in 6
  documents) and two entries of its test-file timeout vocabulary (`SET LOCAL` 62 and
  `statement_timeout` 77), because this delivery's plan and record joined that corpus and its
  suite asserts `SET LOCAL statement_timeout` in `daroobank/health.py`. `LOGIN_ROUTE_TESTS` stays
  46, since this suite never names `staff_login`.

## Limitations

- **No build, image size, container startup or deployment timing was measured, because `docker` is
  not installed in this environment.** Every `Dockerfile` and `compose.yaml` fact in the plan and
  in this record was read from those files, not run. What a container actually does with its
  stdout, how large the image is and how long it takes to start are unmeasured here.
- Nothing was exercised end to end. No collector was installed, no alert rule was written, no
  notification was delivered to a person, no severity scale was ratified and no rota was staffed,
  so this record measures the absence of a capability and not the quality of one.
- The sweeps are shape pins. Both status distributions are asserted, so a route that starts
  answering 200 where it answered 404 fails this suite for a reason that has nothing to do with
  monitoring. The authenticated sweep uses a missing primary key precisely to stay stable, and it
  still walks staff routes that a permission change would move.
- The record counts are compared, not their contents, and the file snapshot is compared by size
  and modification time. A read that deleted one row and inserted another would net out, and a
  write to a cache, a socket or an external service would be invisible to both.
- Only HTTP routes are swept. A read performed by a management command, a shell or direct SQL is
  outside it, and so is anything a worker process would do, because this tree has no worker
  process.
- Durations and byte counts are one run on one machine. The 306.4 ms readiness median, the 0.146
  ms and 0.417 ms probe medians, the 40.0 ms and 201.1 ms sweep totals and the 388 bytes of stderr
  are measurements to compare a later run against, not budgets, and they would differ on other
  hardware.
- The logger shape is Django's default under this settings module. A different `LOGGING_CONFIG`, a
  different Django version or a test runner that installs its own handler would change it, and the
  suite pins the shape this tree has rather than a shape Django promises.
- The absence scan cannot police the nine documents this delivery writes or edits, because they
  are outside the corpus it counts over: a plan that lists `sentry` and `datadog` in order to say
  that neither is present would otherwise fail its own scan. Two mutations aimed at
  `docs/DEPLOYMENT.md` and `docs/OPERATIONS_RUNBOOK.md` were invisible for exactly that reason and
  were retargeted at documents inside the corpus, so a vendor or a contact written into one of
  those nine after this delivery is caught by no suite here.
- This record does not decide whether monitoring is required, what a severity scale should oblige,
  or which vendor would be acceptable inside the sanctions, data-residency and connectivity
  constraints `docs/DEPLOYMENT.md` names. Those are the decisions the plan lists and leaves open.
