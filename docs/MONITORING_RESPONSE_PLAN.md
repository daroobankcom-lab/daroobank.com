# The monitoring and response plan, and what this repository would notice

`docs/SECURITY.md` requires four things this tree does not have: *"Define incident severity,
containment, notification and recovery owners before launch."*, *"Protect audit from modification
by application roles and monitor unauthorized access."*, *"Do not put PHI in metrics, search URLs,
errors or analytics."* and, because *"Search terms can appear in server/access logs; do not enter
PHI and configure logging/redaction before production."*, redaction before any sink exists.
`docs/OPERATIONS_RUNBOOK.md` opens by conceding the whole area: *"No production services,
dashboards, alerts or on-call rotation currently exist."* and *"Create concrete commands, owners
and escalation contacts before production."* It then tells a responder to *"Escalate to data
steward/source owner."*, to *"notify clinical lead and affected users where legally appropriate"*,
that *"For serious harm risk escalate through the clinical incident protocol."* and to *"Define
the on-call chain before enabling patient accounts."*, while recording in its security section
that *"There are no application access or audit logs to review"*. `docs/DEPLOYMENT.md` assigns the
remainder outward — *"Network/proxy restrictions, polling limits, host and HTTPS configuration,
response deadlines, monitoring and incident ownership remain external responsibilities."* — says
of the readiness report that *"it is not monitoring, serves no request and does not replace these
probes"*, and lists *"Provision TLS, secure headers, database backups and off-host encrypted
retention, monitoring/alerts, access review and restore drills."* among its release gates.

The records that measured the neighbouring ground say the same thing from inside their own scope.
[ADR 0217](ARCHITECTURE_DECISIONS/0217-deployment-readiness-report.md) limits its instrument —
*"It is not monitoring, alerting, MFA, TLS issuance, backup verification, network isolation, a
penetration test or an independent security assessment"*, *"Nothing verifies static files were
collected, logging is routed, clocks are synchronized, connection pooling is sized, replicas are
healthy, the process can actually serve a request, or that any external dependency is reachable.
No request is made."*, *"nothing here aggregates or stores them; there is no history, no alerting
and no dashboard."* — and warns that *"`database_reachable` is a single `SELECT 1` with a
one-second statement timeout, and it answers false inside an open transaction, so it must be run
outside one."* [ADR 0221](ARCHITECTURE_DECISIONS/0221-no-read-audit.md) pinned the absence of a
read record and then left exactly the question this document takes up: *"A reverse-proxy access
log, PostgreSQL's `log_statement`, a host audit daemon or an APM agent would all be invisible to
it."* and *"adding an access log is a design decision with retention, PHI and tamper-resistance
consequences that this project has not made"*.
[ADR 0223](ARCHITECTURE_DECISIONS/0223-no-abuse-protection.md) records that `docs/DEPLOYMENT.md`
*"asked for TLS, secure headers, backups, monitoring and access review in its release gates, and
mentioned "polling limits" once in passing for the health probes"*, and
[ADR 0228](ARCHITECTURE_DECISIONS/0228-public-read-limit.md) refused to let its limiter become
one: *"A limiter that stored what was read, by whom, or when, would be an access log wearing a
rate limit's clothes."* [ADR 0227](ARCHITECTURE_DECISIONS/0227-read-audit-plan.md) priced the
in-application record: *"Running nine suites that pin schema, configuration or read behavior
against the prototype — 138 tests — produced **20 failures across 7 of them**"* and *"the true
total of pins an implementation moves is at least 20 and was not measured completely."*, while
[`docs/READ_AUDIT_PLAN.md`](READ_AUDIT_PLAN.md) dismissed the outside option in one line — *"It
carries no actor, no route semantics and no target identity, it is invisible to this repository's
tests, and no such log is arranged today."* `docs/PHASE1_RELEASE_EVIDENCE.md` carries the gate
itself: *"**Open:** private access restrictions, network/request deadlines, monitoring, alert
routing, on-call ownership and incident response."*, *"What is not monitored is measured too: the
application records no read at all"*, *"so any request history has to come from the proxy, the
database or the host"* and *"so the runbook's instruction to review access and audit logs after a
restore still cannot be followed inside this application"*.

