"""Seventeen migrations, two directions, and four questions no document in this tree answers.

`docs/DATABASE_MIGRATION_PLAN.md` exists because seven documents ask for a staging migration and
rollback procedure and the repository answers with two drills that roll a throwaway database back.
`docs/DEPLOYMENT.md` asks a release to *"run tests/migrations on staging and validate rollback
compatibility"* and to *"Define rollback including content/cache and migration compatibility before
release"*; `docs/OPERATIONS_RUNBOOK.md` tells an operator to *"rerun in staging, then explicitly
resume from a safe checkpoint"*; `docs/DEVELOPMENT_GUIDE.md` warns that catalog migration `0008`
*"fails on existing violations and may wait for table locks"*; and the open gate in
`docs/PHASE1_RELEASE_EVIDENCE.md` names exactly what was missing — *"it measured no duration, no WAL
volume and no long-running `ALTER TABLE` under load"*, and *"Rollback of Django's own apps, other
shapes of concurrency (an open writing transaction, `CREATE INDEX CONCURRENTLY`, a running command, a
standby) and tested recovery from a real staging schema are unmeasured."*

What is measured here, and what the plan says because of it:

* both directions are sub-second and cheap in WAL. On an empty throwaway database `migrate` applied
  all 32 migrations in 0.927 s writing 1,172,320 bytes, `migrate catalog zero` unapplied its
  11-migration cascade in 0.711 s, the other five apps followed in 0.378 s leaving nine tables, and
  reapplying took 0.724 s and returned an inventory identical row for row with zero rows;
* a rollback's cost does not grow with the data it destroys. Inserting 50,000 rows wrote 29,621,944
  bytes of WAL; `migrate staff_security zero` removed both of that app's tables, and the 50,000 rows
  with them, in 0.096 s writing 6,680 bytes, and reapplying returned a table with zero rows;
* what each statement locks, and what a long one costs. `ALTER TABLE … ADD COLUMN` takes
  `AccessExclusiveLock` on the table alone, `CREATE INDEX` takes `ShareLock`, and an `ALTER COLUMN …
  TYPE` to the same width rewrites under `AccessExclusiveLock` on the table, its primary key, its
  indexes and its TOAST table. A metadata-only column took 0.001 s at zero rows and at 50,000; a
  rewriting column took 0.007 s, 0.143 s and 3.631 s at zero, 50,000 and 500,000 rows, writing
  178,759,168 bytes of WAL at the last of those — about the size of the table it rewrote;
* under a writer committing every 5 ms, about 175 writes a second, that rewrite waited 2.726 s and
  blocked exactly one insert for 2.703 s, a blocking `CREATE INDEX` took 0.102 s and stalled one
  writer for 0.094 s, the metadata-only column blocked nobody, and `CREATE INDEX CONCURRENTLY` —
  which no atomic migration can hold, because `atomic = False` appears in none of the 17 modules —
  took 0.003 s outside a transaction;
* one session that is only reading stops a migration. An uncommitted `UPDATE` and a `SELECT count(*)`
  followed by `pg_sleep(4)` each cancelled a metadata `ALTER TABLE` after 2.001 s at the drill's 2 s
  `lock_timeout`, and the same reader cancelled `migrate catalog zero` after 2.551 s, leaving 32
  tables, 31 of 32 applied migrations and 29 rows — the cascade's first migration is `ingestion
  0002`, not a `catalog` one, and it had already committed;
* no migration connection carries a timeout. `db_options` is `{'connect_timeout': 5}` while the
  request path bounds itself with `SET LOCAL lock_timeout = '1s'` in three project modules and
  `SET LOCAL statement_timeout` in four places;
* the one migration that reads data is cheap and fails atomically. `catalog 0008`, the validated
  `catalog_published_requires_verified` constraint, took 0.100 s and wrote 2,464 bytes against
  200,000 synthetic presentations and blocked no writer under load, and against a single violating
  row it failed after 0.052 s writing 0 bytes, leaving the constraint absent and the migration
  unrecorded — a forward failure restores the schema it found, while a blocked rollback does not;
* rolling back Django's own apps is the most destructive command in the tree. `migrate sessions zero`
  is one migration and costs `django_session`; `migrate contenttypes zero` derives a cascade of 26
  migrations, 24 of them project migrations, and leaves five tables and six rows; `migrate auth zero`
  afterwards finds nothing left to take, and an ORM read still returns rows from a schema that is
  mostly gone;
* almost nothing notices a half-undone schema. `check`, `makemigrations --check --dry-run` and
  `showmigrations` all exit 0 on one; `migrate --check` exits 1 and readiness reports one unapplied
  migration, which is what an unmigrated database reports too; the model-derived inspection counts the
  damage but `inspect_postgresql_schema` takes no `--database` and reads `django.db.connection`; and
  repairing forward took 0.198 s, returned an identical inventory and left 29 of 31 rows;
* a copy at that volume is small, fast and carries its sequences. `pg_dump --format=custom
  --no-owner --no-acl` of the 50,031-row database took 0.154 s and produced 1,186,535 bytes against
  the 136,001-byte fixture archive ADR 0232 measured, `pg_restore` into a database that did not exist
  took 0.327 s printing nothing, and the next insert into the restored database succeeded with no
  `setval`, because the archive carries its `SEQUENCE SET` entries;
* there is no standby here. `pg_is_in_recovery()` is false and both replication views are empty, so
  that shape stays unmeasured rather than measured safe.

The prices in the plan are counted from these measurements, not prototyped: no migration control was
built and reverted, so no cascade of pin failures was run. Four tests below are database-backed and
re-perform four of the measurements — the cascade a Django app's rollback derives from the graph, what
every existing command and both migration readiness checks say about a database a blocked rollback
left half undone, the atomic refusal of the validated constraint migration, and the absence of any
replica to measure a rollback against. What is not checked is which environment a staging migration runs in, who authorizes one, what is copied
beforehand and what the recovery objective is. Those are the eight numbered decisions the plan leaves
open, and no test can make them.
"""
import ast
import io
import re
from pathlib import Path
from unittest import mock

