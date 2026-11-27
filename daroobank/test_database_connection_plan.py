"""The database connection plan is a proposal, its numbers are measured, and nothing is implemented.

`docs/DATABASE_CONNECTION_PLAN.md` exists because `docs/PHASE1_RELEASE_EVIDENCE.md` carries *"no
representative volume, connection pool, vacuum or checkpoint pressure and no real workload was
measured"* and *"a standby cannot be measured here because this environment has no replica"* in the
open cell of its data-model row, while `docs/DEPLOYMENT.md` documents one connection variable and one
connection option and `docs/OPERATIONS_RUNBOOK.md` records that the readiness report *"checks nothing
about collected static files, logging, clocks, connection pooling, replicas or external
dependencies"*. The repository had no measurement of how many connections a request opens, what one
costs, how far a process gets before the server refuses it, what bounds a statement or a lock wait
when the module that runs it did not bound one, which privileges the role at the other end of every
connection holds, or whether a base backup of this cluster works at all. This suite holds the plan to
four properties.

It has to stay a proposal: nothing may be implemented while it claims nothing is. It has to cite the
requirements it is written against, so the plan cannot drift away from the deployment table, the
environment template, the security document, the readiness record or the settings comments. Its
numbers have to be the measured ones — the connection lifecycle at two lifetimes, the four
`connect_timeout` outcomes, the three unbounded waits, the two ceilings and their refusals, the
per-backend memory, the privilege boundary, the bloat table, the two query plans, the WAL volumes and
the base backup — and the tree itself has to keep matching them: the settings shape, the `SET LOCAL`
inventory, the absence of any pooler, the compose and template shape, and four facts read from the
database catalog are re-measured here rather than trusted from the document. And the neighbour
documents and the evidence row have to link the plan and its record.

What is not checked is whether the eight decisions should be answered the way any particular reader
would answer them, whether a pooler, a lifetime above zero or a second role would behave in a
deployment as these single-process sweeps suggest, or who may approve a capacity. Those are decisions
for named owners, and no test can make them.
"""
import ast
import re
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management import get_commands
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'DATABASE_CONNECTION_PLAN.md'
ADR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0235-database-connection-plan.md'
ADR_INDEX = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / 'README.md'
EVIDENCE = ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
RUNBOOK = ROOT / 'docs' / 'OPERATIONS_RUNBOOK.md'
SECURITY = ROOT / 'docs' / 'SECURITY.md'
TESTING = ROOT / 'docs' / 'TESTING_STRATEGY.md'
GUIDE = ROOT / 'docs' / 'DEVELOPMENT_GUIDE.md'
SCHEMA_DOC = ROOT / 'docs' / 'DATABASE_SCHEMA.md'
CHANGELOG = ROOT / 'docs' / 'CHANGELOG.md'
MIGRATION_PLAN = ROOT / 'docs' / 'DATABASE_MIGRATION_PLAN.md'
BACKUP_PLAN = ROOT / 'docs' / 'BACKUP_RECOVERY_PLAN.md'
ADR_0217 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0217-deployment-readiness-report.md'
ADR_0222 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0222-documented-environment.md'
ADR_0233 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0233-database-migration-plan.md'
SETTINGS = ROOT / 'daroobank' / 'settings.py'
COMPOSE = ROOT / 'compose.yaml'
ENV_TEMPLATE = ROOT / '.env.example'
REQUIREMENTS_IN = ROOT / 'requirements.in'
REQUIREMENTS = ROOT / 'requirements.txt'
REQUIREMENTS_BUILD = ROOT / 'requirements-build.txt'
DOCUMENT_LINKS = ROOT / 'daroobank' / 'test_document_links.py'
MIGRATION_SUITE = ROOT / 'daroobank' / 'test_database_migration_plan.py'
MFA_SUITE = ROOT / 'daroobank' / 'test_mfa_implementation_plan.py'
SECRET_SUITE = ROOT / 'daroobank' / 'test_secret_rotation_plan.py'
BACKUP_SUITE = ROOT / 'daroobank' / 'test_backup_recovery_plan.py'

SKIP_PARTS = ('.venv', '.cache', '.git', 'node_modules', '__pycache__', 'staticfiles')
PROJECT_APPS = ('catalog', 'clinical', 'daroobank', 'ingestion', 'pricing', 'sources',
                'staff_security')
# This delivery's own files. A document that reports the absence of a word cannot be one of the
# documents searched for it, and a suite that names a pooler in order to forbid it cannot be one of
# the files scanned for poolers.
OWN_FILES = (PLAN, ADR, Path(__file__).resolve())
# The eleven documents this delivery writes or edits, excluded from the document corpus the plan
# counts over.
ITEM_DOCS = (PLAN, ADR, ADR_INDEX, CHANGELOG, EVIDENCE, DEPLOYMENT, RUNBOOK, SECURITY, TESTING,
             GUIDE, SCHEMA_DOC)

SECTIONS = ['What is true today, measured',
            'Candidate approach and decisions required',
            'Options and what each costs',
            'Required behavior before any production connection',
            'Verification before any enablement']