So the repository has two opt-in probes, one read-only report, one runbook that names four roles
and one protocol, and no answer to the five questions a monitoring and response capability
actually raises in production: **what would notice a condition, how soon, who would be told, with
what in hand, and which artifact would prove afterwards that any of it happened?**
[ADR 0237](ARCHITECTURE_DECISIONS/0237-monitoring-response-plan.md) records what this document
says and what it measures. It is not an alerting design, not an on-call rota, not a severity
model, not a logging configuration, not a retention schedule and not a choice of collector or
vendor.

This document is a **proposal**. It has no owner and no approval, so it must not be read as a
decision, and it must not treat one measurement run against a synthetic database and a development
process as a detection budget or a response objective. Its prices are counted from the files, the
configuration and the runs below, not prototyped: no collector was installed and removed, no alert
rule was written, no rota was drafted, no severity scale was defined and no sink was configured —
but the measurements **were** performed, against the synthetic PostgreSQL 16.2 server and the
development process this tree already runs, and every number below is the result of those runs.

**Nothing is implemented.** No `LOGGING` dictionary, no handler, no formatter, no logger name, no
metric, no alert rule, no threshold, no severity level, no escalation contact, no rota, no
collector, no agent, no scheduler entry, no healthcheck, no log driver, no rotation limit, no new
environment variable, no new command, no new table, no migration and no new dependency exists in
this tree because of this file. The measurements were performed with the `manage.py runserver`,
`manage.py check_deployment_readiness` and `manage.py test` commands the tree already has, the
`compose.yaml` and `Dockerfile` it already ships and the `.github/workflows/checks.yml` it already
runs, against a development process and a throwaway superuser account that no longer exist.

## What is true today, measured

Counted on this tree by reading `daroobank/settings.py`, `daroobank/health.py`,
`daroobank/urls.py`, `daroobank/middleware.py`,
`daroobank/management/commands/check_deployment_readiness.py`, `Dockerfile`, `compose.yaml` and
`.github/workflows/checks.yml`, and by running every experiment below against the synthetic
PostgreSQL 16.2 server, a development process on a loopback port and a throwaway superuser account
that the experiment created and deleted. Durations and byte counts belong to **one measured run**
on one machine and are quoted as such, never as a budget or a detection objective. They are pinned
by `daroobank/test_monitoring_response_plan.py`.

### The one signal that leaves the process

`settings.LOGGING` is `{}` and `settings.LOGGING_CONFIG` is left at `'logging.config.dictConfig'`,
so the configuration the project writes is empty and the handlers that exist are Django's own
defaults. Four loggers answer for this application: the root logger has no handler and level 30,
`django` has `['StreamHandler', 'AdminEmailHandler']` at level 20 and propagates, `django.request`
has no handler of its own at level 0 and propagates, and `django.server` has `['StreamHandler']`.
`settings.ADMINS` and `settings.MANAGERS` are both `[]`, so the one handler in the tree whose job
is to tell a human something — `AdminEmailHandler` — has no recipient and never sends.

Across the 120 non-test project modules there is not one `import logging` and not one emitter call
site: no `logger.`, no `logging.`, no `.warning(`, `.error(`, `.exception(`, `.critical(`,
`.info(` or `.debug(`. The 13 middleware entries, of which eight are this project's own, set
headers, redirect, count and delete sessions; none of them has a name that suggests recording and
none of them writes a log record.