from django.apps import apps
from django.core.management import call_command
from django.db import connections
from django.test import SimpleTestCase, TransactionTestCase

from daroobank.management.commands import check_deployment_readiness as readiness

from .test_migration_reversibility import (CATALOG_CASCADE, MIGRATION_COUNTS, NOOP_REVERSES,
                                           PROJECT_APPS, applied, inventory, migrate, rows, tables,
                                           throwaway_database)
from .test_populated_rollback_drill import (LOCK_TIMEOUT, POPULATED, populate, rollback_plan,
                                            second_session, total)

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'DATABASE_MIGRATION_PLAN.md'
ADR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0233-database-migration-plan.md'
ADR_INDEX = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / 'README.md'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
RUNBOOK = ROOT / 'docs' / 'OPERATIONS_RUNBOOK.md'
GUIDE = ROOT / 'docs' / 'DEVELOPMENT_GUIDE.md'
TESTING = ROOT / 'docs' / 'TESTING_STRATEGY.md'
SCHEMA_DOC = ROOT / 'docs' / 'DATABASE_SCHEMA.md'
ROADMAP = ROOT / 'docs' / 'ROADMAP.md'
EVIDENCE = ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'
CHANGELOG = ROOT / 'docs' / 'CHANGELOG.md'
ADR_0225 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0225-populated-rollback-drill.md'
ADR_0226 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0226-ci-artifact-gate.md'
ADR_0232 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0232-backup-recovery-plan.md'
BACKUP_PLAN = ROOT / 'docs' / 'BACKUP_RECOVERY_PLAN.md'
SETTINGS = ROOT / 'daroobank' / 'settings.py'
WORKFLOW = ROOT / '.github' / 'workflows' / 'checks.yml'
COMPOSE = ROOT / 'compose.yaml'
REQUIREMENTS = ROOT / 'requirements.txt'
READINESS_COMMAND = ROOT / 'daroobank' / 'management' / 'commands' / 'check_deployment_readiness.py'
INSPECT_COMMAND = ROOT / 'catalog' / 'management' / 'commands' / 'inspect_postgresql_schema.py'
REVERSIBILITY = ROOT / 'daroobank' / 'test_migration_reversibility.py'
DRILL = ROOT / 'daroobank' / 'test_populated_rollback_drill.py'
DOCUMENT_LINKS = ROOT / 'daroobank' / 'test_document_links.py'
MFA_PLAN = ROOT / 'daroobank' / 'test_mfa_implementation_plan.py'
SECRET_PLAN = ROOT / 'daroobank' / 'test_secret_rotation_plan.py'
BACKUP_SUITE = ROOT / 'daroobank' / 'test_backup_recovery_plan.py'
READ_AUDIT_PLAN = ROOT / 'daroobank' / 'test_read_audit_plan.py'
NO_READ_AUDIT = ROOT / 'daroobank' / 'test_no_read_audit.py'
CONSTRAINT_MIGRATION = ROOT / 'catalog' / 'migrations' / \
    '0008_presentation_published_date_constraint.py'

SKIP_PARTS = frozenset({'.venv', '.cache', '.git', 'node_modules', '__pycache__', 'migrations',
                        'staticfiles'})
SECTIONS = ['What is true today, measured',
            'Candidate approach and decisions required',
            'Options and what each costs',
            'Required behavior before any staging migration',
            'Verification before any enablement']
SUBSECTIONS = ['What the tree migrates',
               'The cost of each direction, measured',
               'Rows, not seconds: what a rollback destroys',
               'Locks, and a long `ALTER TABLE` under load',
               'The one migration that reads data, and the shape of its failure',
               "Rolling back Django's own apps",
               'What notices a half-undone schema',
               'The copy step, measured at a volume',
               'What the repository already says about it']
DECISIONS = ['Which environment is "staging", and what data is in it?',
             "In which order, and may a rollback touch Django's own apps at all?",
             'Where is the copy step, and what shape does it take?',
             'Who authorizes a destructive migration, and how is that recorded?',
             'What is the acceptable lock wait, and what happens to requests during it?',
             'What detects a half-undone schema, and who reads it?',
             'What is the recovery objective for a failed migration',
             'Which migrations may never be rolled back in place?']
OPTIONS = ['A. Leave the migration path as it is',
           'B. Write the staging sequence down as an ordered procedure',
           'C. Bound the migration session with a timeout',
           'D. Move index builds out of atomic migrations',
           'E. Take a copy before every destructive migration and drill restoring it',
           'F. Make a half-undone schema detectable',
           'G. Declare staging migration and rollback out of Phase 1 scope']
REQUIRED_BEHAVIOR_COUNT = 7
VERIFICATION_COUNT = 6
PROPOSAL_PHRASES = ['This document is a **proposal**', 'It has no owner and no approval',
                    '**Nothing is implemented.**', 'no migration control was implemented and reverted',
                    'no cascade of pin failures was run', 'must not be read as a decision']
