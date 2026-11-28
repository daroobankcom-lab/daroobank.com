"""The monitoring and response plan is a proposal, its numbers are measured, and the absence is real.

`docs/MONITORING_RESPONSE_PLAN.md` exists because `docs/SECURITY.md` requires incident severity,
containment, notification and recovery owners before launch and asks this system to *monitor
unauthorized access*, because `docs/OPERATIONS_RUNBOOK.md` says *"No production services, dashboards,
alerts or on-call rotation currently exist."* and then escalates to four roles and one protocol that
no document defines, and because `docs/PHASE1_RELEASE_EVIDENCE.md` carries *"monitoring, alert
routing, on-call ownership and incident response"* as an open gate. ADR 0221 pinned the absence of a
read record inside the process and explicitly left the outside open: *"A reverse-proxy access log,
PostgreSQL's `log_statement`, a host audit daemon or an APM agent would all be invisible to it."*
This suite measures that outside.

What is pinned here, and why a test rather than a sentence:

* the plan's shape — its sections, its eight decisions, its eight options, its seven requirements and
  its seven verification checks — so a section cannot be dropped quietly;
* the thirty-one requirements it is priced against, quoted **verbatim** and asserted in both the plan
  and the document each one comes from, so rewording a requirement fails a test instead of leaving the
  plan pricing a sentence that no longer exists;
* that the plan is an unowned proposal: no owner, no approval, and none of the phrases that would make
  it choose an option instead of pricing one;
* the measured absence — an empty `LOGGING`, four loggers with Django's default handlers and no
  recipient behind `AdminEmailHandler`, 120 project modules with no emitter call site, 13 middleware
  entries none of which records, 24 models none of which can hold a record, a `Dockerfile` whose
  production command is the development server, a `compose.yaml` that gives the database a healthcheck
  and the application none, a workflow that polls the home page rather than either probe, and 0
  artifacts, directories, dependencies, vendors, severities or contacts;
* the two live instruments — what the probes answer and what they cannot distinguish, and what two
  sweeps of all 55 routes leave behind, which is 0 moved tables, 0 changed files, and a log record for
  every failure and for no success at all;
* the neighbours, the changelog, both evidence cells and the record index, so the delivery cannot land
  half-linked.

What is **not** checked: whether a condition anybody would care about is missing from the list, whether
an escalation path would work, whether a vendor would be acceptable, or whether the measurements would
hold on different hardware. The suite holds the plan to the tree, not the tree to an opinion.
"""
import ast
import logging
import re
import time
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection, transaction
from django.test import Client, SimpleTestCase, TransactionTestCase, override_settings
from django.urls import get_resolver, reverse

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'MONITORING_RESPONSE_PLAN.md'
ADR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0237-monitoring-response-plan.md'
ADR_DIR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS'
ADR_INDEX = ADR_DIR / 'README.md'
CHANGELOG = ROOT / 'docs' / 'CHANGELOG.md'
EVIDENCE = ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
RUNBOOK = ROOT / 'docs' / 'OPERATIONS_RUNBOOK.md'
SECURITY = ROOT / 'docs' / 'SECURITY.md'
TESTING = ROOT / 'docs' / 'TESTING_STRATEGY.md'
README = ROOT / 'README.md'
READ_AUDIT_PLAN = ROOT / 'docs' / 'READ_AUDIT_PLAN.md'
HEALTH = ROOT / 'daroobank' / 'health.py'
URLS = ROOT / 'daroobank' / 'urls.py'
SETTINGS = ROOT / 'daroobank' / 'settings.py'
READINESS = ROOT / 'daroobank' / 'management' / 'commands' / 'check_deployment_readiness.py'
DOCKERFILE = ROOT / 'Dockerfile'
COMPOSE = ROOT / 'compose.yaml'
WORKFLOW = ROOT / '.github' / 'workflows' / 'checks.yml'
REQUIREMENTS_IN = ROOT / 'requirements.in'
ADR_0217 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0217-deployment-readiness-report.md'
ADR_0221 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0221-no-read-audit.md'
ADR_0223 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0223-no-abuse-protection.md'
ADR_0227 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0227-read-audit-plan.md'
ADR_0228 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0228-public-read-limit.md'
ADR_0236 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0236-database-connection-plan.md'
SKIP_PARTS = ('.venv', '.cache', '.git', 'node_modules', '__pycache__', 'staticfiles', 'backups')
PROJECT_APPS = frozenset({'catalog', 'clinical', 'daroobank', 'ingestion', 'pricing', 'sources',
                          'staff_security'})
# This delivery's own files. A document that reports the absence of a word cannot be one of the
# documents searched for it, and a suite that names a collector in order to forbid it cannot be one
# of the files scanned for collectors.
OWN_FILES = (PLAN, ADR, Path(__file__).resolve())
# The nine documents this delivery writes or edits, excluded from the document corpus the plan counts
# over. The sentences it adds to its neighbours name `alert`, `incident`, `severity` and `dashboard`
# in order to say that no artifact, rota or scale exists behind them, so counting them would raise
# every absence count by the number of documents that report the absence.
ITEM_DOCS = (PLAN, ADR, ADR_INDEX, CHANGELOG, EVIDENCE, DEPLOYMENT, RUNBOOK, SECURITY, TESTING)

SECTIONS = ['What is true today, measured',
            'Candidate approach and decisions required',
            'Options and what each costs',
            'Required behavior before any condition is wired to a person',
            'Verification before any enablement']
SUBSECTIONS = ['The one signal that leaves the process',
               'What a request leaves behind',
               'The two probes, and what they can distinguish',
               'The readiness report: one instrument, no schedule',
               'The response side: four roles, one protocol, no contact',
               'Absence counted as artifacts, not as words',
               'What the repository already says about it']
RECORD_SECTIONS = ['## Context', '## Decision', '## Measured behavior', '## Red checks',
                   '## Consequences', '## Limitations']
DECISION_COUNT = 8
OPTION_COUNT = 8
REQUIRED_BEHAVIOR_COUNT = 7
VERIFICATION_COUNT = 7
# The lead-in of each decision, so a decision cannot be reworded into something the record does not
# name, and the label of each option row in the table the plan family uses.
DECISION_LEADS = ['**What is a condition worth noticing?**',
                  '**Where does a signal live?**',
                  '**Who is told, and how are they reached?**',
                  '**What severity scale, and what does each level oblige?**',
                  '**Does a read get recorded inside the application?**',
                  '**What may a signal contain?**',
                  '**How long is a signal kept, and who may read it?**',
                  '**What proves the response worked?**']
OPTION_LABELS = list('ABCDEFGH')
PROPOSAL_PHRASES = ['This document is a **proposal**', 'It has no owner and no approval',
                    '**Nothing is implemented.**', 'must not be read as a decision',
                    'no collector was installed and removed',
                    'a throwaway superuser account that no longer exist',
                    'No `LOGGING` dictionary, no handler, no formatter']
FORBIDDEN_SELECTION = ['The selected approach is to', 'is selected because',
                       'the recommended approach', 'should be adopted', 'The selected option is',
                       'we recommend', 'the best option is']