What that leaves is the development server's own stderr, and the deployment runs the development
server: `Dockerfile` line 10 is `CMD ["sh", "-c", "python -m tools.wait_for_database && python
manage.py migrate --noinput && exec python manage.py runserver 0.0.0.0:8000"]`. Six requests to
that process — `/`, `/prices`, `/health/live/`, an API search path, the staff login page and one
path that does not exist — produced 388 bytes on stderr in 8 lines: six request lines of the form
`[28/Nov/2026 16:38:19] "GET /health/live/ HTTP/1.1" 404 0` and two `Not Found: /health/live/`
lines from `django.request`. That is the whole record. A request line carries a timestamp to the
second, a method, a path, a status and a byte count, and it carries no account, no session, no
route name, no duration, no request identifier, no client network address and no correlation to
anything else. It goes to the container's stdout, where `compose.yaml` — 44 lines, two services,
one volume named `postgres_data` — configures no `logging:` driver, no `max-size`, no `max-file`
and no volume to hold it.

### What a request leaves behind

Two full sweeps of all 55 routes, one anonymous and one as a fully permitted superuser, each
reached every route and each left the database and the filesystem exactly as it found them. The
anonymous sweep answered `{200: 9, 302: 41, 404: 4, 405: 1}` in 40.0 ms total, 0.73 ms per
request; the authenticated sweep answered `{200: 27, 404: 22, 405: 6}` in 201.1 ms total, 3.66 ms
per request. All 33 tables held the same row counts before and after each sweep, so **0 tables
moved**, and **0 files** were created or modified anywhere in the tree.

The log records are the interesting half. The anonymous sweep produced 5 records and the
authenticated sweep 28, every one of them a `django.request` WARNING, and every one of them came
from a failure: the 28 are exactly the 22 routes that answered 404 and the 6 that answered 405.
**The 27 reads that succeeded as a permitted superuser produced no record at all** — not a row,
not a log record, not a file. A successful read of clinical or price material by an identified
staff account is, on this evidence, indistinguishable from a read that never happened.

The only rows the experiment itself left are the ones it wrote deliberately: `auth_permission` 63,
`auth_user` 1, `django_content_type` 29, `django_migrations` 32 and `django_session` 1 — 5 of the
33 tables non-empty, and the account behind them was deleted afterwards.

### The two probes, and what they can distinguish

`daroobank/health.py` is 41 lines with four definitions — `database_ready`, `_probe`, `live` and
`ready` — and two routes, `/health/live/` and `/health/ready/`. With `HEALTH_PROBES_ENABLED` off,
which is the default and which is what `compose.yaml` sets
(`${DAROOBANK_HEALTH_PROBES_ENABLED:-0}`), both answer 404 with an empty body. With it on, both
answer 200 with the identical three-byte body `ok\n`, `POST`, `PUT` and `DELETE` answer 405 with
`Allow: GET, HEAD`, and `HEAD` answers 200 with no body. A successful answer carries eight
headers, among them `Cache-Control: no-store` and `X-Robots-Tag: noindex, nofollow`.

Because the two bodies are byte-identical, a poller that reads the body learns nothing at all;
only the status differs, and it differs only when the database does not answer. Median latency
over 25 requests each was 0.146 ms for `/health/live/` (minimum 0.122, maximum 1.361) and 0.417 ms
for `/health/ready/` (minimum 0.369, maximum 0.926), so polling readiness every ten seconds would
spend about 0.15% of one second per hour — cheap enough that cost is not the reason nothing polls
it.

`database_ready()` answers False when `connection.in_atomic_block`, which ADR 0217 already warns
about, and it was measured both ways rather than assumed: the same request answered **200 outside
a transaction and 503 inside one**. Any instrument that wraps this probe in a transaction — a test
written as an ordinary `TestCase`, or a caller that opens one — measures its own wrapper and
reports the database as down while it is up.

### The readiness report: one instrument, no schedule

`manage.py check_deployment_readiness` is the only monitoring-shaped tool in the tree. Run against
the synthetic settings it exits 1 and prints one 2,131-byte JSON document on stdout with nothing
on stderr, in a median of 306.4 ms over three runs (329.6, 306.4 and 302.0 ms). Its report has
five keys — `failed`, `ready`, `required`, `review` and `scope` — with `ready` false, ten required
checks of which four pass (`allowed_hosts_explicit`, `session_flags`,
`migration_history_consistent` and `database_reachable`) and six fail (`debug_disabled`,
`staff_portal_disabled`, `secret_key_shape`, `cookies_secure`, `ssl_redirect_enabled` and
`migrations_applied`), and its `scope` line reads *"settings and database shape for this process
only; not monitoring, alerting, MFA, TLS issuance, backups, network isolation or an independent
security assessment"*.