# The requirement each document states, quoted into the plan and pinned here, so the plan cannot drift
# away from the sentences it is written against.
QUOTED_REQUIREMENTS = [
    (DEPLOYMENT, 'run tests/migrations on staging and validate rollback compatibility'),
    (DEPLOYMENT, 'Use expand/contract migrations and versioned API; snapshot/backup before '
                 'destructive change'),
    (DEPLOYMENT, 'Define rollback including content/cache and migration compatibility before release'),
    (DEPLOYMENT, 'Test proxy host/origin and cookies, health endpoints, database migrations, worker '
                 'isolation'),
    (DEPLOYMENT, 'A measured rollback of this schema is not one command'),
    (DEPLOYMENT, 'is 11 migrations, is not ordered by app (`ingestion 0002` runs first) and commits '
                 'each migration alone, so a block on any table it touches leaves the database half '
                 'undone with rows already destroyed'),
    (DEPLOYMENT, 'Set `lock_timeout`, stop the writers, copy the tables the cascade will drop before '
                 'starting'),
    (DEPLOYMENT, 'treat `setval` on the identity sequences as part of any restore'),
    (DEPLOYMENT, 'defines no staging environment'),
    (RUNBOOK, 'rerun in staging, then explicitly resume from a safe checkpoint'),
    (RUNBOOK, "reads this process's settings and its migration table"),
    (RUNBOOK, 'never restore into the running database'),
    (GUIDE, 'fails on existing violations and may wait for table locks'),
    (GUIDE, 'Do not run multiple migration-starting web replicas'),
    (TESTING, 'atomic publication/rollback'),
    (TESTING, 'migrations and backup restore'),
    (TESTING, 'All relevant tests pass in CI and staging'),
    (ROADMAP, 'DB migrations'),
    (EVIDENCE, 'a staging upgrade and rollback **plan** — environment, order, backup and restore '
               'step, owner and authorization for a destructive operation'),
    (EVIDENCE, 'it measured no duration, no WAL volume and no long-running `ALTER TABLE` under load'),
    (EVIDENCE, 'No backup, restore tool, recovery objective or copy of the tables a cascade will drop '
               'exists; a failed rollback has to be repaired by hand'),
    (EVIDENCE, "Rollback of Django's own apps, other shapes of concurrency (an open writing "
               'transaction, `CREATE INDEX CONCURRENTLY`, a running command, a standby) and tested '
               'recovery from a real staging schema are unmeasured'),
    (CHANGELOG, "Django's own apps are never rolled back, and no backup, restore tool, recovery "
                'objective, staging environment or rollback **plan** with an owner exists'),
    (ADR_0225, 'Identity sequences are part of any restore.'),
]
# The measurements, one run each on synthetic throwaway databases, as the plan writes them. They are
# pinned as text because a duration is a fact about one run and not a budget.
MEASURED_BOTH = ['0.927', '1,172,320', '0.711', '149,408', '0.378', '61,536', '0.724', '885,624',
                 '0.096 s', '6,680', '29,621,944', '18,653,184', '50,031', '3.631 s',
                 '178,759,168', '186,662,912', '174,104,576', '2.726 s', '2.703 s', '0.102 s',
                 '0.094 s', '0.003 s', '2.001 s', '2.551 s', '0.100 s', '2,464', '0.052 s',
                 '200,000', '0.156 s', '4,544', '1.241 s', '346,936', '0.016 s', '752',
                 '26 migrations', '24 of them project migrations', '0.198 s', '1,186,535',
                 '0.154 s', '0.327 s', '136,001', "{'connect_timeout': 5}", 'atomic = False',
                 'ActiveSqlTransaction: CREATE INDEX CONCURRENTLY cannot run inside a transaction '
                 'block', 'canceling statement due to lock timeout',
                 '1 migrations are not applied: '
                 'ingestion.0002_importreceiptitem_importreceipt_manifest_version_and_more',
                 'every applied migration has a file in this release',
                 '32 migrations applied, none pending',
                 'cannot truncate a table referenced in a foreign key constraint',
                 'pg_is_in_recovery()', '(2, True)']
MEASURED_PLAN = ['0.345 s', '50,000 rows', '1,344 bytes', '1,408 bytes', '0.007 s', '27,016 bytes',
                 '0.143 s', '17,895,928 bytes', '0.013 s', '0.001 s', '1.125 s', '101,036,096',
                 '69,238,784', '2,440 bytes', '0.068 s', '6,200 bytes', '0.028 s', '0.068 s',
                 '32.3 s', '8.7 times', '~1,614 times', '0.02 %', '175 writes a second',
                 '28 unresolved tables', '49 missing foreign keys', '239 missing columns',
                 '1 unresolved table', '3 missing foreign keys', '10 missing columns']
# The inventory a migration change would move, quoted by four other suites as well as by this plan.
CURRENT_SCHEMA = {'tables': 33, 'columns': 279, 'indexes': 111, 'constraints': 138,
                  'foreign keys': 50, 'applied migrations': 32}
SCHEMA_SUITES = (MFA_PLAN, READ_AUDIT_PLAN, BACKUP_SUITE)
DJANGO_MIGRATIONS = {'auth': 12, 'contenttypes': 2, 'sessions': 1}
CONTENTTYPES_CASCADE = {'auth': 12, 'contenttypes': 2, 'catalog': 6, 'clinical': 2, 'ingestion': 2,
                        'pricing': 1, 'sources': 1}
AUTH_CASCADE_PROJECT = {'catalog': 6, 'clinical': 2, 'ingestion': 2, 'pricing': 1, 'sources': 1}
# What survives `migrate contenttypes zero`, and what survives rolling all six project apps back.
SURVIVORS = ['catalog_productpresentation', 'django_migrations', 'pricing_pricecandidate',
             'staff_security_publicreadwindow', 'staff_security_staffloginwindow']
DJANGO_SURVIVORS = ['auth_group', 'auth_group_permissions', 'auth_permission', 'auth_user',
                    'auth_user_groups', 'auth_user_user_permissions', 'django_content_type',
                    'django_migrations', 'django_session']
HALF_UNDONE = {'tables': 32, 'applied': 31, 'rows': 29}
UNAPPLIED_AFTER_BLOCK = ('ingestion', '0002_importreceiptitem_importreceipt_manifest_version_and_more')
CONSTRAINT_NAME = 'catalog_published_requires_verified'
LOCK_TIMEOUT_MODULES = ('staff_security/management/commands/cleanup_staff_login_windows.py',
                        'staff_security/read_limit.py', 'staff_security/throttle.py')
STATEMENT_TIMEOUT_PLACES = 4
COMMAND_COUNT = 12
PROJECT_MODEL_COUNT = 24
REQUIREMENTS_LINES = 94
SETTINGS_MODULES = 4
DOCS_MARKDOWN_COUNT = 264
TEST_MODULE_COUNT = 240
WORKFLOW_MIGRATE_STEPS = ['python manage.py migrate --noinput', 'python manage.py check',
                          'python manage.py makemigrations --check --dry-run',
                          'python manage.py inspect_postgresql_schema']


def read(path):
    return path.read_text(encoding='utf-8')


def query(alias, sql, params=None):
    """One read on a throwaway alias; the imported helper takes no parameters."""
    with connections[alias].cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def flat(text):
    """The document as one line, so a hard-wrapped phrase can be matched."""
    return ' '.join(text.split())