SUBSECTIONS = ['The connection lifecycle per request',
               'The only bound on a connection, and what is left unbounded',
               'Timeouts: four modules bound themselves, the server bounds nothing',
               'The ceiling, and who is locked out at it',
               'One role, a superuser, and the boundary a runtime role would have',
               'Autovacuum, bloat and what a deletion leaves behind',
               'Plans: the index and the sequential scan',
               'WAL, checkpoints and the standby that does not exist',
               'What the repository already says about it']
DECISIONS = ['Which role connects, and who owns the schema?',
             'What is the connection lifetime, and what may a request pay for it?',
             'Where is the pool, if any, and which ceiling does it protect?',
             'What bounds a statement, a lock wait and an idle transaction, and at which layer?',
             'What bounds a connection that stops answering?',
             'Who may maintain the database, and how is a no-op distinguished from a success?',
             'What is the recovery objective, and does a standby or an archive exist?',
             'Which query plans may be sequential, and who decides an index is worth its write cost?']
OPTIONS = ['A. Leave the connection path as it is',
           'B. Write the connection and capacity numbers into documents only',
           'C. Pin the connection shape in a suite of its own',
           'D. Raise `POSTGRES_CONN_MAX_AGE` above 0',
           'E. Put a pooler in front',
           'F. Bound the session at the server, the role or the connection',
           'G. Move the application onto a least-privilege role',
           'H. Give the cluster an archive and a replica']
REQUIRED_BEHAVIOR_COUNT = 7
VERIFICATION_COUNT = 7
PROPOSAL_PHRASES = ['This document is a **proposal**', 'It has no owner and no approval',
                    '**Nothing is implemented.**', 'must not be read as a decision',
                    'no pooler was installed and removed',
                    'against databases and roles that no longer exist',
                    'No connection pool, no `CONN_MAX_AGE` change']
# Words that would make the plan choose rather than price: none may appear in it or in its record.
FORBIDDEN_SELECTION = ['The selected approach is to', 'is selected because',
                       'the recommended approach', 'should be adopted', 'The selected option is',
                       'we recommend', 'the best option is']