# The requirement each document states, quoted into the plan and pinned here, so the plan cannot drift
# away from the sentences it is written against.
QUOTED_REQUIREMENTS = [
    (SECURITY, 'Protect audit from modification by application roles and monitor unauthorized '
               'access.'),
    (SECURITY, 'Define incident severity, containment, notification and recovery owners before '
               'launch.'),
    (SECURITY, 'Do not put PHI in metrics, search URLs, errors or analytics.'),
    (SECURITY, 'Search terms can appear in server/access logs; do not enter PHI and configure '
               'logging/redaction before production.'),
    (RUNBOOK, 'No production services, dashboards, alerts or on-call rotation currently exist.'),
    (RUNBOOK, 'Create concrete commands, owners and escalation contacts before production.'),
    (RUNBOOK, 'Escalate to data steward/source owner.'),
    (RUNBOOK, 'notify clinical lead and affected users where legally appropriate'),
    (RUNBOOK, 'For serious harm risk escalate through the clinical incident protocol.'),
    (RUNBOOK, 'Define the on-call chain before enabling patient accounts.'),
    (RUNBOOK, 'There are no application access or audit logs to review'),
    (DEPLOYMENT, 'Network/proxy restrictions, polling limits, host and HTTPS configuration, response '
                 'deadlines, monitoring and incident ownership remain external responsibilities.'),
    (DEPLOYMENT, 'it is not monitoring, serves no request and does not replace these probes'),
    (DEPLOYMENT, 'Provision TLS, secure headers, database backups and off-host encrypted retention, '
                 'monitoring/alerts, access review and restore drills.'),
    (ADR_0217, 'It is not monitoring, alerting, MFA, TLS issuance, backup verification, network '
               'isolation, a penetration test or an independent security assessment'),
    (ADR_0217, 'Nothing verifies static files were collected, logging is routed, clocks are '
               'synchronized, connection pooling is sized, replicas are healthy, the process can '
               'actually serve a request, or that any external dependency is reachable. No request '
               'is made.'),
    (ADR_0217, 'nothing here aggregates or stores them; there is no history, no alerting and no '
               'dashboard.'),
    (ADR_0217, '`database_reachable` is a single `SELECT 1` with a one-second statement timeout, and '
               'it answers false inside an open transaction, so it must be run outside one.'),
    (ADR_0221, "A reverse-proxy access log, PostgreSQL's `log_statement`, a host audit daemon or an "
               'APM agent would all be invisible to it.'),
    (ADR_0221, 'adding an access log is a design decision with retention, PHI and tamper-resistance '
               'consequences that this project has not made'),
    (ADR_0223, 'asked for TLS, secure headers, backups, monitoring and access review in its release '
               'gates, and mentioned "polling limits" once in passing for the health probes'),
    (ADR_0227, 'Running nine suites that pin schema, configuration or read behavior against the '
               'prototype — 138 tests — produced **20 failures across 7 of them**'),
    (ADR_0227, 'the true total of pins an implementation moves is at least 20 and was not measured '
               'completely.'),
    (ADR_0227, 'writes an accepted record that supersedes the seven this plan names, with their pins '
               'recomputed in the same change'),
    (ADR_0228, 'A limiter that stored what was read, by whom, or when, would be an access log '
               "wearing a rate limit's clothes."),
    (READ_AUDIT_PLAN, "It carries no actor, no route semantics and no target identity, it is "
                      "invisible to this repository's tests, and no such log is arranged today."),
    (EVIDENCE, '**Open:** private access restrictions, network/request deadlines, monitoring, alert '
               'routing, on-call ownership and incident response.'),
    (EVIDENCE, 'What is not monitored is measured too: the application records no read at all'),
    (EVIDENCE, 'so any request history has to come from the proxy, the database or the host'),
    (EVIDENCE, "so the runbook's instruction to review access and audit logs after a restore still "
               'cannot be followed inside this application'),
    (EVIDENCE, 'All sixteen environment variables the application reads are now inventoried from the '
               'code and documented per audience'),
]
PLAN_DEPENDENCIES = ['docs/SECURITY.md', 'docs/OPERATIONS_RUNBOOK.md', 'docs/DEPLOYMENT.md',
                     'docs/PHASE1_RELEASE_EVIDENCE.md', 'docs/READ_AUDIT_PLAN.md',
                     'docs/DATABASE_CONNECTION_PLAN.md', 'daroobank/settings.py',
                     'daroobank/health.py', 'daroobank/urls.py', 'compose.yaml', 'Dockerfile',
                     '.github/workflows/checks.yml', 'requirements.in',
                     'daroobank/test_monitoring_response_plan.py',
                     'daroobank/management/commands/check_deployment_readiness.py',
                     '0217-deployment-readiness-report.md', '0221-no-read-audit.md',
                     '0223-no-abuse-protection.md', '0227-read-audit-plan.md',
                     '0228-public-read-limit.md', '0236-database-connection-plan.md',
                     '0237-monitoring-response-plan.md']
# The nine of those the plan links rather than only names, and the plan's whole link count. Naming a
# dependency in prose survives the link being deleted, and an unlinked document is one step from an
# orphaned one, which is the failure `test_document_links.py` exists to catch.
LINKED_DEPENDENCIES = ['READ_AUDIT_PLAN.md', 'DATABASE_CONNECTION_PLAN.md',
                       '0217-deployment-readiness-report.md', '0221-no-read-audit.md',
                       '0223-no-abuse-protection.md', '0227-read-audit-plan.md',
                       '0228-public-read-limit.md', '0236-database-connection-plan.md',
                       '0237-monitoring-response-plan.md']
PLAN_LINK_COUNT = 11

# The suites whose pins this delivery moves, and the values the record states for them. A record that
# states a pin states history — ADR 0232 says the suites that count test modules `now count 238` and
# ADR 0233 says 239, and both have moved since without either record being rewritten — so the
# statement is held as a statement and each live pin is held to the thing it counts.
FENCE = re.compile(r'^(```|~~~)')
LINK = re.compile(r'\[[^\]]*\]\(\s*([^)\s]+)\s*\)')
EXTERNAL_PREFIXES = ('http://', 'https://', 'mailto:')
DOCUMENT_LINKS = ROOT / 'daroobank' / 'test_document_links.py'
MIGRATION_SUITE = ROOT / 'daroobank' / 'test_database_migration_plan.py'
MFA_SUITE = ROOT / 'daroobank' / 'test_mfa_implementation_plan.py'
SECRET_SUITE = ROOT / 'daroobank' / 'test_secret_rotation_plan.py'
BACKUP_SUITE = ROOT / 'daroobank' / 'test_backup_recovery_plan.py'
CONNECTION_SUITE = ROOT / 'daroobank' / 'test_database_connection_plan.py'
PIN_DELTAS = ['`DOCUMENT_COUNT` 273', '`ADR_COUNT` 237', '`LINK_COUNT` 1,254',
              '`SUITE_LINE_COUNT` 27', '`TEST_MODULE_COUNT` 244',
              '243 in the MFA and secret-rotation suites', '`DOCS_MARKDOWN_COUNT` 272',
              '`CORPUS_COUNT` 261', '`TREE_FILE_COUNT` 747', '`LOGIN_ROUTE_TESTS` stays 46']
RED_CHECK_COUNT = 39
NEIGHBOURS = (DEPLOYMENT, RUNBOOK, SECURITY, TESTING)
EVIDENCE_ROW = 'Monitoring and response'
# The measured numbers, as the plan states them. Each is one run, not a budget.
MEASURED = [
    '`settings.LOGGING` is `{}`',
    "`'logging.config.dictConfig'`",
    "['StreamHandler', 'AdminEmailHandler']",
    'the 120 non-test project modules there is not one `import logging`',
    'The 13 middleware entries, of which eight are this project\'s own',
    'six request lines of the form',
    '388 bytes on stderr in 8 lines',
    '44 lines, two services, one volume named `postgres_data`',
    '`{200: 9, 302: 41, 404: 4, 405: 1}` in 40.0 ms total, 0.73 ms per request',
    '`{200: 27, 404: 22, 405: 6}` in 201.1 ms total, 3.66 ms per request',
    '**0 tables moved**',
    'The 27 reads that succeeded as a permitted superuser produced no record at all',
    '`auth_permission` 63, `auth_user` 1, `django_content_type` 29, `django_migrations` 32 and '
    '`django_session` 1',
    '41 lines with four definitions',
    'the identical three-byte body',
    '405 with `Allow: GET, HEAD`',
    '0.146 ms for `/health/live/` (minimum 0.122, maximum 1.361)',
    '0.417 ms for `/health/ready/` (minimum 0.369, maximum 0.926)',
    'about 0.15% of one second per hour',
    '**200 outside a transaction and 503 inside one**',
    'a median of 306.4 ms over three runs (329.6, 306.4 and 302.0 ms)',
    'one 2,131-byte JSON document on stdout',
    'ten required checks of which four pass',
    'six identifiers',
    '0 occurrences of `os.environ` in its 189 lines',
    '16 distinct settings it does read',
    'performs 15 `os.environ` reads naming 13 distinct variables',
    '217 lines across two jobs',
    '`clinical lead`, `clinical owner`, `on-call chain`, `clinical incident protocol` and '
    '`escalation contact` each appear in 0 and `data steward` appears in 1',
    'the only two email-shaped strings in those 264 documents are `checkout@v7.0.1`',
    'across the 264 documents this delivery neither writes nor edits',
    'over the 264 documents this delivery neither writes nor edits',
    'the word `alert` appears in 17 documents',
    '**0 have a name containing**',
    'None of the thirteen directories',
    'Of the 24 project models',
    '33 tables, 283 columns, 113 indexes, 139 constraints, 51 foreign keys and 32 applied migrations',
]
# Tokens whose absence is counted over documents, with the document count each was measured at.
# The corpus excludes the nine documents this delivery writes or edits, so these are the documents
# that reported the absence before it, not the ones repeating it after.
CORPUS_COUNT = 266
DOC_TOKEN_COUNTS = {'alert': 19, 'alerting': 4, 'incident': 26, 'on-call': 2, 'dashboard': 7,
                    'severity': 1, 'telemetry': 1, 'incident response': 1, 'data steward': 1}