def sections(text):
    return re.findall(r'^## (.*)$', text, re.M)


def subsections(text):
    return re.findall(r'^### (.*)$', text, re.M)


def section(text, heading):
    return text.partition(f'## {heading}')[2].partition('\n## ')[0]


def python_modules():
    return sorted(path for path in ROOT.rglob('*.py')
                  if not (SKIP_PARTS & set(path.relative_to(ROOT).parts)))


def is_test_module(path):
    return path.name.startswith('test_') or path.name == 'tests.py'


def project_modules():
    return [path for path in python_modules() if not is_test_module(path)]


def command_modules():
    return [path for path in project_modules()
            if 'management/commands' in path.relative_to(ROOT).as_posix()
            and path.name != '__init__.py']


def migration_modules():
    """`{app: [paths]}` for the project's migration modules, from the tree rather than a pin."""
    return {app: sorted((ROOT / app / 'migrations').glob('0*.py')) for app in PROJECT_APPS}


def constant(text, name):
    match = re.search(rf'^{name} = (\d+)$', text, re.M)
    return int(match.group(1)) if match else None


def assignment(text, name):
    """The literal a module-level assignment holds, parsed rather than string-matched.

    A lookahead for the next line that starts at column zero would stop before the closing bracket of
    a multi-line tuple, so the literal is found by bracket depth instead.
    """
    marker = f'\n{name} = '
    start = text.find(marker)
    if start == -1:
        return None
    index = start + len(marker)
    depth = 0
    for offset, char in enumerate(text[index:], index):
        if char in '([{':
            depth += 1
        elif char in ')]}':
            depth -= 1
            if depth == 0:
                return ast.literal_eval(text[index:offset + 1])
        elif char == '\n' and depth == 0 and text[index:offset].strip():
            return ast.literal_eval(text[index:offset].strip())
    return None


class PlanStructureTests(SimpleTestCase):
    def test_the_plan_states_its_own_shape(self):
        text = read(PLAN)
        self.assertEqual(sections(text), SECTIONS, 'the plan gained or lost a section')
        self.assertEqual(subsections(text), SUBSECTIONS, 'the measured subsections moved')
        decisions = section(text, 'Candidate approach and decisions required')
        self.assertEqual(len(re.findall(r'^\d+\. \*\*', decisions, re.M)), len(DECISIONS),
                         'the number of decisions the plan leaves open changed')
        for opener in DECISIONS:
            with self.subTest(decision=opener):
                self.assertIn(opener, flat(decisions))
        options = section(text, 'Options and what each costs')
        self.assertEqual(len(re.findall(r'^\| \*\*[A-G]\.', options, re.M)), len(OPTIONS),
                         'the option table changed size')
        for option in OPTIONS:
            with self.subTest(option=option):
                self.assertIn(f'**{option}**', options)
        required = section(text, 'Required behavior before any staging migration')
        self.assertEqual(len(re.findall(r'^\d+\. \*\*', required, re.M)), REQUIRED_BEHAVIOR_COUNT,
                         'the required-behavior list changed size')
        verification = section(text, 'Verification before any enablement')
        self.assertEqual(len(re.findall(r'^- ', verification, re.M)), VERIFICATION_COUNT,
                         'the verification list changed size')

    def test_the_plan_is_an_unowned_proposal_that_implements_nothing(self):
        flat_text = flat(read(PLAN))
        for phrase in PROPOSAL_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_text,
                              'the plan stopped saying that it proposes and implements nothing')
        self.assertIn('not a staging environment, not a migration order, not a copy procedure and not '
                      'an authorization', flat_text)
        self.assertIn('names neither', flat_text, 'the plan stopped refusing to name an owner')
        for phrase in ('this document names neither', 'It has no owner'):
            self.assertIn(phrase, flat_text)

    def test_no_option_is_presented_as_chosen(self):
        flat_text = flat(read(PLAN)) + flat(read(ADR))
        for phrase in ('the chosen option is', 'we recommend', 'this record chooses',
                       'option A is selected', 'the selected option', 'has been approved'):
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, flat_text, 'an option started looking like a decision')
        self.assertIn('no option was chosen', flat(read(ADR)),
                      'the record stopped saying that no option was chosen')
        self.assertIn('none of them is answered here', flat(read(PLAN)))

    def test_the_plan_quotes_the_requirements_it_is_priced_against(self):
        flat_plan = flat(read(PLAN))
        for path, quote in QUOTED_REQUIREMENTS:
            with self.subTest(document=path.name, quote=quote[:40]):
                self.assertIn(quote, flat(read(path)),
                              'a document stopped saying what it is quoted for')
                self.assertIn(quote, flat_plan, 'the plan stopped quoting the requirement it answers')

    def test_the_plan_names_the_documents_records_and_suites_it_depends_on(self):
        text = read(PLAN)
        for document in (DEPLOYMENT, RUNBOOK, GUIDE, TESTING, ROADMAP, EVIDENCE, CHANGELOG):
            with self.subTest(document=document.name):
                self.assertIn(f'`docs/{document.name}`', text)
        for record in ('0225-populated-rollback-drill.md', '0226-ci-artifact-gate.md',
                       '0232-backup-recovery-plan.md', '0233-database-migration-plan.md'):
            with self.subTest(record=record):
                self.assertIn(f'ARCHITECTURE_DECISIONS/{record}', text,
                              'the plan stopped linking a record it is written against')
        self.assertIn('BACKUP_RECOVERY_PLAN.md', text)
        for suite in ('daroobank/test_migration_reversibility.py',
                      'daroobank/test_populated_rollback_drill.py',
                      'daroobank/test_database_migration_plan.py', 'daroobank/settings.py',
                      '.github/workflows/checks.yml',
                      'catalog/management/commands/inspect_postgresql_schema.py'):
            with self.subTest(suite=suite):
                self.assertIn(f'`{suite}`', text)

    def test_the_plan_states_the_numbers_it_measured(self):
        flat_plan = flat(read(PLAN))
        flat_record = flat(read(ADR))
        for value in MEASURED_BOTH:
            with self.subTest(measurement=value[:40]):
                self.assertIn(value, flat_plan, 'the plan dropped a number it measured')
                self.assertIn(value, flat_record, 'the record dropped a number the plan quotes')
        for value in MEASURED_PLAN:
            with self.subTest(measurement=value[:40]):
                self.assertIn(value, flat_plan, 'the plan dropped a number it measured')