# The requirement each document states, quoted into the plan and pinned here, so the plan cannot
# drift away from the sentences it is written against.
QUOTED_REQUIREMENTS = [
    (DEPLOYMENT, 'integer seconds. Persistent connections need pooling, failover and idle-timeout '
                 'review before they are used in production'),
    (DEPLOYMENT, '`verify-full` for any connection that leaves the host, so the server certificate '
                 'is checked and the link is encrypted in transit; unset means the driver decides'),
    (ENV_TEMPLATE, 'Integer seconds, 0 through 31536000. Persistent connections need operational '
                   'review.'),
    (RUNBOOK, 'checks nothing about collected static files, logging, clocks, connection pooling, '
              'replicas or external dependencies'),
    (ADR_0217, 'Nothing verifies static files were collected, logging is routed, clocks are '
               'synchronized, connection pooling is sized, replicas are healthy, the process can '
               'actually serve a request, or that any external dependency is reachable.'),
    (ADR_0222, 'whether connections are persistent (`POSTGRES_CONN_MAX_AGE`) were documented only '
               'in a development template and a development guide, both of which say they are not '
               'production configuration.'),
    (SECURITY, 'least-privilege DB/worker credentials'),
    (GUIDE, 'provision a PostgreSQL database/role or start only the Compose `db` service'),
    (ADR_0233, 'with no readers, no connection pool, no vacuum, no replication and no checkpoint '
               'pressure'),
    (ADR_0233, "`db_options = {'connect_timeout': 5}` and nothing else"),
    (EVIDENCE, 'no migration connection carries a timeout (`db_options` is '
               "`{'connect_timeout': 5}`)"),
    (MIGRATION_PLAN, '`db_options` stays `{\'connect_timeout\': 5}`'),
    (EVIDENCE, 'no representative volume, connection pool, vacuum or checkpoint pressure and no '
               'real workload was measured'),
    (EVIDENCE, 'a standby cannot be measured here because this environment has no replica '
               '(`pg_is_in_recovery()` is false and both replication views are empty)'),
    (BACKUP_PLAN, 'is this the right archive, whose keys open it, and which database does it go '
                  'into?'),
    (TESTING, 'compares existing search with test-only GIN trigram and partial B-tree ordering '
              'indexes over 100,000 fictional records'),
    (TESTING, 'It requires `pg_trgm` to be available and creatable in an authorized disposable '
              'PostgreSQL cluster'),
    (SCHEMA_DOC, 'Use query plans and realistic data before adding indexes.'),
    (SCHEMA_DOC, 'Add FKs, constrained status transitions and transactional publication'),
    (SETTINGS, "A finite cap also prevents huge integers from overflowing Django's monotonic close "
               'deadline when a database connection is opened.'),
    (SETTINGS, "db_options = {'connect_timeout': 5}"),
    (SETTINGS, "os.environ.get('POSTGRES_CONN_MAX_AGE', '0')"),
    (SETTINGS, 'Invalid PostgreSQL port or connection lifetime'),
    (COMPOSE, 'POSTGRES_CONN_MAX_AGE: ${POSTGRES_CONN_MAX_AGE:-0}'),
]
# Every measured number the plan quotes, pinned as a substring of the flattened document so that a
# reworded or drifted figure fails here rather than in a reader's head.
MEASURED = [
    '20 for 20 requests', '1 for 20 requests', '82 ms', '34 ms', '4.10 ms', '1.68 ms',
    '2.42 ms per request', '0.0044 s', '59.9954 s', '59.9822 s', 'mean 1.88 ms, median 1.82 ms, min '
    '1.56 ms, max 2.55 ms', 'mean 1.84 ms, median 1.95 ms, min 1.39 ms, max 2.08 ms',
    'mean 2.22 ms, median 2.39 ms, min 1.72 ms, max 2.67 ms',
    'mean 2.12 ms, median 2.03 ms, min 1.84 ms, max 2.72 ms',
    'mean 0.11 ms, median 0.08 ms, min 0.06 ms, max 0.51 ms', 'opened **1** connection',
    'moved `pg_stat_database.sessions` by **1**', 'opened 0 new ones', '0..31,536,000',
    'Invalid PostgreSQL port or connection lifetime', '5,001.98 ms', '2,001.65 ms', '30,001.09 ms',
    '130,001.02 ms', 'tcp_syn_retries = 6', 'accepted 4 connections', '0.32 ms', '1.52 ms',
    '1.55 ms', '5.68 ms', 'tcp_keepalives_idle` 0 s', 'tcp_user_timeout` 0 ms',
    'tcp_keepalive_time` 7200 s', 'tcp_keepalive_intvl` 75 s', 'tcp_keepalive_probes` 9',
    '`SO_KEEPALIVE` read **0**', '127.0.0.1:5432` is refused', 'deadlock_timeout` at its 1,000 ms',
    '2,003 ms', '501 ms', "3.003)", '3,007 ms', '301 ms', '6.009', '4 granted locks',
    '7 `SET LOCAL` statements in 4 non-test modules', '`staff_security/read_limit.py`',
    '`staff_security/throttle.py`', '`daroobank/health.py`',
    'staff_security/management/commands/cleanup_staff_login_windows.py',
    '130 mentions of `lock_timeout`', '76 of `statement_timeout`', '61 `SET LOCAL`',
    '12 `set_config`', '6 `connect_timeout`', 'max_connections` is **100**',
    'superuser_reserved_connections` is **3**', '**97**', '**100**',
    'remaining connection slots are reserved for roles with the SUPERUSER attribute',
    'sorry, too many clients already', '1.92 ms', '1.01 ms', '16.90 ms', 'total 1,003,684 kB, mean '
    '10,347 kB, min 9,944 kB, max 10,632 kB', 'total 107,105 kB, mean 1,104 kB, min 1,087 kB, max '
    '1,107 kB', '**9.4 times**', '1.1 MB', '44 lines with 2 services and 15 environment '
    'assignments', 'exactly **one** non-system role', 'every one of the 33 tables in `public`',
    'grants exist to `PUBLIC`', 'all **360** rows of `pg_settings`', '`vector` extension',
    '**2** extensions are available', '`plpgsql` 1.0', 'SCRAM-SHA-256', 'read **340** of the '
    "server's settings", 'WARNING:  permission denied to vacuum "django_migrations", skipping it',
    'WARNING:  no privileges were granted for "django_migrations"', '**1,048,576** bytes',
    '`vacuum_count` stayed **0**', 'MigrationSchemaMissing: Unable to create the django_migrations '
    'table (permission denied for schema public)', 'all **32** migrations',
    'all **33** tables and all **111** indexes', '`pg_namespace` is per-database',
    'Got an error creating the test database: permission denied to create database',
    '(7 tests)', '**145,667** bytes', '<insufficient privilege>', 'pg_signal_backend',
    '9,312 kB', '9,320 kB', '4,664 kB', '**25 ms**', '**48 ms**', '400–440 ms', '13–14 ms',
    '**65 s**', '10,050 dead tuples', '`vacuum_threshold` 50 + `vacuum_scale_factor` 0.2 × 50,000',
    '**0** unindexed foreign keys', 'all **50** of them', 'Execution Time 2.666 ms',
    'shared hit=319', 'Rows Removed by Filter: 49990', 'wall 3.14 ms', 'Execution Time 0.068 ms',
    'shared hit=13 read=2', 'wall 0.48 ms', '**3.51 ms**', '**0.77 ms**', '**17–18 ms**',
    '**480 kB**', '39× on execution time', '4.6× for one cascading delete', '2,619,752 bytes',
    '176,896 bytes', '94,520 bytes', '46.6 % less', '296,928 → 200,328 → 182,776 bytes',
    '247,672 bytes with 14,393 records and 19 full-page images', '721,277 records, 15,665 '
    'full-page images, 140,870,044 bytes', 'wal_buffers_full` 2,280',
    '8 timed checkpoints against 14 requested ones', '7,173 buffers written during checkpoints, '
    '16,952 by backends and 20,744 allocated', '67,113,020 bytes', '126,007,951', '104,884,778',
    '151 commits, 0 rollbacks, 579 blocks read against 746,888 buffer hits',
    'pg_is_in_recovery()` is **false**', 'archive_mode` is **off**', '(disabled)',
    'max_wal_senders` 10', '1,214 ms', '8,058,024 bytes',
    '`backup_manifest`, `base.tar.gz` and `pg_wal.tar.gz`', '**257** documents in `docs/`',
    '**741** files of the tree', '`statement_timeout` is named in **5**', '`replica` in **9**',
    '`superuser` in **15**', '`VACUUM` in **3**', '`standby` in **3**', '`connect_timeout` in **3**',
    '`least privilege` in **2**', '`CONN_MAX_AGE` in **2**', 'in **1** each',
    '`max_connections`, `autovacuum`, `pooler` and `read replica` appear in **0** of them',
    '`requirements.in` is 4 lines, `requirements.txt` 94 and `requirements-build.txt` 9',
]
PLAN_DEPENDENCIES = ['ADR 0217', 'ADR 0222', 'ADR 0233', 'ADR 0235', 'BACKUP_RECOVERY_PLAN.md',
                     'SECRET_ROTATION_PLAN.md', 'docs/DATABASE_SCHEMA.md',
                     'docs/TESTING_STRATEGY.md', 'docs/SECURITY.md', 'docs/DEVELOPMENT_GUIDE.md',
                     'docs/OPERATIONS_RUNBOOK.md', 'docs/DEPLOYMENT.md',
                     'docs/PHASE1_RELEASE_EVIDENCE.md', 'daroobank/settings.py', 'compose.yaml',
                     '.env.example', 'requirements.txt', 'requirements.in',
                     'requirements-build.txt', 'daroobank/test_database_connection_plan.py',
                     'daroobank/isolated_test_runner.py', 'tools/wait_for_database.py',
                     'daroobank.wsgi.application']