Its `review` list is not a fixed count: the source defines six identifiers — `hsts_disabled`,
`proxy_scheme_untrusted`, `development_hosts`, `health_probes_reachable`,
`synthetic_login_throttle` and `clickjacking_middleware_absent` — every one of them conditional,
and this run reported three. A number read off one run's output would be a number about one
configuration, so the six are counted from the source.

The command reads settings and never the environment: 0 occurrences of `os.environ` in its 189
lines, against 16 distinct settings it does read — six as `settings.<NAME>` and ten as names it
looks up, six of those ten through a tuple or a dictionary it iterates over rather than a literal
— and `DATABASES` is not among them, because it reaches the database through the connection it is
given rather than by reading how that connection is configured.

The environment behind those settings is inventoried elsewhere and none of it is monitoring
configuration. `daroobank/settings.py` performs 15 `os.environ` reads naming 13 distinct variables
— `DAROOBANK_ALLOWED_HOSTS` and `POSTGRES_SSLMODE` are each read twice — and reaches three more,
`POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_HOST`, through `required_database_setting`, which is
the sixteen `docs/PHASE1_RELEASE_EVIDENCE.md` counts when it says *"All sixteen environment
variables the application reads are now inventoried from the code and documented per audience"*.
Not one of the sixteen names a handler, a level, a sink, a recipient, a metric, a threshold or a
retention period, so there is no value an operator could set today that would make this
application emit a signal it does not already emit.

Nothing schedules it. `.github/workflows/checks.yml` is 217 lines across two jobs and contains the
word `runserver` zero times and `alert` and `monitor` zero times; the closest thing to a liveness
test anywhere in the repository is its compose job, which waits on `curl -fsS
http://127.0.0.1:8000/` at line 184 and asserts the same URL at line 187 — the home page, not
either probe, once per push and once per pull request. `compose.yaml` gives the `db` service a
`healthcheck:` at line 15 and the `web` service none, so in the stack this tree ships, the
container that answers requests is the only one nobody asks.

### The response side: four roles, one protocol, no contact

The runbook is the only response artifact in the tree, and it is 38 lines long. It names four
roles it escalates to and one protocol it escalates through, and no other document in this
repository names any of them: across the 264 documents this delivery neither writes nor edits,
`clinical lead`, `clinical owner`, `on-call chain`, `clinical incident protocol` and `escalation
contact` each appear in 0 and `data steward` appears in 1. Nothing defines any of them. No
document contains a severity scale (`severity level` 0 documents, `priority level` 0, `duty
roster` 0, `alarm` 0, `oncall` 0), no document sets a time by which a condition must be noticed
(`detection window` 0, `MTTD` 0, `MTTR` 0, `mean time` 0, `within 24 hours` 0, `within 72 hours`
0), and no document contains a person to contact: the only two email-shaped strings in those 264
documents are `checkout@v7.0.1`, which is an action reference, and `user@evil.example`, which is a
test fixture.

So the runbook's instructions are complete as prose and empty as routing. *"Escalate to data
steward/source owner."* names nobody, *"For serious harm risk escalate through the clinical
incident protocol."* points at a protocol that exists in exactly one sentence, and *"Define the
on-call chain before enabling patient accounts."* is the only place the chain is mentioned.

### Absence counted as artifacts, not as words