class RecordStructureTests(SimpleTestCase):
    def test_the_record_has_its_sections_status_and_suite_line(self):
        text = read(ADR)
        self.assertEqual(sections(text), ['Context', 'Decision', 'Measured behavior', 'Red checks',
                                          'Consequences', 'Limitations'],
                         'the record gained or lost a section')
        self.assertRegex(text, r'(?m)^Date: \d{4}-\d{2}-\d{2}$')
        self.assertIn('Status: accepted', text)
        suite_line = re.search(r'(?m)^Suite: (.*)$', text)
        self.assertIsNotNone(suite_line, 'the record stopped naming the suite that pins it')
        self.assertIn('daroobank/test_database_migration_plan.py', suite_line.group(1))
        stated = re.search(r'\((\d+) tests', suite_line.group(1))
        self.assertIsNotNone(stated, 'the Suite: line stopped counting its tests')
        self.assertEqual(int(stated.group(1)), len(re.findall(r'\n    def test_', read(Path(__file__)))),
                         'the Suite: line and this file disagree about how many tests there are')

    def test_the_record_limits_what_it_claims(self):
        text = flat(section(read(ADR), 'Limitations'))
        for phrase in ('one run on one machine', 'one writer thread, not a workload',
                       'The prices are counted, not run', 'stay unmeasured',
                       'No option was evaluated for safety or lawfulness'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text, 'the record lost a limitation')
        self.assertEqual(len(re.findall(r'^- ', section(read(ADR), 'Limitations'), re.M)), 6,
                         'the limitation list changed size')

    def test_the_decision_index_summarizes_this_record(self):
        index = read(ADR_INDEX)
        self.assertIn('[0233: the database migration plan and what a rollback costs]'
                      '(0233-database-migration-plan.md)', index)
        bullet = flat(index.partition('0233-database-migration-plan.md) — ')[2].partition('\n')[0])
        for value in ('0.927 s', '1,172,320', '0.096 s', '6,680', '3.631 s', '178,759,168',
                      '2.703 s', '26-migration cascade', '0.100 s', '2,464', '1,186,535',
                      '0.327 s', 'Seven priced options, eight open decisions, no implementation'):
            with self.subTest(value=value):
                self.assertIn(value, bullet, 'the index summary dropped a measured fact')


class MigrationInventoryTests(SimpleTestCase):
    def test_the_tree_has_seventeen_atomic_project_migration_modules(self):
        modules = migration_modules()
        counts = {app: len(paths) for app, paths in modules.items()}
        self.assertEqual(counts, dict(MIGRATION_COUNTS),
                         'the per-app migration counts the plan quotes moved')
        self.assertEqual(sum(counts.values()), 17, 'the project migration module count moved')
        non_atomic = [path.name for paths in modules.values() for path in paths
                      if 'atomic = False' in read(path)]
        self.assertEqual(non_atomic, [], 'a migration stopped being atomic, which is option D')
        for app, paths in modules.items():
            with self.subTest(app=app):
                numbers = [path.name[:4] for path in paths]
                self.assertEqual(numbers, sorted(numbers), 'an app is no longer one linear chain')

    def test_the_two_data_operations_reverse_to_noops(self):
        noop = {('catalog', '0002_productpresentation_irc_normalized'),
                ('catalog', '0004_productcandidate_irc_normalized')}
        self.assertEqual(noop, set(NOOP_REVERSES), 'the no-op reverses the plan names moved')
        with_data = []
        for app, paths in migration_modules().items():
            for path in paths:
                text = read(path)
                if 'RunPython' in text or 'RunSQL' in text:
                    with_data.append((app, path.name[:4]))
                    self.assertIn('migrations.RunPython.noop', text,
                                  'a data operation lost its explicit no-op reverse')
        self.assertEqual(sorted(with_data), sorted((app, name[:4]) for app, name in noop),
                         'a data operation appeared or disappeared')

    def test_the_one_validating_migration_is_a_single_check_constraint(self):
        text = read(CONSTRAINT_MIGRATION)
        self.assertEqual(text.count('migrations.AddConstraint'), 1)
        self.assertEqual(text.count('migrations.'), 2, 'the migration grew an operation')
        self.assertIn(CONSTRAINT_NAME, text)
        self.assertIn('AddConstraint', flat(read(PLAN)))
        self.assertIn(CONSTRAINT_NAME, flat(read(PLAN)))
        self.assertIn('validates a check constraint against every existing row', flat(read(PLAN)))

    def test_no_migration_connection_carries_a_timeout(self):
        settings = read(SETTINGS)
        self.assertIn("db_options = {'connect_timeout': 5}", settings,
                      'the only database timeout this project configures changed')
        for name in ('lock_timeout', 'statement_timeout', 'idle_in_transaction_session_timeout'):
            with self.subTest(timeout=name):
                self.assertNotIn(name, settings,
                                 'a migration timeout appeared in the settings, which is option C')
        bounded = sorted(str(path.relative_to(ROOT)) for path in project_modules()
                         if 'SET LOCAL lock_timeout' in read(path))
        self.assertEqual(bounded, list(LOCK_TIMEOUT_MODULES),
                         'the request-path modules that bound their own lock wait moved')
        statements = sum(read(path).count('SET LOCAL statement_timeout')
                         for path in project_modules())
        self.assertEqual(statements, STATEMENT_TIMEOUT_PLACES,
                         'the request-path statement timeouts the plan counts moved')
        self.assertIn("db_options = {'connect_timeout': 5}", flat(read(PLAN)))

    def test_the_inspection_command_cannot_be_pointed_at_another_database(self):
        text = read(INSPECT_COMMAND)
        self.assertNotIn('add_arguments', text, 'the inspection command grew options, which is F')
        self.assertIn('from django.db import DatabaseError, connection', text)
        self.assertNotIn('--database', text)
        self.assertIn('takes no `--database`', flat(read(PLAN)))
        self.assertIn('reads `django.db.connection`', flat(read(PLAN)))