# The document corpus the plan counts over: every markdown document in `docs/` that this delivery
# neither writes nor edits.
CORPUS_COUNT = 257
DOC_TOKEN_COUNTS = {'statement_timeout': 5, 'replica': 9, 'superuser': 15, 'VACUUM': 3,
                    'standby': 3, 'connect_timeout': 3, 'least privilege': 2, 'CONN_MAX_AGE': 2,
                    'POSTGRES_CONN_MAX_AGE': 1, 'pooling': 1}
ABSENT_DOC_TOKENS = ('max_connections', 'autovacuum', 'pooler', 'read replica')
ABSENT_TREE_TOKENS = ('pgbouncer', 'pgpool', 'psycopg_pool', 'HAProxy', 'pg_stat_statements')
TREE_FILE_COUNT = 741
PROJECT_MODULE_COUNT = 120
SET_LOCAL_MODULES = {'daroobank/health.py': 1,
                     'staff_security/management/commands/cleanup_staff_login_windows.py': 2,
                     'staff_security/read_limit.py': 2,
                     'staff_security/throttle.py': 2}
SET_LOCAL_TOTAL = 7
LOCK_TIMEOUT_COUNT = 3
STATEMENT_TIMEOUT_COUNT = 4
IDLE_TRANSACTION_COUNT = 0
TEST_TIMEOUT_MENTIONS = {'lock_timeout': 130, 'statement_timeout': 76, 'SET LOCAL': 61,
                         'set_config': 12, 'connect_timeout': 6}
REQUIREMENTS_LINES = {'requirements.in': 4, 'requirements.txt': 94, 'requirements-build.txt': 9}
COMPOSE_LINES = 44
COMPOSE_SERVICES = 2
COMPOSE_ENVIRONMENTS = 15
COMPOSE_RESOURCE_LIMITS = 0
COMPOSE_LOOPBACK_COUNT = 2
SETTINGS_ENVIRONMENT = ('DAROOBANK_ALLOWED_HOSTS', 'DAROOBANK_DEBUG',
                        'DAROOBANK_HEALTH_PROBES_ENABLED', 'DAROOBANK_HSTS_SECONDS',
                        'DAROOBANK_PUBLIC_READ_LIMIT', 'DAROOBANK_SECRET_KEY',
                        'DAROOBANK_STAFF_LOGIN_THROTTLE', 'DAROOBANK_TRUSTED_PROXY_CIDRS',
                        'DAROOBANK_TRUST_PROXY_SSL_HEADER', 'POSTGRES_CONN_MAX_AGE',
                        'POSTGRES_PASSWORD', 'POSTGRES_PORT', 'POSTGRES_SSLMODE')
SETTINGS_ENVIRONMENT_READS = 15
COMMAND_COUNT = 12
PROJECT_MODEL_COUNT = 24
DATABASE_ALIASES = ('default',)
FOREIGN_KEYS = 50
UNINDEXED_FOREIGN_KEYS = 0
EXTENSIONS_FORBIDDEN = ('pg_stat_statements', 'pgcrypto', 'pg_trgm', 'btree_gin', 'pg_buffercache')


def read(path):
    return path.read_text(encoding='utf-8')


def flat(text):
    """The document as one line, so a hard-wrapped phrase can be matched."""
    return ' '.join(text.split())


def flat_code(text):
    """A source file as one line with its comment markers gone, so a quoted comment can be matched.

    A sentence in `settings.py` is split across two `#` lines, and the marker between them is not
    part of the sentence the plan quotes.
    """
    return ' '.join(text.replace('#', ' ').split())


def sections(text):
    return re.findall(r'(?m)^## (.*)$', text)


def subsections(text):
    return re.findall(r'(?m)^### (.*)$', text)