ABSENT_TOKENS = ['oncall', 'severity level', 'priority level', 'duty roster', 'alarm',
                 'escalation policy', 'postmortem', 'post-incident', 'observability', 'pager',
                 'page duty', 'detection window', 'mttd', 'mttr', 'mean time', 'within 24 hours',
                 'within 72 hours', 'alert routing', 'sentry', 'datadog', 'prometheus', 'grafana',
                 'newrelic', 'opentelemetry', 'logstash', 'fluentd', 'cloudwatch']
# The roles and the protocol the runbook escalates to. Each is asserted twice: present in the
# runbook, which is where the instruction lives, and absent from every other document, which is what
# makes it an instruction with no definition behind it.
ROLE_TERMS = ['clinical lead', 'clinical owner', 'on-call chain', 'clinical incident protocol',
              'escalation contact']
NAME_TOKENS = ['alert', 'oncall', 'on-call', 'incident', 'postmortem', 'monitor', 'observab',
               'telemetry', 'paging', 'escalat']
ABSENT_DIRECTORIES = ['ops', 'operations', 'runbooks', 'oncall', 'incidents', 'alerts', 'monitoring',
                      'dashboards', 'terraform', 'ansible', 'k8s', 'helm', 'deploy']
CONFIG_TOKENS = ['alert', 'monitor', 'sentry', 'datadog', 'prometheus', 'grafana', 'opentelemetry',
                 'logzio', 'papertrail', 'slack', 'pagerduty']
ROUTE_COUNT = 55
STAFF_ROUTE_COUNT = 43
HEALTH_ROUTE_COUNT = 2
API_ROUTE_COUNT = 3
PUBLIC_ROUTE_COUNT = 7
URLS_LINES = 66
HEALTH_LINES = 41
HEALTH_DEFINITIONS = ['database_ready', '_probe', 'live', 'ready']
PROJECT_MODULE_COUNT = 120
MIDDLEWARE_COUNT = 13
PROJECT_MIDDLEWARE_COUNT = 8
PROJECT_MODEL_COUNT = 24
RECORD_LIKE_TOKENS = ['audit', 'access', 'request', 'event', 'metric', 'session', 'record', 'track',
                      'visit']
COUNTER_MODELS = ['PublicReadWindow', 'StaffLoginWindow']
LOGGER_HANDLERS = {'django': ['AdminEmailHandler', 'StreamHandler'],
                   'django.request': [], 'django.server': ['StreamHandler']}
LOGGER_LEVELS = {'django': 20, 'django.request': 0}
REQUIRED_CHECKS = ['debug_disabled', 'staff_portal_disabled', 'secret_key_shape',
                   'allowed_hosts_explicit', 'cookies_secure', 'session_flags',
                   'ssl_redirect_enabled', 'migrations_applied', 'migration_history_consistent',
                   'database_reachable']
REVIEW_IDS = ['hsts_disabled', 'proxy_scheme_untrusted', 'development_hosts',
              'health_probes_reachable', 'synthetic_login_throttle',
              'clickjacking_middleware_absent']
REPORT_SETTINGS = ['ALLOWED_HOSTS', 'CSRF_COOKIE_SECURE', 'DEBUG', 'HEALTH_PROBES_ENABLED',
                   'MIDDLEWARE', 'SECRET_KEY', 'SECURE_HSTS_SECONDS', 'SECURE_PROXY_SSL_HEADER',
                   'SECURE_SSL_REDIRECT', 'SESSION_COOKIE_AGE', 'SESSION_COOKIE_HTTPONLY',
                   'SESSION_COOKIE_SAMESITE', 'SESSION_COOKIE_SECURE',
                   'SESSION_EXPIRE_AT_BROWSER_CLOSE', 'STAFF_LOGIN_THROTTLE_ENABLED',
                   'STAFF_PORTAL_ENABLED']
# Which required checks pass is a fact about the process that runs the report, not a fact about the
# report, so it is pinned as one and named as one. This is the answer **in a test process**: `DEBUG`
# is off here, so `debug_disabled` passes, and the runner has applied every migration to the test
# database, so `migrations_applied` passes too. The command-line run the plan quotes had
# `DAROOBANK_DEBUG=1` against a database with migrations pending, and passed four of the ten instead.
# Both are correct answers about different processes, which is ADR 0217's point that a deployment
# needs one report per process; the plan says which run each number came from.
PASSED_IN_A_TEST_PROCESS = ['allowed_hosts_explicit', 'database_reachable', 'debug_disabled',
                            'migration_history_consistent', 'migrations_applied', 'session_flags']
FAILED_IN_A_TEST_PROCESS = ['cookies_secure', 'secret_key_shape', 'ssl_redirect_enabled',
                            'staff_portal_disabled']
REPORT_SCOPE = ('settings and database shape for this process only; not monitoring, alerting, MFA, '
                'TLS issuance, backups, network isolation or an independent security assessment')
READINESS_LINES = 189
ENVIRONMENT_READS = 15
ENVIRONMENT_LITERALS = 13
ENVIRONMENT_VIA_HELPER = ['POSTGRES_DB', 'POSTGRES_HOST', 'POSTGRES_USER']
ENVIRONMENT_NAMES = 16
COMPOSE_LINES = 44
COMPOSE_SERVICES = ['db', 'web']
COMPOSE_HEALTHCHECKS = 1
WORKFLOW_LINES = 217
WORKFLOW_CURLS = 2
DOCKERFILE_COMMAND = ('CMD ["sh", "-c", "python -m tools.wait_for_database && python manage.py '
                      'migrate --noinput && exec python manage.py runserver 0.0.0.0:8000"]')
SWEEP_TABLES = 33
ANONYMOUS_STATUSES = {200: 9, 302: 41, 404: 4, 405: 1}
AUTHENTICATED_STATUSES = {200: 27, 404: 22, 405: 6}
ANONYMOUS_RECORDS = 5
AUTHENTICATED_RECORDS = 28
EMAIL_SHAPED = ['checkout@v7.0.1', 'user@evil.example']


def read(path):
    return path.read_text(encoding='utf-8')


def flat(text):
    """The document as one line, so a hard-wrapped phrase can be matched."""
    return ' '.join(text.split())


def documents():
    """Every markdown document in the repository, README first."""
    return [README] + sorted((ROOT / 'docs').rglob('*.md'))


def corpus():
    """The documents the absence is counted over: all of them except the ones this delivery edits."""
    excluded = {path.resolve() for path in ITEM_DOCS} | {Path(__file__).resolve()}
    return [path for path in documents() if path.resolve() not in excluded]


def tree_files():
    own = {path.resolve() for path in OWN_FILES}
    return [path for path in sorted(ROOT.rglob('*'))
            if path.is_file()
            and not any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts)
            and path.resolve() not in own]


def project_modules():
    """Non-test, non-migration Python modules of the seven project apps.

    The same population ADR 0221 scanned and `daroobank/test_database_connection_plan.py` pins at
    120: a file is excluded for being named `test_*.py` or `tests.py`, or for living under
    `migrations/` or `tests/`, and not for containing the letters `test` anywhere, which would
    quietly drop `synthetic_test_settings.py` and `isolated_test_runner.py` from a scan whose whole
    claim is that nothing in the project emits a log record.
    """
    found = []
    for app in sorted(PROJECT_APPS):
        for module in sorted((ROOT / app).rglob('*.py')):
            relative = module.relative_to(ROOT).as_posix()
            if module.name.startswith('test_') or module.name == 'tests.py':
                continue
            if '/migrations/' in relative or '/tests/' in relative:
                continue
            found.append((relative, module))
    return found