Counting words would prove nothing here, and the count says why: over the 264 documents this
delivery neither writes nor edits, the word `alert` appears in 17 documents, `incident` in 26,
`dashboard` in 7, `alerting` in 4, `on-call` in 2 and `severity` in 1 — because those are the
documents reporting that the thing does not exist, and the count would be higher still if this
delivery's own documents were left in it. The absence that matters is the absence of artifacts,
and it is total. Of the 747 files a tree scan counts, **0 have a name containing** any of `alert`,
`oncall`, `on-call`, `incident`, `postmortem`, `monitor`, `observab`, `telemetry`, `paging` or
`escalat`. None of the thirteen directories that would hold an operational artifact exists: `ops`,
`operations`, `runbooks`, `oncall`, `incidents`, `alerts`, `monitoring`, `dashboards`,
`terraform`, `ansible`, `k8s`, `helm` and `deploy` are all absent. `.github/workflows`,
`compose.yaml` and `requirements.in` together contain 0 occurrences of `alert`, `monitor`,
`sentry`, `datadog`, `prometheus`, `grafana`, `opentelemetry`, `logzio`, `papertrail`, `slack` and
`pagerduty`, and the corpus contains 0 documents naming any collector or vendor at all — `sentry`,
`datadog`, `prometheus`, `grafana`, `newrelic`, `opentelemetry`, `logstash`, `fluentd` and
`cloudwatch` each appear in none, as do `postmortem`, `post-incident`, `escalation policy`,
`observability`, `pager` and `page duty`.

The schema agrees. Of the 24 project models, 0 have a name containing `audit`, `access`,
`request`, `event`, `metric`, `session`, `record`, `track` or `visit`, and the two whose names
touch this area are counters rather than records: `StaffLoginWindow`, the development-only login
throttle's window, and `PublicReadWindow`, the opt-in read limiter's — each holding a keyed
digest, a window start and a count, so neither can say who read what. ADR 0221 pinned this from
the inside; what the counts above add is that there is nothing outside it either.

### What the repository already says about it

Every document that touches this area already says the area is empty, and says so in a sentence
this plan quotes rather than paraphrases: `docs/SECURITY.md` asks for incident severity and owners
before launch and for monitoring of unauthorized access; `docs/OPERATIONS_RUNBOOK.md` says no
dashboards, alerts or on-call rotation exist and that there are no access or audit logs to review;
`docs/DEPLOYMENT.md` assigns monitoring and incident ownership outward and says the readiness
report is not monitoring; `docs/PHASE1_RELEASE_EVIDENCE.md` carries monitoring, alert routing,
on-call ownership and incident response as an open gate; ADR 0217 says its instrument is not
monitoring or alerting and that nothing aggregates its output; ADR 0221 says an outside log would
be invisible to its pins and that `docs/DEPLOYMENT.md` does not arrange one; ADR 0223 records that
monitoring was asked for in the release gates; ADR 0227 prices the in-application record; ADR 0228
refuses to let a rate limiter become one; and `docs/READ_AUDIT_PLAN.md` dismisses edge logging as
carrying no actor and being arranged nowhere.

What none of them measured is the deployment side ADR 0221 explicitly left open — whether a sink
exists outside the process — and that is what this document adds: the deployed command is the
development server, its stderr is the only signal, nothing polls either probe, the app container
has no healthcheck, and no artifact, directory, dependency, contact, severity or schedule exists
anywhere in the tree.

## Candidate approach and decisions required

Eight decisions have to be made before any of the options below is defensible, and each one
changes what the others cost. None is made here.

1. **What is a condition worth noticing?** The tree can currently answer three questions about
   itself: can this process respond (`/health/live/`), can it run `SELECT 1` inside one second
   (`/health/ready/`), and does this process's configuration have a supported non-debug shape (the
   readiness report). Nothing defines a fourth. Error rate, latency, saturation, failed logins, a
   source that stopped, a price that moved, a certificate that expires and a backup that did not
   run are all candidate conditions and none is named, thresholded or owned. A condition nobody
   wrote down is a condition nobody is paged for.
2. **Where does a signal live?** Four candidates differ in cost and not in combination: the
   container's stdout, which is what exists and which nothing collects; a sink configured in
   `LOGGING`, which is a settings change and a PHI decision; the database, which is a schema
   change priced in option E; and a collector outside the repository, which is a vendor, a
   contract and a network egress decision that `docs/SECURITY.md` and the sanctions and
   data-residency review in `docs/DEPLOYMENT.md` both bear on.