class EnvironmentInventoryTests(SimpleTestCase):
    def test_ci_migrates_an_empty_database_and_defines_no_environment(self):
        workflow = read(WORKFLOW)
        for step in WORKFLOW_MIGRATE_STEPS:
            with self.subTest(step=step):
                self.assertIn(step, workflow, 'the CI migration sequence changed')
        self.assertEqual(workflow.count('migrate --check'), 2,
                         'the compose migration checks the plan counts moved')
        self.assertEqual(len(re.findall(r'(?m)^\s*environment:', workflow)), 0,
                         'the workflow grew an environment, so a staging environment exists')
        self.assertEqual(read(COMPOSE).count('127.0.0.1'), 2,
                         'the development stack stopped being bound to localhost')
        self.assertEqual(len(list((ROOT / 'daroobank').glob('*settings*.py'))), SETTINGS_MODULES,
                         'a settings module appeared, which is what a staging environment would need')
        self.assertIn('no `environment:` key', flat(read(PLAN)))

    def test_the_readiness_command_has_exactly_two_migration_checks(self):
        text = read(READINESS_COMMAND)
        self.assertEqual(text.count('MigrationLoader(connection'), 2,
                         'the migration checks the plan names moved')
        # Counting the loader alone does not survive a rename: a check that stopped comparing what is
        # on disk with what is applied has to move these two counts as well.
        self.assertEqual(text.count('loader.disk_migrations'), 2,
                         'a migration check stopped reading what is on disk')
        self.assertEqual(text.count('loader.applied_migrations'), 3,
                         'a migration check stopped reading what is applied')
        self.assertIn("('migrations_applied', migrations_applied)", text)
        self.assertIn("('migration_history_consistent', migration_history_consistent)", text)
        self.assertEqual(len(readiness.REQUIRED), 10, 'the required readiness checks moved')
        self.assertIn('migrations are not applied', text,
                      'the wording the plan quotes from readiness changed')


class PinnedInventoryTests(SimpleTestCase):
    def test_the_schema_pins_a_migration_change_would_move_are_still_there(self):
        for path in SCHEMA_SUITES:
            with self.subTest(suite=path.name):
                self.assertEqual(assignment(read(path), 'CURRENT_SCHEMA'), CURRENT_SCHEMA,
                                 'the measured schema a new migration would move changed on its own')
        names = assignment(read(NO_READ_AUDIT), 'SCHEMA_TABLES')
        self.assertEqual(len(names), CURRENT_SCHEMA['tables'],
                         'the exact table-name tuple the read-audit suite pins moved')
        self.assertEqual(assignment(read(REVERSIBILITY), 'CATALOG_CASCADE'), dict(CATALOG_CASCADE),
                         'the single-app cascade the reversibility suite pins moved')
        self.assertEqual(sum(assignment(read(DRILL), 'POPULATED').values()), sum(POPULATED.values()),
                         'the drill fixture the plan quotes rows from moved')
        self.assertEqual(sum(POPULATED.values()), 31, 'the drill no longer fills 31 rows')
        for value in ('33 tables', '279 columns', '111 indexes', '138 constraints',
                      '50 foreign keys'):
            with self.subTest(value=value):
                self.assertIn(value, flat(read(PLAN)), 'the plan dropped a schema count it quotes')

    def test_the_pins_that_count_the_tree_moved_with_this_plan(self):
        links = read(DOCUMENT_LINKS)
        self.assertEqual(constant(links, 'DOCUMENT_COUNT'), DOCS_MARKDOWN_COUNT + 1,
                         'the document count the link suite pins is not README plus docs/')
        self.assertEqual(constant(links, 'ADR_COUNT'),
                         len(list((ROOT / 'docs' / 'ARCHITECTURE_DECISIONS')
                                  .glob('[0-9][0-9][0-9][0-9]-*.md'))))
        self.assertEqual(len(list((ROOT / 'docs').rglob('*.md'))), DOCS_MARKDOWN_COUNT,
                         'the markdown document count this suite pins moved')
        self.assertEqual(len([path for path in python_modules() if is_test_module(path)]),
                         TEST_MODULE_COUNT, 'the test module count this suite pins moved')
        for suite in (MFA_PLAN, SECRET_PLAN):
            with self.subTest(suite=suite.name):
                self.assertEqual(constant(read(suite), 'TEST_MODULE_COUNT'), TEST_MODULE_COUNT - 1,
                                 'the test-module count these suites pin is not the tree minus one')
        self.assertEqual(constant(read(BACKUP_SUITE), 'DOCS_MARKDOWN_COUNT'), DOCS_MARKDOWN_COUNT,
                         'the backup suite no longer counts the same documents this one does')