def pin(text, name):
    """The integer another suite pins under `name`, read from its source rather than imported."""
    match = re.search(r'(?m)^%s = (\d+)$' % re.escape(name), text)
    assert match, 'a suite stopped pinning %s' % name
    return int(match.group(1))


def prose(text):
    """The lines of a document that are not inside a fenced code block."""
    lines, inside = [], False
    for line in text.splitlines():
        if FENCE.match(line.strip()):
            inside = not inside
            continue
        if not inside:
            lines.append(line)
    return lines


def all_links(text):
    """Every markdown link target in a document's prose, in order."""
    found = []
    for line in prose(text):
        found += LINK.findall(line)
    return found


def sections(text):
    return re.findall(r'(?m)^## (.*)$', text)


def subsections(text):
    return re.findall(r'(?m)^### (.*)$', text)


def section(text, heading):
    """One `## ` section of a document, body only."""
    return text.partition(f'## {heading}')[2].partition('\n## ')[0]


def numbered(text):
    """The numbers of a `1.`-style list, in order, so an item cannot be silently unnumbered."""
    return [int(match.group(1)) for match in re.finditer(r'(?m)^(\d+)\. ', text)]


def route_targets():
    """Every named route in the URLconf, as the pattern that produced it and its name."""
    rows = []

    def walk(resolver, prefix):
        for entry in resolver.url_patterns:
            if hasattr(entry, 'url_patterns'):
                walk(entry, prefix + str(entry.pattern))
            else:
                rows.append((prefix + str(entry.pattern), entry.name or ''))
    walk(get_resolver(), '')
    return rows


def url_for(pattern, name):
    """Reverse a route from the arguments its own pattern asks for, in the order it asks for them."""
    kinds = []
    for token in ('<str:kind>', '<int:pk>'):
        for match in re.finditer(re.escape(token), pattern):
            kinds.append((match.start(), token))
    kinds.sort()
    args = ['package' if token == '<str:kind>' else 999999999 for _start, token in kinds]
    return reverse(name, args=args) if args else reverse(name)


def row_counts():
    with connection.cursor() as cursor:
        cursor.execute("select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
                       " where c.relkind = 'r' and n.nspname = 'public' order by relname")
        tables = [row[0] for row in cursor.fetchall()]
        counts = {}
        for table in tables:
            cursor.execute(f'select count(*) from "{table}"')
            counts[table] = cursor.fetchone()[0]
    return tables, counts


def tree_snapshot():
    snapshot = {}
    for path in tree_files():
        stat = path.stat()
        snapshot[path.relative_to(ROOT).as_posix()] = (stat.st_size, stat.st_mtime_ns)
    return snapshot


class Capture(logging.Handler):
    """One handler on the root logger, so a propagated record is counted once and not twice."""

    def __init__(self):
        super().__init__(level=0)
        self.records = []

    def emit(self, record):
        self.records.append(record)


def evidence_cells():
    """The three cells of the `Monitoring and response` row of the release-evidence table."""
    for line in read(EVIDENCE).splitlines():
        if line.startswith(f'| {EVIDENCE_ROW} |'):
            cells = line.split('|')
            return cells[1].strip(), cells[2].strip(), cells[3].strip()
    raise AssertionError(f'the {EVIDENCE_ROW!r} row is gone from the release evidence')


class PlanShapeTests(SimpleTestCase):
    def test_the_plan_has_the_sections_the_plan_family_uses(self):
        text = read(PLAN)
        for heading in SECTIONS:
            with self.subTest(section=heading):
                self.assertIn(f'## {heading}', text, 'a section the family uses is missing')
        positions = [text.index(f'## {heading}') for heading in SECTIONS]
        self.assertEqual(positions, sorted(positions), 'the sections were reordered')
        measured = text.split('## What is true today, measured', 1)[1]
        for heading in SUBSECTIONS:
            with self.subTest(subsection=heading):
                self.assertIn(f'### {heading}', measured, 'a measured subsection is missing')
        self.assertEqual(len(re.findall(r'^### ', measured, re.M)), len(SUBSECTIONS),
                         'a subsection appeared that this suite does not name')

    def test_the_plan_prices_eight_decisions_and_eight_options(self):
        text = read(PLAN)
        self.assertEqual(sections(text), SECTIONS, 'the plan grew or lost a section')
        self.assertEqual(subsections(text), SUBSECTIONS, 'the plan grew or lost a subsection')
        self.assertEqual(numbered(section(text, 'Candidate approach and decisions required')),
                         list(range(1, DECISION_COUNT + 1)),
                         'a decision lost its number, so the record cannot name it')
        for decision in DECISION_LEADS:
            with self.subTest(decision=decision[:40]):
                self.assertIn(decision, text, 'a decision was reworded or removed')
        for option in OPTION_LABELS:
            with self.subTest(option=option):
                self.assertIn(f'**{option}. ', text, 'an option lost its label')
        self.assertEqual(len(re.findall(r'(?m)^\| \*\*[A-H]\. ', text)), OPTION_COUNT,
                         'the option table stopped carrying one row per option')
        self.assertEqual(numbered(section(text, 'Required behavior before any condition is '
                                                 'wired to a person')),
                         list(range(1, REQUIRED_BEHAVIOR_COUNT + 1)),
                         'the required-behavior list moved')
        self.assertEqual(len(re.findall(r'(?m)^- ', section(text, 'Verification before any '
                                                                  'enablement'))),
                         VERIFICATION_COUNT, 'the verification list moved')

    def test_the_plan_is_an_unowned_proposal_that_implements_nothing(self):
        plan = flat(read(PLAN))
        for phrase in PROPOSAL_PHRASES:
            with self.subTest(phrase=phrase[:40]):
                self.assertIn(phrase, plan, 'the plan stopped saying it is an unowned proposal')
        record = read(ADR)
        # The red-check table has to name what it caught, so the record is read without it.
        outside_red_checks = flat(record.partition('## Red checks')[0]
                                  + record.partition('## Red checks')[2].partition('## ')[0]
                                  + record.partition('## Consequences')[2])
        for text, name in ((plan, 'the plan'), (outside_red_checks, 'the record')):
            for phrase in FORBIDDEN_SELECTION:
                with self.subTest(document=name, phrase=phrase):
                    self.assertNotIn(phrase, text, f'{name} chose an option instead of pricing it')
        self.assertIn('**Nothing is implemented.**', flat(record),
                      'the record stopped quoting the claim it holds the plan to')
        for phrase in ('Approved by', 'approved by', 'Decision owner', 'Owner:'):
            for document in (PLAN, ADR):
                with self.subTest(document=document.name, phrase=phrase):
                    self.assertNotIn(phrase, read(document), 'an owner or an approval appeared')

    def test_the_plan_quotes_the_requirements_it_is_priced_against(self):
        plan = flat(read(PLAN))
        self.assertEqual(len(QUOTED_REQUIREMENTS), 31,
                         'the quotation list moved without the record saying so')
        for path, phrase in QUOTED_REQUIREMENTS:
            with self.subTest(document=path.name, phrase=phrase[:40]):
                self.assertIn(phrase, flat(read(path)),
                              'a requirement the plan is priced against was reworded in its source')
                self.assertIn(phrase, plan,
                              'the plan stopped quoting a requirement it is priced against')
        self.assertIn('thirty-one quotes', flat(read(ADR)),
                      'the record states a quotation count that is not the list this suite holds')

    def test_the_plan_states_the_measured_numbers(self):
        plan = flat(read(PLAN))
        for number in MEASURED:
            with self.subTest(number=number[:40]):
                self.assertIn(flat(number), plan, 'a measured number was reworded or removed')

    def test_the_plan_names_the_documents_records_and_suites_it_depends_on(self):
        plan = read(PLAN)
        for name in PLAN_DEPENDENCIES:
            with self.subTest(name=name):
                self.assertIn(name, plan, 'the plan stopped naming something it depends on')
        targets = [target.rsplit('/', 1)[-1]
                   for target in re.findall(r'\[[^\]]*\]\(([^)\s]+)\)', plan)]
        self.assertEqual(len(targets), PLAN_LINK_COUNT,
                         'a link in the plan was added or removed')
        for name in LINKED_DEPENDENCIES:
            with self.subTest(dependency=name):
                self.assertIn(name, targets,
                              'a dependency the plan links stopped being a link, which is how a '
                              'document leaves the graph without being deleted')

    def test_the_plan_wraps_to_the_house_width(self):
        for path in (PLAN, ADR):
            for number, line in enumerate(read(path).splitlines(), 1):
                if line.startswith('|'):
                    continue
                with self.subTest(document=path.name, line=number):
                    self.assertLessEqual(len(line), 100,
                                         'a prose line is wider than the house wrap')

    def test_the_plan_prices_the_audit_table_as_the_database_lanes_request(self):
        """The lane boundary: quote ADR 0227's cost, and write no migration."""
        plan = flat(read(PLAN))
        for phrase in ('This is a schema change', "the lead's database lane",
                       'No migration is written here and no model is proposed here.',
                       'this plan writes no migration, proposes no model and adds no setting'):
            with self.subTest(phrase=phrase[:40]):
                self.assertIn(phrase, plan, 'the plan stopped routing the schema change to its lane')
        self.assertIn('0236-database-connection-plan.md', read(PLAN),
                      'the plan stopped naming the record that carries the database lane')
        self.assertEqual(list((ROOT / 'daroobank').glob('migrations')), [],
                         'a migrations package appeared in `daroobank`')
        for app in sorted(PROJECT_APPS):
            migrations = sorted((ROOT / app / 'migrations').glob('[0-9]*.py'))
            self.assertNotIn('read_audit', ' '.join(path.name for path in migrations).lower(),
                             'a read-audit migration was written, which this plan must not do')