3. **Who is told, and how are they reached?** The runbook names four roles and the tree contains
   no contact for any of them. Deciding this means naming a person or a queue per role, a channel
   that works from inside Iran, and a fallback when the first channel does not answer. This is the
   decision with the least engineering content and the most consequence, and it is the one nothing
   else can substitute for.
4. **What severity scale, and what does each level oblige?** `docs/SECURITY.md` requires incident
   severity to be defined before launch. A scale is only real if each level carries an
   acknowledgement time, a notification duty and an escalation step; the tree has no time by which
   anything must be noticed, so a scale written today would be a label with no obligation
   attached.
5. **Does a read get recorded inside the application?** This is the read-audit question ADR 0221
   declined and ADR 0227 priced, and it is a schema change: an append-only table, its migration
   and a middleware that writes a row per read. It is therefore a request to the lead's database
   lane, which carries ADR 0236 and `docs/DATABASE_CONNECTION_PLAN.md`, and not something this
   plan may decide or write. Decision 6 and decision 7 both change shape depending on this one,
   because a table of reads is a different privacy object from a line of stdout.
6. **What may a signal contain?** `docs/SECURITY.md` forbids PHI in metrics, search URLs, errors
   and analytics, and warns that search terms reach server and access logs. Any sink that records
   a path records a query string, and this application's search routes take a query parameter, so
   redaction is a precondition of the sink and not a refinement of it. Who reviews a redaction
   rule, and against what list, is undecided.
7. **How long is a signal kept, and who may read it?** A log of who read clinical material is
   itself sensitive. Retention, access control and tamper-resistance for the signal are the same
   three questions ADR 0227 lists for the audit table, and the tree answers none of them for
   stdout either — no rotation, no driver, no volume, no retention.
8. **What proves the response worked?** Nothing in the tree has ever been exercised end to end: no
   condition has been raised, no notification delivered, no acknowledgement recorded and no review
   written. Deciding what evidence would satisfy the gate — a drill, a recorded incident, a test
   that fails when the wiring breaks — determines whether any of the above can be claimed rather
   than asserted.

## Options and what each costs

Eight options, priced against the measurements above. No option is chosen here, none is
recommended and none is excluded; the ordering is by what has to be true first, not by preference.
Prices are counted from the pins and files above, not prototyped.