def section(text, heading):
    return text.partition(f'## {heading}')[2].partition('\n## ')[0]


def numbered(text):
    """The numbers of a `1.`-style list, in order, so a decision cannot be silently unnumbered."""
    return [int(match.group(1)) for match in re.finditer(r'(?m)^(\d+)\. ', text)]


def documents():
    return sorted((ROOT / 'docs').rglob('*.md'))


def corpus():
    return [path for path in documents() if path not in ITEM_DOCS]


def tree_files():
    own = {path.resolve() for path in OWN_FILES}
    return [path for path in sorted(ROOT.rglob('*'))
            if path.is_file()
            and not any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts)
            and path.resolve() not in own]


def project_modules():
    """Non-test, non-migration Python modules of the seven project apps."""
    found = []
    for app in PROJECT_APPS:
        for module in sorted((ROOT / app).rglob('*.py')):
            relative = module.relative_to(ROOT).as_posix()
            if module.name.startswith('test_') or module.name == 'tests.py':
                continue
            if '/migrations/' in relative or '/tests/' in relative:
                continue
            found.append((relative, module))
    return found


def command_modules():
    return [path for _relative, path in project_modules()
            if 'management/commands' in path.relative_to(ROOT).as_posix()
            and path.name != '__init__.py']


def environment_reads(text):
    """The literal environment names `settings.py` reads, from its syntax tree."""
    names = []
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and reads_environ_parent(node.func.value) and node.args \
                and isinstance(node.args[0], ast.Constant):
            names.append(node.args[0].value)
        if isinstance(node, ast.Subscript) and reads_environ_parent(node.value) \
                and isinstance(node.slice, ast.Constant):
            names.append(node.slice.value)
    return names


def reads_environ_parent(node):
    return (isinstance(node, ast.Attribute) and node.attr == 'environ'
            and isinstance(node.value, ast.Name) and node.value.id == 'os')


def catalog(sql, params=None):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def one(sql, params=None):
    return catalog(sql, params)[0][0]