class RecordShapeTests(SimpleTestCase):
    def test_the_record_has_the_sections_a_decision_record_needs(self):
        record = read(ADR)
        for heading in RECORD_SECTIONS:
            with self.subTest(section=heading):
                self.assertIn(heading, record, 'a section every record in this tree has is missing')
        positions = [record.index(heading) for heading in RECORD_SECTIONS]
        self.assertEqual(positions, sorted(positions), 'the record sections were reordered')
        self.assertRegex(record, r'(?m)^Date: 20\d\d-\d\d-\d\d$', 'the record has no date line')
        self.assertRegex(record, r'(?m)^Status: ', 'the record has no status line')
        self.assertRegex(record, r'(?m)^Suite: `daroobank/test_monitoring_response_plan\.py`',
                         'the record does not name the suite that pins it')

    def test_the_record_index_names_the_record_in_number_order(self):
        index = read(ADR_INDEX)
        self.assertIn('0237-monitoring-response-plan.md', index,
                      'the index stopped linking the record')
        self.assertRegex(index, r'\[0237: ', 'the index bullet is not in the house form')
        self.assertLess(index.index('0236-database-connection-plan.md'),
                        index.index('0237-monitoring-response-plan.md'),
                        'the index is out of number order')
        numbers = [int(match) for match in re.findall(r'^- \[(\d{4}):', index, re.M)]
        self.assertEqual(numbers, sorted(set(numbers)), 'the index is not contiguous and increasing')
        self.assertEqual(len(numbers), len(set(numbers)), 'a record number is used twice')
        files = sorted(int(path.name[:4]) for path in ADR.parent.glob('[0-9][0-9][0-9][0-9]-*.md'))
        self.assertEqual(files, list(range(files[0], files[-1] + 1)),
                         'the record numbers on disk are not contiguous')
        self.assertEqual(files, numbers, 'the index and the directory disagree')

    def test_the_changelog_entry_is_newest_first_and_names_the_plan(self):
        text = read(CHANGELOG)
        entries = re.findall(r'(?m)^## (\d{4}-\d{2}-\d{2}) — (.+)$', text)
        self.assertEqual([date for date, _ in entries],
                         sorted((date for date, _ in entries), reverse=True),
                         'the changelog is not newest-first')
        # A later delivery puts its own entry above this one, so the entry that records this plan is
        # found by what it names rather than by being first; newest-first is asserted above and is
        # owned for the whole file by daroobank/test_release_notes_structure.py.
        bodies = [text.split(f'## {date} — {title}', 1)[1].split('\n## ', 1)[0]
                  for date, title in entries]
        own = [body for body in bodies if 'MONITORING_RESPONSE_PLAN.md' in body]
        self.assertEqual(len(own), 1,
                         'the changelog entry that records this plan is missing or duplicated')
        first_body = own[0]
        self.assertIn('MONITORING_RESPONSE_PLAN.md', first_body,
                      'the entry that records this plan does not name it')
        self.assertIn('0237-monitoring-response-plan.md', first_body,
                      'the entry that records this plan does not name the record')
        self.assertIn('**Changes:**', first_body, 'the entry has no changes paragraph')
        self.assertEqual(len(re.findall(r'\*\*Changes:\*\*', first_body)), 1,
                         'the entry has more than one body')

    def test_both_evidence_cells_of_the_monitoring_row_name_the_plan(self):
        area, evidence, gate = evidence_cells()
        self.assertEqual(area, EVIDENCE_ROW)
        self.assertIn('MONITORING_RESPONSE_PLAN.md', evidence,
                      'the development-evidence cell stopped naming the plan')
        self.assertIn('ADR 0237', evidence,
                      'the development-evidence cell stopped naming the record')
        self.assertIn('MONITORING_RESPONSE_PLAN.md', gate,
                      'the open-gate cell stopped naming the plan')
        self.assertIn('ADR 0237', gate, 'the open-gate cell stopped naming the record')
        # The gate's own sentences are quoted by other suites and by this plan, so they stay.
        for phrase in ('**Open:** private access restrictions, network/request deadlines, monitoring, '
                       'alert routing, on-call ownership and incident response.',
                       'No component records that a read happened'):
            with self.subTest(phrase=phrase[:40]):
                self.assertIn(phrase, gate, 'a gate sentence this plan quotes was rewritten')
        for phrase in ('What is not monitored is measured too',
                       'so any request history has to come from the proxy, the database or the host'):
            with self.subTest(phrase=phrase[:40]):
                self.assertIn(phrase, evidence, 'an evidence sentence this plan quotes was rewritten')

    def test_each_neighbour_document_names_the_plan(self):
        for path in NEIGHBOURS:
            text = read(path)
            with self.subTest(document=path.name):
                self.assertIn('MONITORING_RESPONSE_PLAN.md', text,
                              'a neighbour stopped linking the plan')
                self.assertIn('0237-monitoring-response-plan.md', text,
                              'a neighbour stopped linking the record')

    def test_the_plan_is_linked_from_a_document_it_does_not_own(self):
        """Reachable from the documents a reader actually arrives from, and not orphaned.

        The repository README is a documentation index and links no plan in this family, so it is
        deliberately not required here; `daroobank/test_document_links.py` is the suite that fails on
        an unreachable document, and this one fails on a plan that only its own record links.
        """
        own = {path.resolve() for path in OWN_FILES}
        linking = sorted(path.name for path in documents()
                         if path.resolve() not in own
                         and 'MONITORING_RESPONSE_PLAN.md' in read(path))
        self.assertGreaterEqual(len(linking), 5,
                                'the plan is close to orphaned; only %s link it' % linking)
        for name in ('CHANGELOG.md', 'PHASE1_RELEASE_EVIDENCE.md', 'DEPLOYMENT.md',
                     'OPERATIONS_RUNBOOK.md', 'SECURITY.md'):
            with self.subTest(document=name):
                self.assertIn(name, linking, f'{name} stopped linking the plan')