class PlanConsequenceTests(SimpleTestCase):
    def test_the_neighbouring_documents_name_the_plan_and_what_it_measured(self):
        for path, phrases in ((DEPLOYMENT, ['DATABASE_MIGRATION_PLAN.md',
                                            '0233-database-migration-plan.md']),
                              (RUNBOOK, ['DATABASE_MIGRATION_PLAN.md',
                                         '0233-database-migration-plan.md']),
                              (GUIDE, ['DATABASE_MIGRATION_PLAN.md',
                                       '0233-database-migration-plan.md']),
                              (TESTING, ['DATABASE_MIGRATION_PLAN.md',
                                         '0233-database-migration-plan.md']),
                              (SCHEMA_DOC, ['DATABASE_MIGRATION_PLAN.md',
                                            '0233-database-migration-plan.md']),
                              (CHANGELOG, ['DATABASE_MIGRATION_PLAN.md',
                                           '0233-database-migration-plan.md'])):
            with self.subTest(document=path.name):
                text = flat(read(path))
                for phrase in phrases:
                    self.assertIn(phrase, text,
                                  'a neighbouring document stopped naming the migration plan')

    def test_the_release_evidence_row_answers_the_gate_and_stays_open(self):
        row = [line for line in read(EVIDENCE).splitlines()
               if line.startswith('| Data model and migrations')]
        self.assertEqual(len(row), 1, 'the data-model row of the release evidence moved')
        measured, open_cell = row[0].split('|')[2], row[0].split('|')[3]
        self.assertIn('DATABASE_MIGRATION_PLAN.md', measured)
        self.assertIn('0233-database-migration-plan.md', measured)
        self.assertIn('**Open:**', open_cell, 'the row stopped being open')
        for phrase in ('0.927', '1,172,320', '3.631', '2.703', '26 migrations', '1,186,535'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, measured, 'the row stopped quoting a measured number')
        for phrase in ('no owner', 'not a staging environment'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat(open_cell),
                              'the open cell stopped saying what the plan does not settle')

    def test_the_record_names_the_documents_it_changed(self):
        text = flat(section(read(ADR), 'Consequences'))
        for document in ('docs/DEPLOYMENT.md', 'docs/OPERATIONS_RUNBOOK.md',
                         'docs/DEVELOPMENT_GUIDE.md', 'docs/TESTING_STRATEGY.md',
                         'docs/DATABASE_SCHEMA.md', 'docs/CHANGELOG.md',
                         'docs/PHASE1_RELEASE_EVIDENCE.md'):
            with self.subTest(document=document):
                self.assertIn(document, text, 'the record stopped naming a document it changed')
        self.assertIn('no option was chosen', text)
        self.assertIn('265 documents, 233 records', text)
        self.assertIn('23 `Suite:` lines', text)
        self.assertIn('now count 239', text)


class NothingImplementedTests(SimpleTestCase):
    def test_nothing_this_plan_prices_exists(self):
        self.assertEqual(len(command_modules()), COMMAND_COUNT,
                         'a management command appeared, which no option may do silently')
        self.assertEqual(len(read(REQUIREMENTS).splitlines()), REQUIREMENTS_LINES,
                         'a dependency appeared')
        self.assertNotIn('pgserver', read(REQUIREMENTS),
                         'the synthetic server tool was added to the runtime lock')
        self.assertEqual(len(migration_modules()['catalog']), MIGRATION_COUNTS['catalog'],
                         'a migration appeared')
        models = [model for model in apps.get_models()
                  if model._meta.app_label in PROJECT_APPS]
        self.assertEqual(len(models), PROJECT_MODEL_COUNT, 'a model appeared')
        names = ' '.join(model.__name__.lower() for model in models)
        for word in ('migration', 'staging', 'deployment', 'release', 'rollback'):
            with self.subTest(word=word):
                self.assertNotIn(word, names, 'a model named like a migration record appeared')
        for module in python_modules():
            relative = module.relative_to(ROOT).as_posix()
            if relative.startswith('daroobank/test_'):
                continue
            with self.subTest(module=relative):
                self.assertNotIn('staging_environment', read(module),
                                 'a staging environment appeared in project code')


class DerivedCascadeTests(TransactionTestCase):
    """The cascade a rollback derives from the graph, re-performed rather than quoted.

    Reading the graph needs a migrated database and writes nothing, so this runs against the test
    runner's own database instead of building a throwaway one.
    """

    def test_a_django_app_rollback_is_not_confined_to_django(self):
        catalog = rollback_plan('default', 'catalog')
        per_app = {}
        for app, _name in catalog:
            per_app[app] = per_app.get(app, 0) + 1
        self.assertEqual(per_app, dict(CATALOG_CASCADE),
                         'the single-app cascade the plan and the reversibility suite pin moved')
        self.assertEqual(len(catalog), 11, 'rolling catalog back is no longer 11 migrations')

        sessions = rollback_plan('default', 'sessions')
        self.assertEqual(len(sessions), 1, 'a session rollback stopped being one migration')
        self.assertEqual({app for app, _name in sessions}, {'sessions'})

        contenttypes = rollback_plan('default', 'contenttypes')
        counts = {}
        for app, _name in contenttypes:
            counts[app] = counts.get(app, 0) + 1
        self.assertEqual(counts, CONTENTTYPES_CASCADE,
                         'the contenttypes cascade the plan quotes moved')
        self.assertEqual(len(contenttypes), 26)
        self.assertEqual(len(contenttypes) - counts['contenttypes'], 24,
                         'rolling contenttypes back no longer takes 24 project migrations with it')
        self.assertGreater(len(contenttypes), len(catalog),
                           'the plan says a Django app rollback is wider than a catalog one')

        auth = rollback_plan('default', 'auth')
        auth_counts = {}
        for app, _name in auth:
            auth_counts[app] = auth_counts.get(app, 0) + 1
        self.assertEqual(auth_counts['auth'], DJANGO_MIGRATIONS['auth'])
        self.assertEqual({app: count for app, count in auth_counts.items() if app != 'auth'},
                         AUTH_CASCADE_PROJECT, 'the auth cascade the plan quotes moved')
        self.assertEqual(len(auth), 24)

    def test_the_validated_constraint_migration_refuses_one_row_without_being_recorded(self):
        with throwaway_database() as alias:
            migrate(alias)
            populate(alias)
            migrate(alias, 'catalog', '0007')
            self.assertEqual(self.constraint_count(alias), 0,
                             'the constraint survived rolling catalog back one migration')
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    'UPDATE catalog_productpresentation SET published = true, verified_at = NULL '
                    'WHERE id = (SELECT min(id) FROM catalog_productpresentation)')
                cursor.execute('SELECT count(*) FROM catalog_productpresentation '
                               'WHERE published AND verified_at IS NULL')
                violating = cursor.fetchone()[0]
            self.assertEqual(violating, 1, 'the fixture no longer holds a violating row to refuse')
            self.assertEqual(rows(alias, 'SELECT count(*) FROM catalog_productpresentation')[0][0], 2,
                             'the drill fixture no longer holds the two rows this test un-publishes')
            before = len(applied(alias))
            with self.assertRaises(Exception) as caught:
                migrate(alias, 'catalog')
            connections[alias].close()
            self.assertIn(CONSTRAINT_NAME, str(caught.exception))
            self.assertIn('violated by some row', str(caught.exception))
            self.assertEqual(self.constraint_count(alias), 0,
                             'a refused constraint migration left the constraint behind')
            self.assertEqual(len(applied(alias)), before,
                             'a refused constraint migration was recorded anyway')
            self.assertNotIn(('catalog', '0008_presentation_published_date_constraint'),
                             applied(alias))
            # The refusal is atomic: un-publishing the row lets the same migration through. The row
            # cannot be deleted, because a price candidate still points at it.
            with connections[alias].cursor() as cursor:
                cursor.execute('UPDATE catalog_productpresentation SET published = false '
                               'WHERE published AND verified_at IS NULL')
            migrate(alias, 'catalog')
            self.assertEqual(self.constraint_count(alias), 1,
                             'the constraint migration did not apply once the row was gone')
            self.assertEqual(len(applied(alias)), 32)

    def constraint_count(self, alias):
        return query(alias, 'SELECT count(*) FROM pg_constraint WHERE conname = %s',
                     (CONSTRAINT_NAME,))[0][0]