class PlanShapeTests(SimpleTestCase):
    def test_the_plan_states_its_own_shape(self):
        text = read(PLAN)
        self.assertTrue(text.startswith('# The database connection plan, and what a connection in '
                                        'this repository actually costs'),
                        'the plan stopped naming its own subject in its title')
        self.assertEqual(sections(text), SECTIONS, 'the plan grew or lost a section')
        self.assertEqual(subsections(text), SUBSECTIONS, 'the plan grew or lost a subsection')
        decisions = numbered(section(text, 'Candidate approach and decisions required'))
        self.assertEqual(decisions, list(range(1, len(DECISIONS) + 1)),
                         'a decision lost its number, so the record cannot name it')
        for decision in DECISIONS:
            with self.subTest(decision=decision[:40]):
                self.assertIn(decision, text, 'a decision was reworded or removed')
        for option in OPTIONS:
            with self.subTest(option=option):
                self.assertIn(f'**{option}**', text, 'an option lost its label')
        self.assertEqual(len(re.findall(r'(?m)^\| \*\*[A-H]\. ', text)), len(OPTIONS),
                         'the option table stopped carrying one row per option')
        self.assertEqual(len(numbered(section(text, 'Required behavior before any production '
                                                    'connection'))), REQUIRED_BEHAVIOR_COUNT,
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
        # The red-check list has to name the selection phrase it caught, so the record is read
        # without that section when the forbidden list is applied.
        outside_red_checks = flat(record.partition('## Red checks')[0]
                                  + record.partition('## Red checks')[2].partition('## ')[0]
                                  + record.partition('## Consequences')[2])
        for text, name in ((plan, 'the plan'), (outside_red_checks, 'the record')):
            for phrase in FORBIDDEN_SELECTION:
                with self.subTest(document=name, phrase=phrase):
                    self.assertNotIn(phrase, text,
                                     f'{name} chose an option instead of pricing it')
        self.assertIn('**Nothing is implemented.**', flat(record),
                      'the record stopped quoting the claim it holds the plan to')
        for phrase in ('Approved by', 'approved by', 'Decision owner', 'Owner:'):
            for document in (PLAN, ADR):
                with self.subTest(document=document.name, phrase=phrase):
                    self.assertNotIn(phrase, read(document),
                                     'an owner or an approval appeared')

    def test_the_plan_quotes_the_requirements_it_is_priced_against(self):
        plan = flat(read(PLAN))
        self.assertEqual(len(QUOTED_REQUIREMENTS), 24,
                         'the quotation list moved without the record saying so')
        for path, phrase in QUOTED_REQUIREMENTS:
            flatten = flat_code if path.suffix == '.py' else flat
            with self.subTest(document=path.name, phrase=phrase[:40]):
                self.assertIn(phrase, flatten(read(path)),
                              'a requirement the plan is priced against was reworded in its source')
                self.assertIn(phrase, plan, 'the plan stopped quoting a requirement it is priced '
                                            'against')
        self.assertIn('twenty-four quotes', flat(read(ADR)),
                      'the record states a quotation count that is not the list this suite holds')


class MeasuredNumberTests(SimpleTestCase):
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
        for record in ('0217-deployment-readiness-report.md', '0222-documented-environment.md',
                       '0233-database-migration-plan.md', '0009-postgresql-only.md',
                       '0235-database-connection-plan.md'):
            with self.subTest(record=record):
                self.assertIn(record, plan, 'the plan stopped linking a record it quotes')

    def test_the_document_corpus_counts_are_the_measured_ones(self):
        found = corpus()
        self.assertEqual(len(found), CORPUS_COUNT,
                         'the corpus the plan counts over moved; recount it from the tree')
        self.assertEqual(len(ITEM_DOCS), 11, 'the plan says eleven documents and this list is not')
        for token, count in sorted(DOC_TOKEN_COUNTS.items()):
            hits = [path for path in found if token in read(path)]
            with self.subTest(token=token):
                self.assertEqual(len(hits), count,
                                 'the documents naming this token moved; recount them from the tree')
        for token in ABSENT_DOC_TOKENS:
            hits = [path.name for path in found if token in read(path)]
            with self.subTest(token=token):
                self.assertEqual(hits, [], 'a document started naming a word the plan says none does')

    def test_the_tree_still_contains_no_pooler(self):
        found = tree_files()
        self.assertEqual(len(found), TREE_FILE_COUNT,
                         'the tree the plan counts over moved; recount it from the tree')
        for token in ABSENT_TREE_TOKENS:
            hits = []
            for path in found:
                try:
                    text = read(path)
                except UnicodeDecodeError:
                    continue
                if token in text:
                    hits.append(path.relative_to(ROOT).as_posix())
            with self.subTest(token=token):
                self.assertEqual(hits, [], 'a pooler or a statement-level monitor appeared')

    def test_the_timeout_inventory_is_the_measured_one(self):
        modules = project_modules()
        self.assertEqual(len(modules), PROJECT_MODULE_COUNT,
                         'the project module set the plan counts over moved')
        counted = {relative: read(path).count('SET LOCAL') for relative, path in modules}
        counted = {relative: count for relative, count in counted.items() if count}
        self.assertEqual(counted, SET_LOCAL_MODULES,
                         'the modules that bound their own statements moved')
        self.assertEqual(sum(counted.values()), SET_LOCAL_TOTAL)
        texts = {relative: read(path) for relative, path in modules}
        self.assertEqual(sum(text.count('lock_timeout') for text in texts.values()),
                         LOCK_TIMEOUT_COUNT, 'a `lock_timeout` appeared in project code')
        self.assertEqual(sum(text.count('statement_timeout') for text in texts.values()),
                         STATEMENT_TIMEOUT_COUNT, 'a `statement_timeout` appeared in project code')
        self.assertEqual(sum(text.count('idle_in_transaction_session_timeout')
                             for text in texts.values()), IDLE_TRANSACTION_COUNT,
                         'an idle-transaction bound appeared, which the plan says exists nowhere')
        own = {path.resolve() for path in OWN_FILES}
        test_texts = [read(path) for path in sorted(ROOT.rglob('test_*.py'))
                      if not any(part in SKIP_PARTS for part in path.relative_to(ROOT).parts)
                      and path.resolve() not in own]
        for token, count in sorted(TEST_TIMEOUT_MENTIONS.items()):
            with self.subTest(token=token):
                self.assertEqual(sum(text.count(token) for text in test_texts), count,
                                 'the test-suite timeout vocabulary the plan quotes moved')

    def test_the_settings_shape_is_the_measured_one(self):
        text = read(SETTINGS)
        self.assertIn("db_options = {'connect_timeout': 5}", text,
                      'the only connection option moved')
        self.assertIn("int(os.environ.get('POSTGRES_CONN_MAX_AGE', '0'))", text,
                      'the connection lifetime stopped defaulting to zero')
        self.assertIn('0 <= db_conn_max_age <= 31_536_000', text,
                      'the lifetime cap moved')
        self.assertIn("'CONN_HEALTH_CHECKS': True,", text,
                      'the health check on a reused connection was turned off')
        self.assertIn("raise ImproperlyConfigured('Invalid PostgreSQL port or connection lifetime')",
                      text, 'the refusal message for a bad lifetime moved')
        self.assertEqual(len(environment_reads(text)), SETTINGS_ENVIRONMENT_READS,
                         'settings.py grew an environment read, so an option was implemented')
        self.assertEqual(sorted(set(environment_reads(text))), list(SETTINGS_ENVIRONMENT),
                         'the environment names settings.py reads moved')
        self.assertEqual(tuple(settings.DATABASES), DATABASE_ALIASES,
                         'a database alias appeared, which is what a read replica would need')
        self.assertEqual(settings.DATABASES['default']['CONN_MAX_AGE'], 0,
                         'the running configuration does not have the lifetime the plan prices')
        self.assertTrue(settings.DATABASES['default']['CONN_HEALTH_CHECKS'])
        self.assertEqual(settings.DATABASES['default']['OPTIONS'], {'connect_timeout': 5},
                         'the running connection options are not the ones the plan prices')
        self.assertEqual(sorted(connection.settings_dict['OPTIONS']), ['connect_timeout'],
                         'the backend hands libpq an option the plan does not name')

    def test_no_new_command_model_or_dependency_exists(self):
        self.assertEqual(len([name for name in get_commands()
                              if name in {command.stem for command in command_modules()}]),
                         COMMAND_COUNT, 'a management command appeared')
        self.assertEqual(len(command_modules()), COMMAND_COUNT,
                         'the command modules in the tree moved')
        models = [model for model in apps.get_models()
                  if model._meta.app_label in PROJECT_APPS]
        self.assertEqual(len(models), PROJECT_MODEL_COUNT,
                         'a model appeared, which no connection option may do silently')
        for name, lines in sorted(REQUIREMENTS_LINES.items()):
            with self.subTest(requirement=name):
                self.assertEqual(len(read(ROOT / name).splitlines()), lines,
                                 'a dependency appeared, which is what a pooler would need')
        self.assertNotIn('pgserver', read(REQUIREMENTS),
                         'the synthetic server tool was added to the runtime lock')

    def test_the_compose_and_template_shape_is_the_measured_one(self):
        compose = read(COMPOSE)
        self.assertEqual(len(compose.splitlines()), COMPOSE_LINES,
                         'the development stack the plan prices moved')
        self.assertEqual(len(re.findall(r'(?m)^  [a-z]+:$', compose)), COMPOSE_SERVICES,
                         'a service appeared in the development stack')
        self.assertEqual(len(re.findall(r'(?m)^\s+[A-Z_]+:', compose)), COMPOSE_ENVIRONMENTS,
                         'the environment assignments in the development stack moved')
        self.assertIn('POSTGRES_CONN_MAX_AGE: ${POSTGRES_CONN_MAX_AGE:-0}', compose,
                      'the development stack stopped defaulting the lifetime to zero')
        self.assertEqual(compose.count('127.0.0.1'), COMPOSE_LOOPBACK_COUNT,
                         'the development stack stopped being bound to localhost')
        for limit in ('mem_limit', 'cpus', 'deploy:', 'resources:', 'memswap_limit'):
            with self.subTest(limit=limit):
                self.assertEqual(compose.count(limit), COMPOSE_RESOURCE_LIMITS,
                                 'a resource limit appeared, which the plan says exists nowhere')
        template = read(ENV_TEMPLATE)
        self.assertIn('POSTGRES_CONN_MAX_AGE=0', template,
                      'the template stopped defaulting the lifetime to zero')
        self.assertIn('Integer seconds, 0 through 31536000. Persistent connections need '
                      'operational review.', template,
                      'the template comment the plan quotes was reworded')

    def test_the_record_states_the_pin_deltas_it_causes(self):
        consequences = flat(section(read(ADR), 'Consequences'))
        for document in ('docs/DEPLOYMENT.md', 'docs/OPERATIONS_RUNBOOK.md', 'docs/SECURITY.md',
                         'docs/TESTING_STRATEGY.md', 'docs/DEVELOPMENT_GUIDE.md',
                         'docs/DATABASE_SCHEMA.md', 'docs/CHANGELOG.md',
                         'docs/PHASE1_RELEASE_EVIDENCE.md'):
            with self.subTest(document=document):
                self.assertIn(document, consequences,
                              'the record stopped naming a document it changed')
        self.assertIn('No option was chosen', consequences,
                      'the record stopped saying that nothing here decides anything')
        self.assertIn('269 documents, 235 records', consequences)
        self.assertIn('25 `Suite:` lines', consequences)
        self.assertIn('now count 242 and 241, and 268', consequences)
        self.assertIn('`LOGIN_ROUTE_TESTS` is 45, not 44', consequences,
                      'the record stopped naming the pin its module list moved')
        self.assertIn('twenty-six mutations', flat(section(read(ADR), 'Red checks')),
                      'the record states a red-check count that is not the list it carries')
        self.assertEqual(len(numbered(section(read(ADR), 'Red checks'))), 26,
                         'the red-check list the record names moved')
        for path, name, value in ((DOCUMENT_LINKS, 'DOCUMENT_COUNT', 269),
                                  (DOCUMENT_LINKS, 'ADR_COUNT', 235),
                                  (DOCUMENT_LINKS, 'SUITE_LINE_COUNT', 25),
                                  (MIGRATION_SUITE, 'TEST_MODULE_COUNT', 242),
                                  (MIGRATION_SUITE, 'DOCS_MARKDOWN_COUNT', 268),
                                  (MFA_SUITE, 'TEST_MODULE_COUNT', 241),
                                  (SECRET_SUITE, 'TEST_MODULE_COUNT', 241),
                                  (BACKUP_SUITE, 'DOCS_MARKDOWN_COUNT', 268),
                                  (MFA_SUITE, 'LOGIN_ROUTE_TESTS', 45)):
            with self.subTest(suite=path.name, pin=name):
                self.assertIn(f'{name} = {value}', read(path),
                              'a global pin the record names was not moved to the value it states')

    def test_the_neighbour_documents_and_the_evidence_row_link_the_plan(self):
        for path in (DEPLOYMENT, RUNBOOK, SECURITY, TESTING, GUIDE, SCHEMA_DOC, CHANGELOG):
            with self.subTest(document=path.name):
                text = flat(read(path))
                for phrase in ('DATABASE_CONNECTION_PLAN.md', '0235-database-connection-plan.md'):
                    self.assertIn(phrase, text,
                                  'a neighbouring document stopped naming the connection plan')
        self.assertIn('0235-database-connection-plan.md', read(ADR_INDEX),
                      'the record is not listed in the index that is supposed to list it')
        row = [line for line in read(EVIDENCE).splitlines()
               if line.startswith('| Data model and migrations')]
        self.assertEqual(len(row), 1, 'the data-model row of the release evidence moved')
        measured, open_cell = row[0].split('|')[2], row[0].split('|')[3]
        self.assertIn('DATABASE_CONNECTION_PLAN.md', measured)
        self.assertIn('0235-database-connection-plan.md', measured)
        self.assertIn('**Open:**', open_cell, 'the row stopped being open')
        for phrase in ('2.42 ms', '97', '1,104 kB', '1,104', '8,058,024', '5,001.98',
                       'no pooler', 'superuser'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, measured, 'the row stopped quoting a measured number')
        for phrase in ('no owner', 'not a capacity plan', 'nothing is implemented'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat(open_cell),
                              'the open cell stopped saying what the plan does not settle')
        # The sentences ADR 0233 put in this row are pinned by its own suite and must survive.
        for phrase in ('0.927', '1,172,320', '3.631', '2.703', '26 migrations', '1,186,535',
                       'DATABASE_MIGRATION_PLAN.md', '0233-database-migration-plan.md'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, measured + open_cell,
                              'the migration measurements in this row were disturbed')


class CatalogShapeTests(TransactionTestCase):
    """Facts read from the database the suite runs against, rather than trusted from the document.

    Only facts that hold in every environment this suite can run in are pinned: the compiled defaults
    of the server, the shape of the schema and the privileges of the role in use. Role counts,
    `listen_addresses` and any per-run name differ between the synthetic server and CI, so none is
    pinned.
    """

    def test_the_server_bounds_no_wait_and_configures_nothing(self):
        for name, expected in (('statement_timeout', '0'), ('lock_timeout', '0'),
                               ('idle_in_transaction_session_timeout', '0'),
                               ('idle_session_timeout', '0'), ('deadlock_timeout', '1s')):
            with self.subTest(setting=name):
                self.assertEqual(one('select current_setting(%s)', (name,)), expected,
                                 'the server started bounding a wait the plan says it does not')
        for name in ('max_connections', 'superuser_reserved_connections', 'statement_timeout',
                     'lock_timeout', 'idle_in_transaction_session_timeout', 'autovacuum_naptime',
                     'autovacuum_vacuum_scale_factor', 'checkpoint_timeout', 'wal_level',
                     'archive_mode', 'tcp_keepalives_idle', 'tcp_user_timeout'):
            with self.subTest(setting=name):
                setting, boot, source = catalog(
                    'select setting, boot_val, source from pg_settings where name = %s', (name,))[0]
                self.assertEqual(setting, boot,
                                 'a connection or capacity setting was configured away from its '
                                 'compiled default')
                self.assertIn(source, ('default', 'configuration file'),
                             'a connection or capacity setting is set somewhere this suite cannot '
                             'read: neither a compiled default nor a configuration file')

    def test_the_role_is_a_superuser_and_the_cluster_has_no_replica(self):
        self.assertTrue(one('select rolsuper from pg_roles where rolname = current_user'),
                        'the application stopped connecting as a superuser, which is what the plan '
                        'prices as the starting point')
        self.assertTrue(one('select has_database_privilege(current_user, current_database(), '
                            "'CREATE')"), 'the role in use lost CREATE on its own database')
        self.assertFalse(one('select pg_is_in_recovery()'),
                         'this environment grew a replica, so the standby the plan says cannot be '
                         'measured here became measurable')
        self.assertEqual(one('select count(*) from pg_stat_replication'), 0,
                         'a wal sender appeared')
        self.assertEqual(one('select count(*) from pg_replication_slots'), 0,
                         'a replication slot appeared')
        self.assertEqual(one("select current_setting('archive_mode')"), 'off',
                         'archiving was turned on, so a recovery objective became measurable here')
        for extension in EXTENSIONS_FORBIDDEN:
            with self.subTest(extension=extension):
                self.assertEqual(one('select count(*) from pg_extension where extname = %s',
                                     (extension,)), 0,
                                 'an extension the plan says is not available here was installed')
        self.assertEqual(one("select count(*) from pg_tables where schemaname = 'public'"
                             " and tableowner <> current_user"), 0,
                         'a table appeared that the role in use does not own')
        self.assertEqual(one("select count(*) from pg_constraint where contype = 'f'"), FOREIGN_KEYS,
                         'the foreign-key count the plan prices moved')
        foreign_keys = catalog('select conrelid, conkey::int2[] from pg_constraint'
                               " where contype = 'f'")
        indexes = catalog('select indrelid, indkey::int2[] from pg_index')
        unindexed = [key for key in foreign_keys
                     if not any(index[0] == key[0]
                                and list(index[1])[:len(key[1])] == list(key[1])
                                for index in indexes)]
        self.assertEqual(len(unindexed), UNINDEXED_FOREIGN_KEYS,
                         'a foreign key without an index or a covering prefix appeared, which is '
                         'the gap the plan prices')
        self.assertEqual(len(foreign_keys), FOREIGN_KEYS)