class AbsenceOfLoggingTests(SimpleTestCase):
    def test_the_logging_configuration_is_empty_and_nobody_is_addressed(self):
        self.assertEqual(settings.LOGGING, {}, 'a logging configuration appeared')
        self.assertEqual(settings.LOGGING_CONFIG, 'logging.config.dictConfig',
                         'the logging configurator changed')
        self.assertEqual(settings.ADMINS, [], 'an administrator appeared, so AdminEmailHandler '
                                              'would have a recipient')
        self.assertEqual(list(getattr(settings, 'MANAGERS', [])), [],
                         'a manager appeared')
        plan = flat(read(PLAN))
        self.assertIn('`settings.ADMINS` and `settings.MANAGERS` are both `[]`', plan)

    def test_the_loggers_have_the_handlers_django_gives_them_by_default(self):
        configured = logging.Logger.manager.loggerDict
        for name, expected in LOGGER_HANDLERS.items():
            with self.subTest(logger=name):
                # Asserted before `getLogger`, which would create the logger it is asked for and so
                # turn an absent logger into an empty one.
                self.assertIn(name, configured, f'the {name} logger is not configured at all')
                logger = logging.getLogger(name)
                self.assertEqual(sorted(type(handler).__name__ for handler in logger.handlers),
                                 sorted(expected),
                                 f'the {name} logger grew or lost a handler')
        for name, level in LOGGER_LEVELS.items():
            with self.subTest(logger=name):
                self.assertEqual(logging.getLogger(name).level, level,
                                 f'the {name} logger level moved')
        root = logging.getLogger()
        self.assertEqual(root.handlers, [], 'the root logger grew a handler')
        self.assertEqual(root.level, logging.WARNING, 'the root logger level moved')
        self.assertTrue(any(type(handler).__name__ == 'AdminEmailHandler'
                            for handler in logging.getLogger('django').handlers),
                        'the one handler that could tell a human something is gone')

    def test_no_project_module_imports_logging_or_calls_an_emitter(self):
        modules = project_modules()
        self.assertEqual(len(modules), PROJECT_MODULE_COUNT,
                         'the non-test module count the plan quotes moved')
        emitters = re.compile(r'\.(warning|error|exception|critical|info|debug)\(|logger\.|logging\.')
        importing, calling = [], []
        for relative, path in modules:
            text = read(path)
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import) and any(a.name == 'logging' for a in node.names):
                    importing.append(relative)
                if isinstance(node, ast.ImportFrom) and node.module == 'logging':
                    importing.append(relative)
            if emitters.search(text):
                calling.append(relative)
        self.assertEqual(sorted(set(importing)), [], 'a module imported `logging`')
        self.assertEqual(sorted(set(calling)), [], 'a module gained an emitter call site')
        # A positive control: the same scan must find an import that does exist, so that a scan
        # which silently finds nothing cannot pass for an absence.
        control = [relative for relative, path in modules
                   if any(isinstance(node, ast.Import)
                          and any(alias.name == 'json' for alias in node.names)
                          for node in ast.walk(ast.parse(read(path))))]
        self.assertGreater(len(control), 0, 'the scan finds nothing at all, so it proves nothing')

    def test_no_middleware_records_a_request(self):
        middleware = list(settings.MIDDLEWARE)
        self.assertEqual(len(middleware), MIDDLEWARE_COUNT, 'the middleware list moved')
        project = [name for name in middleware if name.startswith('daroobank.middleware.')]
        self.assertEqual(len(project), PROJECT_MIDDLEWARE_COUNT,
                         'the project middleware count moved')
        recording = [name for name in middleware
                     if re.search(r'log|audit|record|monitor|metric|telemetry', name, re.I)]
        self.assertEqual(recording, [], 'a middleware with a record-like name appeared')
        text = read(ROOT / 'daroobank' / 'middleware.py')
        self.assertNotIn('import logging', text, 'the middleware module imported `logging`')
        self.assertNotIn('getLogger', text, 'the middleware module took a logger')

    def test_the_route_inventory_the_sweeps_walk(self):
        targets = route_targets()
        names = [name for _pattern, name in targets if name]
        self.assertEqual(len(targets), ROUTE_COUNT, 'the route count the plan quotes moved')
        self.assertEqual(len([name for name in names if name.startswith('staff_')]),
                         STAFF_ROUTE_COUNT, 'the staff route count moved')
        self.assertEqual(len([name for name in names if name.startswith('health_')]),
                         HEALTH_ROUTE_COUNT, 'the health route count moved')
        self.assertEqual(len([name for name in names if name.startswith(('search_api',
                                                                        'openapi_document',
                                                                        'presentation_api'))]),
                         API_ROUTE_COUNT, 'the api route count moved')
        rest = len(names) - STAFF_ROUTE_COUNT - HEALTH_ROUTE_COUNT - API_ROUTE_COUNT
        self.assertEqual(rest, PUBLIC_ROUTE_COUNT, 'the public route count moved')
        self.assertEqual(len(read(URLS).splitlines()), URLS_LINES, '`urls.py` moved')


class InstrumentShapeTests(SimpleTestCase):
    def test_the_probes_are_the_two_routes_health_py_defines(self):
        text = read(HEALTH)
        self.assertEqual(len(text.splitlines()), HEALTH_LINES, '`health.py` moved')
        self.assertEqual(re.findall(r'(?m)^def ([a-z_]+)', text), HEALTH_DEFINITIONS,
                         'the probe definitions moved')
        self.assertIn("SET LOCAL statement_timeout", text,
                      'the readiness probe stopped bounding its own statement')
        self.assertIn('in_atomic_block', text,
                      'the condition that makes the probe answer 503 inside a transaction is gone')

    def test_the_readiness_command_reads_settings_and_never_the_environment(self):
        text = read(READINESS)
        self.assertEqual(len(text.splitlines()), READINESS_LINES, 'the command moved')
        self.assertEqual(text.count('os.environ'), 0,
                         'the command started reading the environment directly')
        tree = ast.parse(text)
        attributes = {node.attr for node in ast.walk(tree)
                      if isinstance(node, ast.Attribute)
                      and isinstance(node.value, ast.Name) and node.value.id == 'settings'}
        literals = {node.value for node in ast.walk(tree)
                    if isinstance(node, ast.Constant) and isinstance(node.value, str)
                    and re.fullmatch(r'[A-Z][A-Z0-9_]{3,}', node.value)}
        self.assertEqual(sorted(attributes | literals), REPORT_SETTINGS,
                         'the settings the report reads moved')
        self.assertEqual(len(attributes | literals), 16, 'the report reads a different number')
        self.assertNotIn('DATABASES', attributes | literals,
                         'the report started reading the database configuration')
        identifiers = re.findall(r"'id': '([a-z_]+)'", text)
        self.assertEqual(sorted(set(identifiers)), sorted(REVIEW_IDS),
                         'the review identifiers moved')
        self.assertEqual(len(REQUIRED_CHECKS), 10)
        for name in REQUIRED_CHECKS:
            with self.subTest(check=name):
                self.assertIn(f'def {name}()', text, 'a required check is gone from the source')
        # Read from the module, not from its source text: `SCOPE` is written as two adjacent string
        # literals, so the file's flattened text carries a quote mark between the two halves and a
        # phrase match against the source would fail on a line that is in fact correct.
        from daroobank.management.commands.check_deployment_readiness import SCOPE
        self.assertEqual(SCOPE, REPORT_SCOPE, 'the scope line the plan quotes was reworded')
        self.assertIn(REPORT_SCOPE, flat(read(PLAN)), 'the plan stopped quoting the scope line')

    def test_the_environment_names_none_of_which_configures_a_sink(self):
        text = read(SETTINGS)
        reads = re.findall(r"""os\.environ(?:\.get\(|\[)\s*['"]([A-Z][A-Z0-9_]+)['"]""", text)
        self.assertEqual(len(reads), ENVIRONMENT_READS,
                         'settings.py grew an environment read')
        self.assertEqual(len(set(reads)), ENVIRONMENT_LITERALS,
                         'the distinct literal environment names moved')
        helper = sorted(set(re.findall(r"required_database_setting\('([A-Z_]+)'\)", text)))
        self.assertEqual(helper, ENVIRONMENT_VIA_HELPER,
                         'the names reached through the helper moved')
        self.assertEqual(len(set(reads) | set(helper)), ENVIRONMENT_NAMES,
                         'the sixteen names the evidence cell counts moved')
        # Matched on whole underscore-separated words: a substring scan calls
        # `DAROOBANK_STAFF_LOGIN_THROTTLE` a logging variable because `LOGIN` contains `LOG`.
        sinks = [name for name in set(reads) | set(helper)
                 if re.search(r'(?:^|_)(LOG|LOGGING|HANDLER|LEVEL|ALERT|ALERTING|METRIC|METRICS|'
                              r'MONITOR|MONITORING|TELEMETRY|TRACE|TRACING|ADMIN|SYSLOG|SENTRY)'
                              r'(?:$|_)', name)]
        self.assertEqual(sinks, [], 'an environment name that configures a sink appeared')