| Option | What changes | Price, counted | What it still does not answer |
| --- | --- | --- | --- |
| **A. Leave the detection and response surface exactly as measured** | nothing | 0 code files, 0 settings, 0 documents. The gate stays open and the absence stays as it is measured above: `LOGGING` `{}`, no emitter call site in 120 modules, no middleware that records, 0 tables moved by two sweeps of all 55 routes | anything. A condition inside this application becomes visible only when a user reports it, because the 27 successful authenticated reads produced no record, nobody schedules the readiness report, no healthcheck asks the `web` container anything, and the only signal is 388 bytes of development-server stderr per six requests that nothing collects |
| **B. Write the measured absence into the documents only** | this document, its record and one sentence in each of four neighbours, the changelog, the record index and both evidence cells | 6 documents edited, 2 added, 0 code files, 0 dependencies, and the recount of every shared pin the two new documents move | how a condition would be detected. What it buys is that the absence is counted as artifacts — 0 of 13 operational directories, 0 vendor mentions, 1 document naming the clinical incident protocol, 0 contacts in the 264-document corpus — instead of being described as a feeling |
| **C. Pin the detection surface in a suite of its own** | `daroobank/test_monitoring_response_plan.py`, which this delivery adds | 1 suite of 33 tests, 31 of them database-free, and the shared pins it moves; it detects no condition at runtime and emits no signal | what happens at 03:00 when something breaks. It makes the empty `LOGGING`, the four-logger handler shape, the 13 middleware entries, the 55-route sweeps, the identical three-byte probe bodies, the ten required checks and six review identifiers, the `Dockerfile` command, the absent `web` healthcheck and the absent log driver all things that fail loudly instead of things a reader has to remember |
| **D. Arrange the signal outside the application, at the edge or the host** | a proxy access log, PostgreSQL's `log_statement`, a host audit daemon or a container log collector — none of which this repository can pin, configure or test | 0 files here, and a deployment change this tree cannot see. `docs/READ_AUDIT_PLAN.md` already measured the limitation: *"It carries no actor, no route semantics and no target identity, it is invisible to this repository's tests, and no such log is arranged today."* | who read what. It would answer "was this path requested" and not "which account read this clinical record", and ADR 0221's pins would not notice it either way, because they measure the process |
| **E. Record the read inside the application, as a request to the database lane** | an append-only table, its migration, a row-per-read middleware and a setting to enable it — **a schema change**, so it belongs to the lead's database lane, which carries [ADR 0236](ARCHITECTURE_DECISIONS/0236-database-connection-plan.md) and [`docs/DATABASE_CONNECTION_PLAN.md`](DATABASE_CONNECTION_PLAN.md). This is a schema change: price it as a request to that lane. **No migration is written here and no model is proposed here.** | measured, not estimated, by [ADR 0227](ARCHITECTURE_DECISIONS/0227-read-audit-plan.md): *"Running nine suites that pin schema, configuration or read behavior against the prototype — 138 tests — produced **20 failures across 7 of them**"*, *"the true total of pins an implementation moves is at least 20 and was not measured completely."*, and a prototype schema of 33 tables, 283 columns, 113 indexes, 139 constraints, 51 foreign keys and 32 applied migrations against that day's 32, 276, 108, 136, 50 and 31, landing in a schema now at 33 tables, 279 columns, 111 indexes, 138 constraints, 50 foreign keys and 32 applied migrations | the six decisions ADR 0227 lists — scope, reader identity, retention, tamper-resistance, placement and enablement. Whoever makes it *"writes an accepted record that supersedes the seven this plan names, with their pins recomputed in the same change"*, and this plan writes no migration, proposes no model and adds no setting |
| **F. Give the deployment something to poll** | a `healthcheck:` on the `web` service in `compose.yaml`, and `DAROOBANK_HEALTH_PROBES_ENABLED=1` where the probes are network-restricted | 1 compose key, 1 environment value, 0 code files. Measured headroom: 0.417 ms median for `/health/ready/` and 0.146 ms for `/health/live/`, about 0.15% of one second per hour at a ten-second interval, so cost is not the obstacle | why a container was unhealthy, and what should happen next — `restart: on-failure` already restarts it, so a healthcheck turns a hung process into a restart loop with no record of why. It also inherits the measured trap: the probe answers 503 inside an open transaction, so a poller that wraps it reports a database that is up as down |
| **G. Configure logging in the application** | a `LOGGING` dictionary, a handler, a level and a formatter | 1 settings change that moves the four-logger shape this plan pins, plus a rotation, retention and redaction decision. To stdout it costs nothing new and changes only what `compose.yaml` does not collect; to a file it adds a volume, a permission and a retention question the tree has no answer to | who is told. It would also give `AdminEmailHandler` something to do, which needs `ADMINS` to hold an address, and the tree contains no address to put there. It has to satisfy *"Do not put PHI in metrics, search URLs, errors or analytics"* on routes that take a search query, so the redaction rule is the hard part and not the handler |
| **H. Choose a collector, a severity scale and a rota** | a vendor or a self-hosted stack, a severity scale with an obligation per level, and a rota of named people | the most expensive option in this list and the only one this repository is least able to price: a contract, network egress from a deployment whose sanctions, vendor and data-residency constraints `docs/DEPLOYMENT.md` says must be reviewed before a provider is chosen, and 0 contacts in the 264-document corpus to put on the rota | nothing, if it is done — it is the only option that produces a responder rather than a signal, which is why options D through G do not close the gate without it. No collector was installed, no vendor was contacted and no notification was delivered to a person here, and the corpus names none |