class HalfUndoneDetectionTests(TransactionTestCase):
    """What every existing command says about a database a blocked rollback left half undone."""

    def test_a_blocked_rollback_is_invisible_to_three_commands_and_visible_to_two(self):
        with throwaway_database() as alias:
            migrate(alias)
            populate(alias)
            schema_before = inventory(alias)
            rows_before = total(alias)
            self.assertEqual(rows_before, sum(POPULATED.values()))

            holder = second_session(alias)
            holder.cursor().execute('SELECT count(*) FROM catalog_productpresentation')
            holder.cursor().execute('SELECT pg_sleep(4)')
            with connections[alias].cursor() as cursor:
                cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
            with self.assertRaises(Exception) as caught:
                migrate(alias, 'catalog', 'zero')
            connections[alias].close()
            holder.rollback()
            holder.close()
            self.assertIn('lock timeout', str(caught.exception),
                          'the rollback was not cancelled by the lock timeout the drill sets')

            self.assertEqual(len(tables(alias)), HALF_UNDONE['tables'])
            self.assertEqual(len(applied(alias)), HALF_UNDONE['applied'])
            self.assertEqual(total(alias), HALF_UNDONE['rows'],
                             'a blocked rollback no longer destroys the rows the plan counts')
            self.assertNotIn(UNAPPLIED_AFTER_BLOCK, applied(alias),
                             'the first migration of the cascade is not the one the plan names')
            self.assertIn(('catalog', '0008_presentation_published_date_constraint'), applied(alias))

            for name, args, kwargs in (('check', ('check',), {'databases': [alias]}),
                                       ('makemigrations --check', ('makemigrations',),
                                        {'check': True, 'dry_run': True}),
                                       ('showmigrations', ('showmigrations',),
                                        {'database': alias})):
                with self.subTest(command=name):
                    try:
                        # `showmigrations` prints its list even at verbosity 0; the report is what is
                        # being measured, not the listing.
                        call_command(*args, verbosity=0, stdout=io.StringIO(), **kwargs)
                    except SystemExit as exit_code:  # pragma: no cover - a failure is the finding
                        self.fail(f'`manage.py {name}` started reporting a half-undone schema '
                                  f'(exit {exit_code.code}), which is option F')

            with self.subTest(command='migrate --check'):
                with self.assertRaises(SystemExit) as exit_code:
                    call_command('migrate', '--check', database=alias, interactive=False,
                                 verbosity=0, stdout=io.StringIO(), stderr=io.StringIO())
                self.assertEqual(exit_code.exception.code, 1)

            with mock.patch.object(readiness, 'connection', connections[alias]):
                applied_ok, applied_detail = readiness.migrations_applied()
                history_ok, history_detail = readiness.migration_history_consistent()
            self.assertFalse(applied_ok, 'readiness stopped seeing the unapplied migration')
            self.assertIn('1 migrations are not applied', applied_detail)
            self.assertIn('ingestion.0002', applied_detail)
            self.assertTrue(history_ok, 'a half-undone schema started looking like a stale release')
            self.assertEqual(history_detail, 'every applied migration has a file in this release')

            migrate(alias)
            self.assertEqual(inventory(alias), schema_before,
                             'repairing forward no longer returns an identical schema')
            self.assertEqual(len(applied(alias)), 32)
            self.assertEqual(total(alias), HALF_UNDONE['rows'],
                             'repairing forward started restoring rows, which nothing claims it does')
            with mock.patch.object(readiness, 'connection', connections[alias]):
                applied_ok, applied_detail = readiness.migrations_applied()
            self.assertTrue(applied_ok)
            self.assertEqual(applied_detail, '32 migrations applied, none pending')

    def test_no_standby_and_no_replication_exists_to_measure(self):
        with throwaway_database() as alias:
            migrate(alias)
            self.assertEqual(rows(alias, 'SELECT pg_is_in_recovery()')[0][0], False,
                             'this environment started replicating, so the standby shape is measurable')
            self.assertEqual(rows(alias, 'SELECT count(*) FROM pg_stat_replication')[0][0], 0)
            self.assertEqual(rows(alias, 'SELECT count(*) FROM pg_replication_slots')[0][0], 0)
            self.assertIn('no standby to measure', flat(read(ADR)))
            self.assertIn('No standby exists here to measure against', flat(read(PLAN)))
            # The two survivor lists the plan quotes, checked against a real rolled-back schema.
            for app in PROJECT_APPS:
                migrate(alias, app, 'zero')
            self.assertEqual(sorted(tables(alias)), DJANGO_SURVIVORS,
                             'a full project rollback no longer leaves exactly Django\'s tables')
            self.assertIn('Six `auth_*` tables, `django_content_type`, `django_migrations` and '
                          '`django_session`', flat(read(PLAN)))
            migrate(alias)
            for survivor in SURVIVORS:
                with self.subTest(table=survivor):
                    self.assertIn(survivor, flat(read(PLAN)),
                                  'the plan dropped one of the five surviving tables it names')
                    self.assertIn(survivor, flat(read(ADR)))