class DeploymentSurfaceTests(SimpleTestCase):
    def test_the_deployed_command_is_the_development_server(self):
        text = read(DOCKERFILE)
        self.assertIn(DOCKERFILE_COMMAND, text,
                      'the container command moved, which changes what the plan says is deployed')
        self.assertIn('runserver', text, 'the deployed command stopped being the dev server')
        self.assertNotIn('gunicorn', text, 'a production server appeared')
        self.assertNotIn('uwsgi', text, 'a production server appeared')

    def test_compose_gives_the_database_a_healthcheck_and_the_application_none(self):
        text = read(COMPOSE)
        lines = text.splitlines()
        self.assertEqual(len(lines), COMPOSE_LINES, '`compose.yaml` moved')
        services = re.findall(r'(?m)^  ([a-z][\w-]*):', text)
        self.assertEqual(services[:2], COMPOSE_SERVICES, 'the services moved')
        self.assertEqual(text.count('healthcheck:'), COMPOSE_HEALTHCHECKS,
                         'a healthcheck appeared or disappeared')
        web = text.split('  web:', 1)[1]
        self.assertNotIn('healthcheck:', web, 'the web service grew a healthcheck')
        self.assertEqual(len(re.findall(r'(?m)^\s+logging:', text)), 0,
                         'a log driver was configured, which nothing collects')
        self.assertEqual(len(re.findall(r'max-size|max-file', text)), 0,
                         'log rotation was configured')
        self.assertIn('DAROOBANK_HEALTH_PROBES_ENABLED: ${DAROOBANK_HEALTH_PROBES_ENABLED:-0}',
                      text, 'the probes stopped being off by default in the shipped stack')
        self.assertIn('curl', text + read(WORKFLOW), 'nothing polls anything any more')

    def test_ci_polls_the_home_page_and_neither_probe(self):
        text = read(WORKFLOW)
        self.assertEqual(len(text.splitlines()), WORKFLOW_LINES, 'the workflow moved')
        self.assertEqual(len(re.findall(r'curl -fsS http://127\.0\.0\.1:8000/', text)),
                         WORKFLOW_CURLS, 'the workflow changed what it polls')
        self.assertNotIn('/health/', text, 'CI started polling a probe')
        self.assertEqual(text.lower().count('runserver'), 0, 'the workflow named the dev server')
        for token in ('alert', 'monitor'):
            self.assertEqual(text.lower().count(token), 0,
                             f'the workflow gained a {token} step')

    def test_no_artifact_directory_dependency_or_vendor_exists(self):
        names = [path.name.lower() for path in tree_files()]
        for token in NAME_TOKENS:
            with self.subTest(token=token):
                self.assertEqual([name for name in names if token in name], [],
                                 f'a file named like a {token} artifact appeared')
        for directory in ABSENT_DIRECTORIES:
            with self.subTest(directory=directory):
                self.assertFalse((ROOT / directory).exists(),
                                 f'an operational directory `{directory}` appeared')
        for path in (COMPOSE, WORKFLOW, REQUIREMENTS_IN):
            body = read(path).lower()
            for token in CONFIG_TOKENS:
                with self.subTest(document=path.name, token=token):
                    self.assertEqual(body.count(token), 0,
                                     f'{path.name} named a collector or an alert sink')
        requirements = read(ROOT / 'requirements.in') + read(ROOT / 'requirements.txt')
        for token in CONFIG_TOKENS:
            with self.subTest(token=token):
                self.assertEqual(requirements.lower().count(token), 0,
                                 'a monitoring dependency appeared')

    def test_the_absence_is_counted_over_documents_that_report_it(self):
        texts = {path.as_posix(): flat(read(path)).lower() for path in corpus()}
        self.assertEqual(len(texts), CORPUS_COUNT,
                         'the document corpus the plan counts over moved')
        for token, count in DOC_TOKEN_COUNTS.items():
            with self.subTest(token=token):
                self.assertEqual(len([text for text in texts.values() if token in text]), count,
                                 f'the documents mentioning {token!r} moved')
        for token in ABSENT_TOKENS:
            with self.subTest(token=token):
                self.assertEqual([name for name, text in texts.items() if token in text], [],
                                 f'a document started naming {token!r}')

    def test_the_roles_the_runbook_escalates_to_are_defined_nowhere(self):
        texts = {path.as_posix(): flat(read(path)).lower() for path in corpus()}
        runbook = flat(read(RUNBOOK)).lower()
        for role in ROLE_TERMS:
            with self.subTest(role=role):
                self.assertIn(role, runbook,
                              'the runbook stopped naming a role it escalates to')
                self.assertEqual([name for name, text in texts.items() if role in text], [],
                                 f'a document outside the runbook started naming {role!r}, which is '
                                 f'where a definition would live')
        emails = set()
        for path in corpus():
            emails.update(re.findall(r'[\w.+-]+@[\w-]+\.[\w.]+', read(path)))
        self.assertEqual(sorted(emails), EMAIL_SHAPED,
                         'a contact appeared, or a placeholder was removed')
        for phrase in ('Escalate to data steward/source owner.',
                       'Define the on-call chain before enabling patient accounts.'):
            with self.subTest(phrase=phrase[:40]):
                self.assertIn(phrase, flat(read(RUNBOOK)),
                              'the runbook stopped escalating to a role')


class SharedPinTests(SimpleTestCase):
    def test_the_record_states_the_pin_deltas_it_causes(self):
        consequences = flat(section(read(ADR), 'Consequences'))
        for phrase in PIN_DELTAS:
            with self.subTest(phrase=phrase[:44]):
                self.assertIn(phrase, consequences,
                              'the record stopped stating a shared pin this delivery moves')
        markdown = len(list((ROOT / 'docs').rglob('*.md')))
        records = sorted(ADR_DIR.glob('[0-9][0-9][0-9][0-9]-*.md'))
        links = read(DOCUMENT_LINKS)
        targets = [target for document in documents() for target in all_links(read(document))]
        self.assertEqual(pin(links, 'DOCUMENT_COUNT'), markdown + 1,
                         'the document pin is not README plus docs/')
        self.assertEqual(pin(links, 'ADR_COUNT'), len(records),
                         'the record pin is not the directory it indexes')
        self.assertEqual(pin(links, 'SUITE_LINE_COUNT'),
                         len([record for record in records
                              if re.search(r'(?m)^Suite:', read(record))]),
                         'the `Suite:` pin is not the number of records that name one')
        self.assertEqual(pin(links, 'LINK_COUNT'), len(targets),
                         'the link pin is not the links the documents contain')
        self.assertEqual(pin(links, 'EXTERNAL_COUNT'),
                         len([t for t in targets if t.startswith(EXTERNAL_PREFIXES)]),
                         'the external-link pin is not the external links the documents contain')
        self.assertEqual(pin(links, 'ANCHOR_COUNT'), len([t for t in targets if '#' in t]),
                         'the anchor pin is not the links that point into a heading')
        self.assertEqual(pin(read(MIGRATION_SUITE), 'DOCS_MARKDOWN_COUNT'), markdown,
                         'the migration suite\'s markdown pin is not docs/')
        self.assertEqual(pin(read(BACKUP_SUITE), 'DOCS_MARKDOWN_COUNT'), markdown,
                         'the backup suite\'s markdown pin is not docs/')
        migration_modules = pin(read(MIGRATION_SUITE), 'TEST_MODULE_COUNT')
        for suite in (MFA_SUITE, SECRET_SUITE):
            with self.subTest(suite=suite.name):
                self.assertEqual(pin(read(suite), 'TEST_MODULE_COUNT'), migration_modules - 1,
                                 'the two older suites\' module pins are not the tree minus one')
        self.assertEqual(pin(read(CONNECTION_SUITE), 'CORPUS_COUNT'), markdown - 11,
                         'the connection corpus is not docs/ minus the eleven documents it edits')
        self.assertEqual(CORPUS_COUNT, markdown + 1 - len(ITEM_DOCS),
                         'this corpus is not the documents minus the nine this delivery edits')
        self.assertIn('LOGIN_ROUTE_TESTS = 47', read(MFA_SUITE),
                      'the login-route pin moved again, and not by the record that recounts it here')

    def test_the_record_carries_the_red_checks_it_names(self):
        red = section(read(ADR), 'Red checks')
        self.assertIn('thirty-nine mutations', flat(red),
                      'the record states a red-check count that is not the list it carries')
        self.assertEqual(len(numbered(red)), RED_CHECK_COUNT,
                         'the red-check list the record names moved')
        for phrase in ('`sha256sum -c` returned rc=0 after every restore',
                       'the suite was green at both ends', 'Every mutation went red'):
            with self.subTest(phrase=phrase[:44]):
                self.assertIn(phrase, flat(red),
                              'the red checks stopped saying how the tree was held identical and '
                              'that the suite was green before the first mutation and after the '
                              'last restore')