## Required behavior before any condition is wired to a person

Seven requirements. Each is written so that a reader can tell whether it is met, and none is met
today.

1. **Name the condition.** A condition is written down with the observation that reveals it, the
   threshold at which it counts and the severity it carries — not left to whatever a future
   collector's default rules happen to fire on.
2. **Give every condition a destination.** One role, one channel and one fallback, each of them a
   value rather than a job title, with the four roles the runbook already names resolved to
   something reachable.
3. **Attach an obligation to every severity level.** An acknowledgement time, a notification duty
   and an escalation step, so that the scale `docs/SECURITY.md` requires decides what happens next
   rather than only describing how bad something is.
4. **Redact the signal before it is written.** On the routes that carry a search query, and with
   the redaction rule reviewed against the PHI prohibition rather than assumed to follow from it.
5. **Give the signal a retention and an access rule.** How long it is kept, who may read it, and
   what stops an application role from altering it — the same three questions ADR 0227 asks of an
   audit table, asked here of stdout, a file and a collector.
6. **Keep the poller out of the transaction.** Whatever polls a probe does not wrap it in one, and
   a 503 is distinguishable from the 503 that an open transaction produces by accident, because
   both were measured from the same code path.
7. **Exercise the wiring once end to end.** A condition raised, a notification delivered, an
   acknowledgement recorded and a review written, with the evidence kept with the release record
   the way `docs/OPERATIONS_RUNBOOK.md` already asks the readiness output to be kept.

## Verification before any enablement

Seven checks. Each one is runnable in this repository, or says explicitly what it is not.

- `daroobank/test_monitoring_response_plan.py` passes, and its pins are the ones this document
  quotes: the empty `LOGGING`, the four-logger handler shape, the 13 middleware entries with none
  of them recording, the 120 modules with no emitter call site, the two sweeps' status
  distributions and their 0 moved tables, the 27 successful reads with 0 records, the probes'
  identical three-byte bodies and their 405 with `Allow: GET, HEAD`, the readiness report's ten
  required checks and six source-defined review identifiers, the `Dockerfile` command line, the
  one `healthcheck:` on `db` and none on `web`, and the 0 counts over file names, directories and
  vendor mentions.
- Every quotation in this document is present **verbatim** in the document it is quoted from,
  asserted by the suite in both places at once, so a reworded requirement fails a test instead of
  silently diverging from the plan that prices it.
- The suite's red checks were run one at a time on a byte-identical tree, each mutation restored
  and verified by checksum before the next, and every one of them failed the suite — the results
  are in the `Red checks` table of
  [ADR 0237](ARCHITECTURE_DECISIONS/0237-monitoring-response-plan.md), and a mutation that no test
  caught is listed there as a gap rather than dropped.
- A sink added later is caught by a test rather than by a reader: enabling the probes in
  `compose.yaml`, adding a `healthcheck:` to `web`, adding a `logging:` driver, adding a `LOGGING`
  dictionary, adding a collector dependency or adding a model whose name suggests an access record
  each fails a named pin, and the failure message says which document has to be updated with it.
- Whatever is verified is verified the way CI verifies it: `DAROOBANK_DEBUG=1`, an explicit
  `PYTHONHASHSEED`, `--settings=daroobank.synthetic_test_settings` and `--noinput`, against a
  PostgreSQL server whose coordinates come from the environment, with the full suite run to
  completion on two seeds rather than a sample.
- **No duration, byte count or latency in this document is a budget.** Each is one measured run on
  one machine against synthetic data, quoted so that a later run can be compared with it, and the
  suite pins the numbers as measurements rather than as thresholds anything must meet.
- What cannot be verified here is stated rather than approximated: no collector was installed, no
  vendor was contacted, no notification was delivered to a person, no severity scale was ratified,
  no rota was staffed, and **no build, image size, container startup or deployment timing was
  measured, because `docker` is not installed in this environment** — the `Dockerfile` and
  `compose.yaml` facts in this document were read from those files, not run.