class LiveInstrumentTests(TransactionTestCase):
    """Live, because a probe answered from a fixture proves nothing about the code that answers it.

    A `TransactionTestCase` rather than a `TestCase` on purpose: `database_ready()` answers False
    inside an atomic block, so an ordinary `TestCase` would measure its own wrapper. Both readings are
    taken below, which is the measurement the plan quotes.
    """

    def test_the_probes_answer_three_bytes_and_503_inside_a_transaction(self):
        client = Client()
        for path in ('/health/live/', '/health/ready/'):
            with self.subTest(probe=path, enabled=False):
                response = client.get(path)
                self.assertEqual(response.status_code, 404,
                                 'a probe answered while it is disabled')
                self.assertEqual(response.content, b'', 'a disabled probe has a body')
        with override_settings(HEALTH_PROBES_ENABLED=True):
            answers = {}
            for path in ('/health/live/', '/health/ready/'):
                with self.subTest(probe=path, enabled=True):
                    response = client.get(path)
                    answers[path] = response.content
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.content, b'ok\n', 'the probe body moved')
                    self.assertEqual(response['Content-Type'], 'text/plain; charset=utf-8')
                    self.assertEqual(response['Cache-Control'], 'no-store')
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                head = client.head(path)
                self.assertEqual(head.status_code, 200)
                self.assertEqual(head.content, b'', 'a HEAD answer has a body')
            self.assertEqual(answers['/health/live/'], answers['/health/ready/'],
                             'the two probes became distinguishable by their bodies')
            for method in ('post', 'put', 'delete'):
                with self.subTest(method=method):
                    response = getattr(client, method)('/health/ready/')
                    self.assertEqual(response.status_code, 405)
                    self.assertEqual(response['Allow'], 'GET, HEAD')
            outside = client.get('/health/ready/')
            self.assertEqual(outside.status_code, 200,
                             'readiness failed outside a transaction')
            self.assertFalse(connection.in_atomic_block)
            with transaction.atomic(using='default'):
                inside = client.get('/health/ready/')
                self.assertEqual(inside.status_code, 503,
                                 'the probe stopped answering 503 inside a transaction, so the trap '
                                 'the plan documents is no longer reproducible')
                self.assertTrue(connection.in_atomic_block)

    def test_the_report_answers_not_ready_with_a_conditional_review_list(self):
        from io import StringIO
        out = StringIO()
        with self.assertRaises(SystemExit) as raised:
            call_command('check_deployment_readiness', stdout=out, stderr=out)
        self.assertEqual(raised.exception.code, 1, 'the report stopped failing on this configuration')
        import json
        report = json.loads(out.getvalue())
        self.assertEqual(sorted(report), ['failed', 'ready', 'required', 'review', 'scope'],
                         'the report keys moved')
        self.assertIs(report['ready'], False)
        required = report['required']
        self.assertEqual(sorted(item['id'] for item in required), sorted(REQUIRED_CHECKS),
                         'the required checks moved')
        self.assertEqual(len(required), 10)
        passed = sorted(item['id'] for item in required if item['passed'])
        failed = sorted(report['failed'])
        self.assertEqual(passed, PASSED_IN_A_TEST_PROCESS,
                         'the checks that pass in a test process moved')
        self.assertEqual(failed, FAILED_IN_A_TEST_PROCESS,
                         'the checks that fail in a test process moved')
        self.assertEqual(sorted(passed + failed), sorted(REQUIRED_CHECKS),
                         'a required check is neither passed nor failed')
        self.assertIn('database_reachable', passed,
                      'the database was not reachable from the report')
        for item in required:
            with self.subTest(check=item['id']):
                self.assertEqual(sorted(item), ['detail', 'id', 'passed'],
                                 'a required check changed shape')
        self.assertEqual(report['scope'], REPORT_SCOPE, 'the scope line was reworded')
        for item in report['review']:
            identifier = item['id'] if isinstance(item, dict) else item
            with self.subTest(review=identifier):
                self.assertIn(identifier, REVIEW_IDS,
                              'the report raised a review item its source does not define')
        self.assertNotIn(settings.SECRET_KEY, out.getvalue(),
                         'the report printed the secret it checks the shape of')


class RequestFootprintTests(TransactionTestCase):
    def test_two_sweeps_of_all_55_routes_move_nothing_and_record_only_failures(self):
        client = Client()
        targets = route_targets()
        self.assertEqual(len(targets), ROUTE_COUNT, 'the sweep no longer walks every route')
        files_before = tree_snapshot()
        results = {}
        for label, authenticate in (('anonymous', False), ('authenticated', True)):
            capture = Capture()
            root = logging.getLogger()
            previous_handlers = list(root.handlers)
            previous_level = root.level
            root.handlers = [capture]
            root.setLevel(0)
            if authenticate:
                user = get_user_model().objects.create_superuser(
                    username='probe_monitoring', email='probe@example.invalid',
                    password='probe-password-not-used-again')
                client.force_login(user)
            tables_before, rows_before = row_counts()
            started = time.perf_counter()
            statuses, reached = {}, 0
            for pattern, name in targets:
                if not name:
                    continue
                response = client.get(url_for(pattern, name))
                statuses[response.status_code] = statuses.get(response.status_code, 0) + 1
                reached += 1
            elapsed = (time.perf_counter() - started) * 1000
            tables_after, rows_after = row_counts()
            root.handlers = previous_handlers
            root.setLevel(previous_level)
            if authenticate:
                get_user_model().objects.filter(username='probe_monitoring').delete()
                client.logout()
            moved = sorted(table for table in tables_after
                           if rows_before.get(table) != rows_after.get(table))
            results[label] = {
                'reached': reached, 'statuses': statuses, 'elapsed': elapsed,
                'tables': len(tables_after), 'moved': moved,
                'records': [(record.name, record.levelname) for record in capture.records],
            }
        files_after = tree_snapshot()
        changed = sorted(set(files_before) ^ set(files_after)) + sorted(
            key for key in set(files_before) & set(files_after)
            if files_before[key] != files_after[key])

        anonymous = results['anonymous']
        authenticated = results['authenticated']
        for label, result in results.items():
            with self.subTest(sweep=label):
                self.assertEqual(result['reached'], ROUTE_COUNT,
                                 'the sweep did not reach every route')
                self.assertEqual(result['tables'], SWEEP_TABLES,
                                 'the table count the plan quotes moved')
                self.assertEqual(result['moved'], [],
                                 'a read moved rows, which is what a read audit would record')
                self.assertEqual(set(level for _name, level in result['records']), {'WARNING'},
                                 'a record was emitted at a level the plan does not quote')
                self.assertEqual(set(name for name, _level in result['records']),
                                 {'django.request'},
                                 'a logger other than django.request emitted a record')
        self.assertEqual(anonymous['statuses'], ANONYMOUS_STATUSES,
                         'the anonymous sweep answers differently')
        self.assertEqual(authenticated['statuses'], AUTHENTICATED_STATUSES,
                         'the authenticated sweep answers differently')
        self.assertEqual(len(anonymous['records']), ANONYMOUS_RECORDS,
                         'the anonymous sweep emitted a different number of records')
        self.assertEqual(len(authenticated['records']), AUTHENTICATED_RECORDS,
                         'the authenticated sweep emitted a different number of records')
        # The point of the measurement: every record came from a failure, and no success made one.
        failures = authenticated['statuses'].get(404, 0) + authenticated['statuses'].get(405, 0)
        self.assertEqual(len(authenticated['records']), failures,
                         'a record no longer corresponds to a failed request')
        self.assertEqual(authenticated['statuses'][200], 27,
                         'the number of successful authenticated reads moved')
        self.assertLess(ANONYMOUS_RECORDS, AUTHENTICATED_RECORDS,
                        'the plan compares the two sweeps in a way the numbers do not support')
        self.assertEqual(changed, [], 'a request created or modified a file in the tree')
