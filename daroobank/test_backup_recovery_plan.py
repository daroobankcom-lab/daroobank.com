"""One drill, one archive, and three questions nothing in this repository asks.

`docs/BACKUP_RECOVERY_PLAN.md` exists because five documents ask for backup and recovery and the
repository answers with a drill that restores an archive into a database that did not exist before.
The drill is real and it runs twice in CI under opt-in switches, but the gate in
`docs/PHASE1_RELEASE_EVIDENCE.md` asks for *"integrity and anti-replay/freshness policy"*,
*"independent key custody"* and *"recovery objectives"*, and none of those is a property of restoring
into a fresh database. This suite pins the plan to what the documented restore path actually is and to
what one stale archive actually does, so the options in it stay priced against the code and the word
"drill" keeps meaning what it says.

What is measured here, and what the plan says because of it:

* the documented sequence is six steps and the second one discards its own output. The guide's script
  is `dump, list, createdb, restore, migrate, check`, and its listing step is
  `pg_restore --list --no-password -- "$SYNTHETIC_DUMP_FILE" > /dev/null`, so the fifteen-line comment
  header in which an archive states its creation time, source database, format and client version is
  thrown away;
* the drill captures that listing and never reads it. `daroobank/test_synthetic_restore.py` asserts
  only `listed.returncode`, and `listed.stdout` appears nowhere in its 315 lines;
* the target is always a database the process just created. The guide runs
  `createdb --no-password daroobank_restore_drill` and retargets `POSTGRES_DB` to that literal twice,
  and the drill refuses a colliding target instead of replacing it;
* one replay, performed on synthetic data in throwaway databases, shows what that leaves unproven. Two
  dumps of one database taken 0.071 s and 0.053 s apart carry the same one-second stamp, so the older
  archive is distinguishable only by its bytes; restoring it exits 0 in 0.163 s printing 0 bytes; the
  target comes back with 33 tables, 32 applied migrations, 2 accounts, 0 sessions, 1 package and
  1 review while the source holds 2 and 2; and `manage.py check`, `migrate --check`,
  `inspect_postgresql_schema` and the drill's own ORM verification all exit 0 in 1.673 s, because they
  verify a fixture the dumping process wrote;
* a restore brings back no privileges and every credential. Of 287 selected TOC entries — 33 `TABLE`,
  33 `TABLE DATA`, 60 `INDEX`, 30 `SEQUENCE` and 30 `SEQUENCE SET`, 51 `CONSTRAINT` and 50
  `FK CONSTRAINT` — none is an ACL, an OWNER or a GRANT, because the dump is taken with
  `--no-owner --no-acl`, and four of the `TABLE DATA` entries are
  `auth_user`, `auth_user_groups`, `auth_user_user_permissions` and `django_session`;
* restoring over a populated database fails and its fix is written down nowhere. A second restore of
  the same archive exits 1 in 0.006 s on `ERROR:  relation "auth_group" already exists`; adding
  `--clean --if-exists` makes it exit 0 in 0.209 s, and of the 264 markdown documents in `docs/` only
  the plan and its decision record name either flag;
* the envelope drill mints its own keys and destroys them. `openssl req -x509 -newkey rsa:2048 -nodes
  -days 1 -subj /CN=synthetic-only`, files `O_EXCL` at `0600` inside a `0700` temporary directory that
  the test removes, while `.github/workflows/checks.yml` references zero `secrets.*` expressions and no
  key file is committed, so *"independent key custody"* is the same open question ADR 0231 left for
  `DAROOBANK_SECRET_KEY`;
* the client tools are neither in the repository nor pinned by it. No `pg_dump` exists outside the
  virtual environment here, and CI writes two wrapper scripts that run
  `docker run --rm --network host … postgres:16 … pg_dump`, one of the four mutable base-image
  references ADR 0226 counted;
* nothing records a dump or a restore. `LOGGING` is `{}`, no application module imports `logging`,
  `pg_restore` printed 0 bytes, none of the 24 project models is named like a backup record, and the
  runbook's instruction is that a human *"Record the outcome without sensitive details"*.

The prices in the plan are counted from these measurements, not prototyped: no backup control was built
and reverted, so no cascade of pin failures was run, but the replay itself was performed and every
number above is its result. What is not checked is whether a recovery objective exists, who holds an
envelope key, who re-grants privileges after a `--no-acl` restore, what may be restored over what, and
how long a dump of every password hash may be kept. Those are the eight numbered decisions the plan
leaves open, and no test can make them.
"""
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import skipUnless
from uuid import uuid4

from django.apps import apps
from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase, override_settings

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'BACKUP_RECOVERY_PLAN.md'
ADR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0232-backup-recovery-plan.md'
ADR_INDEX = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / 'README.md'
GUIDE = ROOT / 'docs' / 'DEVELOPMENT_GUIDE.md'
RUNBOOK = ROOT / 'docs' / 'OPERATIONS_RUNBOOK.md'
EVIDENCE = ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'
SECURITY = ROOT / 'docs' / 'SECURITY.md'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
TESTING = ROOT / 'docs' / 'TESTING_STRATEGY.md'
CHANGELOG = ROOT / 'docs' / 'CHANGELOG.md'
ADR_0225 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0225-populated-rollback-drill.md'
DRILL = ROOT / 'daroobank' / 'test_synthetic_restore.py'
ENCRYPTED_DRILL = ROOT / 'daroobank' / 'test_synthetic_encrypted_restore.py'
GUARD = ROOT / 'daroobank' / 'test_synthetic_restore_guard.py'
FIXTURE = ROOT / 'daroobank' / 'synthetic_restore_fixture.py'
GUIDE_TEST = ROOT / 'daroobank' / 'test_backup_guide.py'
RESTORE_SETTINGS = ROOT / 'daroobank' / 'restore_test_settings.py'
ISOLATED_RUNNER = ROOT / 'daroobank' / 'isolated_test_runner.py'
WORKFLOW = ROOT / '.github' / 'workflows' / 'checks.yml'
CI_GATE = ROOT / 'daroobank' / 'test_ci_artifact_gate.py'
NO_READ_AUDIT = ROOT / 'daroobank' / 'test_no_read_audit.py'
ATTRIBUTION = ROOT / 'daroobank' / 'test_actor_attribution_inventory.py'
ROLLBACK_DRILL = ROOT / 'daroobank' / 'test_populated_rollback_drill.py'
MFA_PLAN = ROOT / 'daroobank' / 'test_mfa_implementation_plan.py'
READ_AUDIT_PLAN = ROOT / 'daroobank' / 'test_read_audit_plan.py'
DOCUMENT_LINKS = ROOT / 'daroobank' / 'test_document_links.py'
SETTINGS = ROOT / 'daroobank' / 'settings.py'
REQUIREMENTS = ROOT / 'requirements.txt'
REQUIREMENTS_IN = ROOT / 'requirements.in'

SKIP_PARTS = frozenset({'.venv', '.cache', '.git', 'node_modules', '__pycache__', 'migrations',
                        'staticfiles'})
PROJECT_APPS = ('catalog', 'clinical', 'ingestion', 'pricing', 'sources', 'staff_security')
SECTIONS = ['What is true today, measured',
            'Candidate approach and decisions required',
            'Options and what each costs',
            'Required behavior before any restore',
            'Verification before any enablement']
SUBSECTIONS = ['The documented restore path', 'The replay, measured on synthetic databases',
               'The envelope, the clients and the custody',
               'What the repository already says about it']
DECISIONS = ['What are the recovery objectives, and who approves them?',
             'How is the right archive chosen?',
             'Who holds the envelope key and the signing key',
             'What is a restore of the database the application uses?',
             'Who re-grants privileges after a `--no-owner --no-acl` restore, and how is that '
             'verified?',
             'What is recorded about a dump and a restore?',
             'How are dumps retained, moved off-host and protected?',
             'What makes a restore complete rather than consistent?']
OPTIONS = ['A. Leave the restore path as documented',
           "B. Read the archive's own header before restoring",
           'C. Record every dump and restore in the database',
           'D. Put the envelope keys in a custodian outside the repository',
           'E. Document and drill the live-database shape',
           'F. Verify completeness against a manifest instead of a self-written fixture',
           'G. Declare backup and recovery out of Phase 1 scope']
PROPOSAL_PHRASES = ['This document is a **proposal**', 'It has no owner and no approval',
                    '**Nothing is implemented.**', 'no backup control was implemented and reverted',
                    'no cascade of pin failures was run']
# The requirement each document states, quoted into the plan and pinned here, so the plan cannot
# drift away from the sentences it is written against.
QUOTED_REQUIREMENTS = [
    (GUIDE, "PostgreSQL's `pg_dump` and `pg_restore` are external client utilities, not an "
            'application backup service'),
    (GUIDE, 'are unencrypted by default and are not committed'),
    (GUIDE, 'A volume alone is not a backup.'),
    (GUIDE, 'Use a client version at least as new as the server'),
    (GUIDE, 'Choose a trusted private location, encrypt and retain according to policy'),
    (RUNBOOK, 'define ownership, encrypted backup cadence, off-host retention, RPO/RTO and recovery '
              'environment'),
    (RUNBOOK, 'no values have been approved'),
    (RUNBOOK, 'Record actual restore duration and recovery point'),
    (RUNBOOK, 'never restore into the running database'),
    (RUNBOOK, 'Test restoring database and authorized objects together, permissions, audit '
              'integrity, point-in-time consistency and application compatibility'),
    (RUNBOOK, 'These steps are not a production restore exercise'),
    (RUNBOOK, 'Record the outcome without sensitive details'),
    (EVIDENCE, 'encrypted off-site backups, independent key custody, access control, retention, '
               'integrity and anti-replay/freshness policy, recovery objectives, scheduled isolated '
               'restore drills and documented owner'),
    (EVIDENCE, 'The synthetic test is not an operating backup service.'),
    (SECURITY, 'Operate backups and database'),
    (ADR_0225, 'Identity sequences are part of any restore.'),
]
# The measured replay, one run on synthetic data. Durations and byte counts belong to that run and are
# pinned here as the numbers the plan quotes; the opt-in test below re-performs it and asserts the
# invariants that do not move.
REPLAY = {'stale bytes': 136001, 'fresh bytes': 136541, 'stale dump seconds': 0.071,
          'fresh dump seconds': 0.053, 'listing seconds': 0.003, 'restore seconds': 0.163,
          'verification seconds': 1.673, 'second restore seconds': 0.006,
          'clean restore seconds': 0.209, 'toc entries': 287, 'header toc entries': 291,
          'table data': 33, 'tables': 33, 'sequences': 30, 'sequence sets': 30, 'indexes': 60,
          'constraints': 51, 'foreign key constraints': 50,
          'acl entries': 0, 'public tables': 33, 'applied migrations': 32, 'accounts': 2,
          'sessions': 0, 'stale packages': 1, 'stale reviews': 1, 'source packages': 2,
          'source reviews': 2}
REPLAY_STAMP = '; Archive created at 2026-11-26 23:37:44 UTC'
SECOND_RESTORE_ERROR = 'ERROR:  relation "auth_group" already exists'
CREDENTIAL_TABLE_DATA = ('auth_user', 'auth_user_groups', 'auth_user_user_permissions',
                         'django_session')
GUIDE_TRACE = ('dump', 'list', 'createdb', 'restore', 'migrate', 'check')
GUIDE_LISTING = 'pg_restore --list --no-password -- "$SYNTHETIC_DUMP_FILE" > /dev/null'
GUIDE_DUMP = ('pg_dump --no-password --format=custom --no-owner --no-acl --dbname="$POSTGRES_DB" '
              '> "$SYNTHETIC_DUMP_FILE"')
GUIDE_CREATEDB = 'createdb --no-password daroobank_restore_drill'
GUIDE_RESTORE = ('pg_restore --no-password --exit-on-error --single-transaction --no-owner --no-acl '
                 '--dbname=daroobank_restore_drill -- "$SYNTHETIC_DUMP_FILE"')
GUIDE_PROTECTIONS = ('set -C', 'umask 077', 'An absolute archive path is required.',
                     'A simple synthetic database name is required.', '-le 63')
# The flags a recovery into an existing database would need, and the only documents that name them.
LIVE_RESTORE_TOKENS = ('--clean', '--if-exists', '--create', 'dropdb', 'DROP DATABASE')
DOCS_MARKDOWN_COUNT = 272
DRILL_LINES = 315
ENCRYPTED_DRILL_LINES = 225
FIXTURE_LINES = 230
TEST_COUNTS = {'daroobank/test_synthetic_restore.py': 5,
               'daroobank/test_synthetic_encrypted_restore.py': 2,
               'daroobank/test_synthetic_restore_guard.py': 9,
               'daroobank/test_backup_guide.py': 7}
OPT_IN_SWITCHES = {'DAROOBANK_RESTORE_TESTS': 'daroobank/test_synthetic_restore.py',
                   'DAROOBANK_ENCRYPTED_RESTORE_TESTS': 'daroobank/test_synthetic_encrypted_restore.py',
                   'DAROOBANK_BROWSER_TESTS': 'daroobank/test_browser.py',
                   'DAROOBANK_SEARCH_BENCHMARK': 'catalog/test_synthetic_search_benchmark.py'}
DRILL_TOTAL = 16
# The envelope drill builds its openssl commands as argument lists, so they are pinned as source.
ENVELOPE_COMMANDS = ["'openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1'",
                     "'-subj', '/CN=synthetic-only'",
                     "'openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:2048'",
                     "'openssl', 'pkey', '-in', str(private_key), '-pubout'",
                     "['openssl', 'cms', '-encrypt', '-binary', '-aes-256-gcm', '-outform', 'DER']",
                     "['openssl', 'dgst', '-sha256', '-sign'",
                     "['openssl', 'dgst', '-sha256', '-verify'",
                     "['openssl', 'cms', '-decrypt', '-binary', '-inform', 'DER']"]
# The same commands as the plan writes them, in shell form, for a reader without the source.
ENVELOPE_PLAN_PHRASES = ['openssl req -x509 -newkey rsa:2048 -nodes -days 1 -subj /CN=synthetic-only',
                         'openssl genpkey', 'openssl pkey -pubout',
                         'openssl cms -encrypt -binary -aes-256-gcm -outform DER',
                         'openssl dgst -sha256 -sign', 'openssl cms -decrypt']
ENVELOPE_NEGATIVE_CONTROLS = ["b'authEnvelopedData'", 'contents[-1] ^= 1',
                              "'Tampered synthetic envelope was accepted'",
                              "'Wrong synthetic recipient was accepted'"]
WORKFLOW_SHIM = ('exec docker run --rm --network host -v /tmp:/tmp -v "$RUNNER_TEMP:$RUNNER_TEMP" '
                 '-e PGHOST -e PGPORT -e PGUSER -e PGPASSWORD -e PGDATABASE -e PGSSLMODE '
                 '--entrypoint $tool postgres:16 "\\$@"')
WORKFLOW_FACTS = {'postgres:16': 2, 'python:3.11-slim': 0, '@sha256:': 0, 'secrets.': 0,
                  '::error::': 10, 'RUNNER_TEMP': 35, 'GITHUB_PATH': 1, 'GITHUB_OUTPUT': 0,
                  'needs:': 0, 'environment:': 0}
# The four mutable base-image references ADR 0226 counted, by file.
IMAGE_REFERENCES = {'.github/workflows/checks.yml': {'postgres:16': 2},
                    'compose.yaml': {'postgres:16': 1},
                    'Dockerfile': {'python:3.11-slim': 1}}
CI_GATE_FACTS = {'STEP_COUNT': 22, 'RUN_STEP_COUNT': 17, 'USES_COUNT': 5, 'ERROR_ANNOTATIONS': 10,
                 'RUNNER_TEMP_REFERENCES': 35}
CURRENT_SCHEMA = {'tables': 33, 'columns': 279, 'indexes': 111, 'constraints': 138,
                  'foreign keys': 50, 'applied migrations': 32}
READ_AUDIT_PROTOTYPE = {'tables': 33, 'columns': 283, 'indexes': 113}
SCHEMA_TABLE_COUNT = 33
UNATTRIBUTED_MODELS = ('catalog.ProductPresentation', 'catalog.FormulationComponent',
                       'ingestion.ImportReceiptItem', 'staff_security.StaffLoginWindow',
                       'staff_security.PublicReadWindow')
PROJECT_MODEL_COUNT = 24
ATTRIBUTED_MODEL_COUNT = 19
POPULATED_TABLES = 24
POPULATED_ROWS = 31
MIGRATION_MODULES = 17
APPLIED_MIGRATIONS = 32
COMMAND_COUNT = 12
REQUIREMENTS_LINES = 94
DIRECT_REQUIREMENTS = ['Django==5.2.19', 'asgiref==3.13.0', 'sqlparse==0.6.1',
                       'psycopg[binary]==3.3.9']
BACKUP_WORDS = r'(?i)backup|restore|recover|dump|archive|snapshot|replica'
# The only project modules named like a restore today, both of them drill support rather than a
# control: the isolated settings the drill requires and the fixture it verifies.
RESTORE_NAMED_MODULES = ['daroobank/restore_test_settings.py',
                         'daroobank/synthetic_restore_fixture.py']
KEY_FILE_SUFFIXES = ('.pem', '.key', '.crt', '.p12', '.pfx', '.gpg', '.asc')
# TOC entry kinds `pg_restore --list` can print, longest first so `TABLE DATA` is not read as `TABLE`.
TOC_KINDS = ('TABLE DATA', 'FK CONSTRAINT', 'CONSTRAINT TRIGGER', 'SEQUENCE OWNED BY',
             'DEFAULT ACL', 'MATERIALIZED VIEW', 'BLOB DATA', 'INDEX ATTACH', 'SEQUENCE SET',
             'UNIQUE CONSTRAINT', 'CHECK CONSTRAINT', 'PRIMARY KEY', 'CONSTRAINT', 'SEQUENCE',
             'INDEX', 'TABLE', 'VIEW', 'SCHEMA', 'EXTENSION', 'COMMENT', 'ACL', 'OWNER', 'GRANT',
             'FUNCTION', 'TRIGGER', 'RULE', 'TYPE', 'STATISTICS', 'DEFAULT')
PRIVILEGE_KINDS = ('ACL', 'OWNER', 'GRANT', 'DEFAULT ACL')


def read(path):
    return path.read_text(encoding='utf-8')


def flat(text):
    """The document as one line, so a hard-wrapped phrase can be matched."""
    return ' '.join(text.split())


def sections(text):
    return re.findall(r'^## (.*)$', text, re.M)


def subsections(text):
    return re.findall(r'^### (.*)$', text, re.M)


def section(text, heading):
    return text.partition(f'## {heading}')[2].partition('\n## ')[0]


def guide_script():
    """The shell sequence the guide documents, exactly as `test_backup_guide.py` extracts it."""
    text = read(GUIDE)
    return text.split('For a **synthetic development**', 1)[1].split('```sh\n', 1)[1].split('\n```', 1)[0]


def python_modules():
    return sorted(path for path in ROOT.rglob('*.py')
                  if not (SKIP_PARTS & set(path.relative_to(ROOT).parts)))


def is_test_module(path):
    return path.name.startswith('test_') or path.name == 'tests.py'


def project_modules():
    """Non-test project modules: the code an operator's restore would run."""
    return [path for path in python_modules() if not is_test_module(path)]


def command_modules():
    return [path for path in project_modules()
            if 'management/commands' in path.relative_to(ROOT).as_posix()
            and path.name != '__init__.py']


def markdown_documents():
    return sorted((ROOT / 'docs').rglob('*.md'))


def test_methods(path):
    return len(re.findall(r'\n    def test_', read(path)))


def toc_kinds(listing):
    """`{kind: count}` for the selected entries of a `pg_restore --list` listing."""
    kinds = {}
    for line in listing.splitlines():
        if not line.strip() or line.startswith(';'):
            continue
        tokens = line.split(';', 1)[1].split()
        for kind in TOC_KINDS:
            words = kind.split()
            if tokens[2:2 + len(words)] == words:
                kinds[kind] = kinds.get(kind, 0) + 1
                break
        else:
            kinds['unparsed'] = kinds.get('unparsed', 0) + 1
    return kinds


def constant(text, name):
    """The integer a pinned constant is set to in another suite."""
    match = re.search(rf'^{name} = (\d+)$', text, re.M)
    return int(match.group(1)) if match else None


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
        required = section(text, 'Required behavior before any restore')
        self.assertEqual(len(re.findall(r'^\d+\. \*\*', required, re.M)), 7,
                         'the required-behavior list changed size')
        verification = section(text, 'Verification before any enablement')
        self.assertEqual(len(re.findall(r'^- ', verification, re.M)), 6,
                         'the verification list changed size')

    def test_the_plan_is_an_unowned_proposal_that_implements_nothing(self):
        flat_text = flat(read(PLAN))
        for phrase in PROPOSAL_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_text,
                              'the plan stopped saying that it proposes and implements nothing')
        self.assertIn('must not be read as a decision', flat_text)
        self.assertIn('not a recovery objective', flat_text)
        for phrase in ('approved procedure', 'no owner'):
            self.assertIn(phrase, flat_text)

    def test_the_plan_quotes_the_requirements_it_is_priced_against(self):
        flat_plan = flat(read(PLAN))
        for path, quote in QUOTED_REQUIREMENTS:
            with self.subTest(document=path.name, quote=quote[:40]):
                self.assertIn(quote, flat(read(path)), 'a document stopped saying what it is quoted for')
                self.assertIn(quote, flat_plan, 'the plan stopped quoting the requirement it answers')

    def test_the_plan_states_the_measured_replay_numbers(self):
        flat_plan = flat(read(PLAN))
        for label, value in REPLAY.items():
            with self.subTest(measurement=label):
                if isinstance(value, float):
                    self.assertIn(f'{value} s', flat_plan, f'the plan dropped the {label} it measured')
                elif label.endswith('bytes'):
                    self.assertIn(f'{value:,}', flat_plan, f'the plan dropped the {label} it measured')
                else:
                    self.assertIn(str(value), flat_plan, f'the plan dropped the {label} it measured')
        self.assertIn(REPLAY_STAMP, flat_plan, 'the plan dropped the stamp both archives shared')
        # `flat` collapses whitespace, so the two-space PostgreSQL error is matched normalized.
        self.assertIn(flat(SECOND_RESTORE_ERROR), flat_plan,
                      'the plan dropped the second restore error')
        self.assertIn(f'{DRILL_TOTAL} of those tests pass locally in 23.8 s', flat_plan,
                      'the plan dropped the local drill run it measured')

    def test_the_plan_names_the_five_documents_and_the_records_it_depends_on(self):
        text = read(PLAN)
        for document in (GUIDE, RUNBOOK, EVIDENCE, SECURITY):
            with self.subTest(document=document.name):
                self.assertIn(f'`docs/{document.name}`', text)
        for record in ('0221-no-read-audit.md', '0225-populated-rollback-drill.md',
                       '0226-ci-artifact-gate.md', '0232-backup-recovery-plan.md'):
            with self.subTest(record=record):
                self.assertIn(f'ARCHITECTURE_DECISIONS/{record}', text,
                              'the plan stopped linking a record it is written against')
        self.assertIn('SECRET_ROTATION_PLAN.md', text)
        for suite in ('daroobank/test_backup_guide.py', 'daroobank/test_synthetic_restore.py',
                      'daroobank/test_synthetic_encrypted_restore.py',
                      'daroobank/test_synthetic_restore_guard.py',
                      'daroobank/synthetic_restore_fixture.py', 'daroobank/test_ci_artifact_gate.py'):
            with self.subTest(suite=suite):
                self.assertIn(f'`{suite}`', text)


class DocumentedRestorePathTests(SimpleTestCase):
    def test_the_guide_sequence_is_six_steps_and_discards_the_listing(self):
        script = guide_script()
        flat_script = flat(script)
        self.assertIn(GUIDE_DUMP, flat_script, 'the documented dump command changed')
        self.assertIn(GUIDE_LISTING, flat_script,
                      'the documented listing stopped discarding its output, which is the gap '
                      'the plan is priced against')
        self.assertIn(GUIDE_CREATEDB, flat_script)
        self.assertIn(GUIDE_RESTORE, flat_script)
        self.assertEqual(flat_script.count('POSTGRES_DB=daroobank_restore_drill'), 2,
                         'the number of commands retargeted at the drill database changed')
        for protection in GUIDE_PROTECTIONS:
            with self.subTest(protection=protection):
                self.assertIn(protection, script)
        self.assertIn("['dump', 'list', 'createdb', 'restore', 'migrate', 'check']",
                      read(GUIDE_TEST), 'the pinned trace in the guide test moved')
        self.assertEqual(test_methods(GUIDE_TEST), TEST_COUNTS['daroobank/test_backup_guide.py'])

    def test_the_guide_restores_only_into_a_database_it_just_created(self):
        script = guide_script()
        for token in LIVE_RESTORE_TOKENS:
            with self.subTest(token=token):
                self.assertNotIn(token, script,
                                 'the documented sequence learned a live-database restore shape')
        self.assertIn('daroobank_restore_drill', script)
        drill = read(DRILL)
        self.assertIn('Source and target are new, dedicated databases, never an existing database',
                      drill, 'the drill stopped saying which databases it may touch')
        self.assertIn('def test_target_name_collision_is_not_dropped', drill,
                      'the collision refusal the plan relies on disappeared')
        self.assertIn('created = False', drill)
        self.assertRegex(read(RESTORE_SETTINGS), r"test_daroobank_restore_\{uuid4\(\)\.hex\}")
        self.assertIn('DAROOBANK_RESTORE_ISOLATED', read(RESTORE_SETTINGS))
        self.assertIn('IsolatedTestRunner', read(ISOLATED_RUNNER))

    def test_no_document_except_the_plan_and_its_record_names_a_live_database_restore(self):
        naming = sorted(str(path.relative_to(ROOT)) for path in markdown_documents()
                        if any(token in read(path) for token in LIVE_RESTORE_TOKENS))
        self.assertEqual(naming, ['docs/ARCHITECTURE_DECISIONS/0232-backup-recovery-plan.md',
                                  'docs/BACKUP_RECOVERY_PLAN.md'],
                         'a document other than the plan and its record named a live restore shape')
        self.assertEqual(len(markdown_documents()), DOCS_MARKDOWN_COUNT,
                         'the document count the plan quotes moved')

    def test_the_drill_never_reads_the_listing_it_captures(self):
        drill = read(DRILL)
        self.assertEqual(drill.count('listed.stdout'), 0,
                         'the drill started reading the archive listing, which closes the gap the '
                         'plan is priced against')
        self.assertEqual(drill.count('listed.returncode'), 1)
        self.assertIn("self.assertEqual(listed.returncode, 0, 'Synthetic archive listing failed')",
                      drill)
        self.assertEqual(len(drill.splitlines()), DRILL_LINES)
        self.assertEqual(test_methods(DRILL), TEST_COUNTS['daroobank/test_synthetic_restore.py'])
        self.assertEqual(test_methods(GUARD), TEST_COUNTS['daroobank/test_synthetic_restore_guard.py'])
        self.assertEqual(test_methods(ENCRYPTED_DRILL),
                         TEST_COUNTS['daroobank/test_synthetic_encrypted_restore.py'])
        self.assertEqual(len(read(ENCRYPTED_DRILL).splitlines()), ENCRYPTED_DRILL_LINES)
        self.assertEqual(len(read(FIXTURE).splitlines()), FIXTURE_LINES)

    def test_the_runbook_and_the_evidence_row_say_what_is_missing(self):
        flat_plan = flat(read(PLAN))
        self.assertIn('## Restore and recovery', read(RUNBOOK))
        self.assertIn('## Local synthetic restore drill', read(RUNBOOK))
        row = [line for line in read(EVIDENCE).splitlines()
               if line.startswith('| Backups and recovery |')]
        self.assertEqual(len(row), 1, 'the release-evidence row for backups moved or duplicated')
        self.assertIn('**Open:**', row[0])
        for phrase in ('recovery objectives', 'documented owner', 'anti-replay/freshness policy'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, row[0])
                self.assertIn(phrase, flat_plan)

    def test_the_restore_drills_are_opt_in_and_counted(self):
        for switch, module in OPT_IN_SWITCHES.items():
            with self.subTest(switch=switch):
                self.assertIn(f"os.environ.get('{switch}') == '1'", read(ROOT / module),
                              'an opt-in drill changed the switch it answers to')
        self.assertIn('which is 9 of the 10 skips an ordinary run reports', flat(read(PLAN)),
                      'the plan stopped saying how many skips the opt-in suites account for')
        total = sum(TEST_COUNTS[module] for module in
                    ('daroobank/test_synthetic_restore.py',
                     'daroobank/test_synthetic_encrypted_restore.py',
                     'daroobank/test_synthetic_restore_guard.py'))
        self.assertEqual(total, DRILL_TOTAL,
                         'the number of restore tests a local drill run performs changed')
        for step in ('Run isolated synthetic restore drill', 'DAROOBANK_RESTORE_TESTS',
                     'DAROOBANK_ENCRYPTED_RESTORE_TESTS'):
            with self.subTest(step=step):
                self.assertIn(step, read(WORKFLOW))
        self.assertIn('daroobank.test_synthetic_restore --settings=daroobank.restore_test_settings',
                      read(WORKFLOW))


class ArchiveContentsTests(SimpleTestCase):
    def test_the_dump_flags_drop_privileges_and_the_plan_says_so(self):
        script = flat(guide_script())
        self.assertEqual(script.count('--no-owner --no-acl'), 2,
                         'the dump or the restore stopped dropping owners and privileges')
        self.assertIn('--format=custom', script)
        flat_plan = flat(read(PLAN))
        for phrase in ('**zero** carry an ACL, an OWNER or a GRANT', '33 `TABLE DATA`',
                       '`TOC Entries: 291`', 'who re-grants them'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_plan)
        for table in CREDENTIAL_TABLE_DATA:
            with self.subTest(table=table):
                self.assertIn(f'`{table}`', read(PLAN),
                              'the plan stopped naming a credential table the archive carries')

    def test_the_archive_is_a_credential_store_and_the_plan_prices_it(self):
        flat_plan = flat(read(PLAN))
        self.assertIn(f"{REPLAY['stale bytes']:,}-byte file", flat_plan)
        for phrase in ('every password hash and every live session row', 'umask 077', 'set -C'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_plan)
        drill = read(DRILL)
        self.assertIn('0o600', drill)
        self.assertIn('os.O_WRONLY | os.O_CREAT | os.O_EXCL', drill)
        self.assertIn('0o700', drill)
        self.assertIn('self.assertGreater(archive.stat().st_size, 128)', drill)


class EnvelopeAndCustodyTests(SimpleTestCase):
    def test_the_encrypted_drill_mints_and_destroys_its_own_keys(self):
        drill = flat(read(ENCRYPTED_DRILL))
        for command in ENVELOPE_COMMANDS:
            with self.subTest(command=command):
                self.assertIn(command, drill, 'the envelope drill changed how it makes or opens a key')
        for control in ENVELOPE_NEGATIVE_CONTROLS:
            with self.subTest(control=control):
                self.assertIn(control, drill, 'an envelope negative control disappeared')
        flat_plan = flat(read(PLAN))
        for phrase in ENVELOPE_PLAN_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_plan, 'the plan stopped naming an envelope command')
        self.assertIn("'-days', '1'", drill, 'the synthetic certificate stopped expiring in a day')
        self.assertIn('/CN=synthetic-only', drill)
        self.assertIn('os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600', drill)
        self.assertIn('tempfile.TemporaryDirectory', drill)
        self.assertIn('0o700', drill)
        flat_plan = flat(read(PLAN))
        for phrase in ('mints its own keys and destroys them', 'No custodian exists anywhere',
                       'independent key custody'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_plan)

    def test_the_workflow_holds_no_secret_and_no_key_file_is_committed(self):
        workflow = read(WORKFLOW)
        for token, count in WORKFLOW_FACTS.items():
            with self.subTest(token=token):
                self.assertEqual(workflow.count(token), count,
                                 f'the workflow inventory the plan quotes changed for {token}')
        self.assertIn('permissions:\n  contents: read', workflow)
        self.assertNotIn('secrets.', workflow, 'CI started holding a secret the plan says it has none of')
        self.assertIn(WORKFLOW_SHIM, workflow, 'the client shim the plan describes moved')
        keys = sorted(str(path.relative_to(ROOT)) for path in ROOT.rglob('*')
                      if path.suffix in KEY_FILE_SUFFIXES and path.is_file()
                      and not (SKIP_PARTS & set(path.relative_to(ROOT).parts)))
        self.assertEqual(keys, [], 'a key file appeared in the repository')
        settings_text = read(SETTINGS)
        self.assertNotIn('PASSPHRASE', settings_text)
        self.assertNotIn('BACKUP_KEY', settings_text)
        flat_plan = flat(read(PLAN))
        self.assertIn('**zero** `secrets.*`', flat_plan)
        self.assertIn('no key file is committed', flat_plan)

    def test_the_client_tools_come_from_outside_the_repository(self):
        tracked = [str(path.relative_to(ROOT)) for path in python_modules()]
        self.assertEqual([name for name in tracked if 'pg_dump' in name or 'pg_restore' in name], [],
                         'a PostgreSQL client binary became part of the repository')
        workflow = read(WORKFLOW)
        self.assertIn('--entrypoint $tool postgres:16', workflow)
        total = 0
        for name, images in IMAGE_REFERENCES.items():
            text = read(ROOT / name)
            for image, count in images.items():
                with self.subTest(file=name, image=image):
                    self.assertEqual(text.count(image), count,
                                     'a mutable base-image reference moved')
                    total += count
        self.assertEqual(total, 4, 'the four mutable references ADR 0226 counted changed')
        self.assertEqual(read(ROOT / 'Dockerfile').count('@sha256:'), 0)
        gate = read(CI_GATE)
        self.assertEqual(constant(gate, 'STEP_COUNT'), CI_GATE_FACTS['STEP_COUNT'])
        self.assertEqual(constant(gate, 'RUN_STEP_COUNT'), CI_GATE_FACTS['RUN_STEP_COUNT'])
        self.assertEqual(constant(gate, 'USES_COUNT'), CI_GATE_FACTS['USES_COUNT'])
        self.assertIn("MUTABLE_IMAGES = {'postgres:16': 3, 'python:3.11-slim': 1}", gate,
                      'the mutable base-image inventory the plan quotes moved')
        flat_plan = flat(read(PLAN))
        self.assertIn('four mutable base-image references', flat_plan)
        self.assertIn('not part of the repository', flat_plan)


class RecordedAbsenceTests(SimpleTestCase):
    def test_nothing_records_a_dump_or_a_restore(self):
        self.assertEqual(settings.LOGGING, {}, 'a logging configuration appeared')
        importers = sorted(str(path.relative_to(ROOT)) for path in project_modules()
                           if re.search(r'^\s*(import logging|from logging)', read(path), re.M))
        self.assertEqual(importers, [], 'an application module started logging')
        self.assertEqual(read(DRILL).count('listed.stdout'), 0)
        models = [model for model in apps.get_models() if model._meta.app_label in PROJECT_APPS]
        self.assertEqual(len(models), PROJECT_MODEL_COUNT, 'the project model count moved')
        named = sorted(model.__name__ for model in models
                       if re.search(r'(?i)backup|dump|archive|recover', model.__name__))
        self.assertEqual(named, [], 'a model named like a backup record appeared')
        commands = sorted(path.name for path in command_modules())
        self.assertEqual(len(commands), COMMAND_COUNT, 'the management command count moved')
        self.assertEqual([name for name in commands
                          if re.search(r'(?i)backup|dump|restore|recover|archive', name)], [],
                         'a backup or restore command appeared')
        flat_plan = flat(read(PLAN))
        self.assertIn('`LOGGING` is `{}`', flat_plan)
        self.assertIn('daroobank/test_secret_rotation_plan.py', flat_plan)


class PinnedInventoryTests(SimpleTestCase):
    def test_the_schema_pins_a_backup_record_would_move(self):
        mfa = read(MFA_PLAN)
        audit = read(READ_AUDIT_PLAN)
        for path, text in ((MFA_PLAN, mfa), (READ_AUDIT_PLAN, audit)):
            with self.subTest(suite=path.name):
                self.assertIn("CURRENT_SCHEMA = {'tables': 33, 'columns': 279, 'indexes': 111, "
                              "'constraints': 138,\n                  'foreign keys': 50, "
                              "'applied migrations': 32}", text,
                              'the measured schema a new table would move changed on its own')
        self.assertIn("'tables': 33, 'columns': 283, 'indexes': 113", audit,
                      'the read-audit prototype measurement the plan prices option C against moved')
        names = re.findall(r"'([^']+)'", read(NO_READ_AUDIT).split('SCHEMA_TABLES = (', 1)[1]
                           .split(')', 1)[0])
        self.assertEqual(len(names), SCHEMA_TABLE_COUNT,
                         'the exact table inventory a new table would move changed')
        self.assertEqual(len([name for name in names
                              if re.search(r'(?i)backup|dump|archive|recover', name)]), 0)
        flat_plan = flat(read(PLAN))
        self.assertIn('33 tables', flat_plan)
        self.assertIn('279', flat_plan)
        self.assertIn('283 columns and 113 indexes', flat_plan)

    def test_the_attribution_and_rollback_pins_a_backup_record_would_move(self):
        text = read(ATTRIBUTION)
        unattributed = re.findall(r"'([^']+)':", text.split('UNATTRIBUTED = {', 1)[1].split('}', 1)[0])
        self.assertEqual(tuple(unattributed), UNATTRIBUTED_MODELS,
                         'the unattributed-model inventory moved')
        self.assertEqual(len(unattributed), len(UNATTRIBUTED_MODELS))
        self.assertEqual(PROJECT_MODEL_COUNT - len(unattributed), ATTRIBUTED_MODEL_COUNT)
        populated = re.findall(r"'([\w]+)': (\d+),",
                               read(ROLLBACK_DRILL).split('POPULATED = {', 1)[1].split('}', 1)[0])
        self.assertEqual(len(populated), POPULATED_TABLES,
                         'the rollback drill fixture the plan prices option C against moved')
        self.assertEqual(sum(int(rows) for _table, rows in populated), POPULATED_ROWS)
        counts = re.search(r'MIGRATION_COUNTS = \{([^}]*)\}', read(MFA_PLAN)).group(1)
        self.assertEqual(sum(int(number) for number in re.findall(r': (\d+)', counts)),
                         MIGRATION_MODULES, 'the project migration count moved')
        self.assertEqual(len(list(ROOT.glob('*/migrations/0*.py'))), MIGRATION_MODULES)
        self.assertIn('setval(pg_get_serial_sequence', read(ADR_0225),
                      'the sequence lesson a restore depends on disappeared from ADR 0225')

    def test_the_document_and_module_pins_the_plan_moves_are_recounted(self):
        links = read(DOCUMENT_LINKS)
        self.assertEqual(constant(links, 'DOCUMENT_COUNT'), DOCS_MARKDOWN_COUNT + 1,
                         'the document count the link suite pins is not README plus docs/')
        self.assertEqual(constant(links, 'ADR_COUNT'),
                         len(list((ROOT / 'docs' / 'ARCHITECTURE_DECISIONS')
                                  .glob('[0-9][0-9][0-9][0-9]-*.md'))))
        self.assertEqual(constant(links, 'SUITE_LINE_COUNT'),
                         len([record for record in
                              (ROOT / 'docs' / 'ARCHITECTURE_DECISIONS').glob('[0-9][0-9][0-9][0-9]-*.md')
                              if re.search(r'^Suite:', read(record), re.M)]),
                         'the Suite: line count is not the number of records that name a suite')
        for suite in (MFA_PLAN, ROOT / 'daroobank' / 'test_secret_rotation_plan.py'):
            with self.subTest(suite=suite.name):
                self.assertEqual(constant(read(suite), 'TEST_MODULE_COUNT'),
                                 len([path for path in python_modules() if is_test_module(path)]) - 1,
                                 'the test-module count these suites pin is not the tree minus one')


class PlanConsequenceTests(SimpleTestCase):
    def test_the_neighbouring_documents_name_the_plan_and_what_it_measured(self):
        for path, phrases in ((GUIDE, ['BACKUP_RECOVERY_PLAN.md', '0232-backup-recovery-plan.md']),
                              (RUNBOOK, ['BACKUP_RECOVERY_PLAN.md', '0232-backup-recovery-plan.md']),
                              (EVIDENCE, ['BACKUP_RECOVERY_PLAN.md']),
                              (SECURITY, ['BACKUP_RECOVERY_PLAN.md']),
                              (DEPLOYMENT, ['BACKUP_RECOVERY_PLAN.md']),
                              (TESTING, ['test_backup_recovery_plan.py']),
                              (CHANGELOG, ['BACKUP_RECOVERY_PLAN.md'])):
            text = read(path)
            for phrase in phrases:
                with self.subTest(document=path.name, phrase=phrase):
                    self.assertIn(phrase, text,
                                  'a document that asks for backup and recovery stopped naming the '
                                  'plan that answers it')

    def test_the_record_states_its_decision_and_its_limits(self):
        text = read(ADR)
        lines = text.splitlines()
        self.assertTrue(lines[0].startswith('# 0232 — '), 'the record lost its numbered heading')
        self.assertIn('Date: 2026-11-26', text)
        self.assertIn('Status: accepted', text)
        self.assertRegex(text, re.compile(r'^Suite: `daroobank/test_backup_recovery_plan\.py`',
                                          re.M))
        self.assertEqual(sections(text), ['Context', 'Decision', 'Measured behavior', 'Red checks',
                                          'Consequences', 'Limitations'],
                         'the record lost a house section')
        decisions = section(text, 'Decision')
        self.assertEqual(len(re.findall(r'^\d+\. \*\*', decisions, re.M)), 4,
                         'the numbered decisions in the record changed')
        self.assertIn('**Nothing was implemented.**', decisions)
        limitations = section(text, 'Limitations')
        self.assertEqual(len(re.findall(r'^- ', limitations, re.M)), 6,
                         'the record stopped limiting itself')
        for phrase in ('The replay was performed once, on a fixture',
                       'No option was evaluated for security or lawfulness',
                       'The prices are counted, not run',
                       'Custody was not measured because there is none to measure',
                       'The live-database shape was exercised mechanically'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, limitations)
        red = section(text, 'Red checks')
        self.assertEqual(len(re.findall(r'^\| ', red, re.M)) - 2, 20,
                         'the record stopped listing every red check it ran')
        self.assertIn('Twenty mutations were applied to a byte-identical backup', red)
        self.assertIn('All twenty were caught', red)
        self.assertIn('DAROOBANK_RESTORE_TESTS=1', red,
                      'the record stopped saying the replay ran during the red checks')
        index = read(ADR_INDEX)
        bullet = [line for line in index.splitlines() if '0232-backup-recovery-plan.md' in line]
        self.assertEqual(len(bullet), 1,
                         'the record is not listed once in the index that is supposed to list it')
        for phrase in ('five documents ask for backup and recovery', 'eight open decisions',
                       'no implementation'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, bullet[0], 'the index bullet stopped summarizing the record')
        self.assertIn('../BACKUP_RECOVERY_PLAN.md', text,
                      'the record stopped linking the plan it records')


class NothingImplementedTests(SimpleTestCase):
    def test_no_backup_control_exists_while_the_plan_says_so(self):
        flat_plan = flat(read(PLAN))
        self.assertIn('no backup control was implemented and reverted', flat_plan)
        for phrase in ('**Nothing is implemented.**', 'No custodian exists anywhere'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_plan)
        script = guide_script()
        for token in LIVE_RESTORE_TOKENS:
            self.assertNotIn(token, script, 'the documented sequence became a live restore')
        self.assertNotIn('BACKUP', read(SETTINGS), 'settings grew a backup configuration')
        self.assertNotIn('RESTORE', read(SETTINGS))
        self.assertEqual([line for line in read(REQUIREMENTS_IN).splitlines() if line.strip()],
                         DIRECT_REQUIREMENTS, 'a backup dependency was added to the lock')
        self.assertEqual(len(read(REQUIREMENTS).splitlines()), REQUIREMENTS_LINES,
                         'the hash-pinned lock grew')
        self.assertEqual(read(WORKFLOW).count('secrets.'), 0)
        self.assertEqual(sorted(str(path.relative_to(ROOT)) for path in project_modules()
                                if re.search(BACKUP_WORDS, path.name)), RESTORE_NAMED_MODULES,
                         'a module named like a backup control appeared')
        self.assertEqual(settings.SECRET_KEY_FALLBACKS, [],
                         'an unrelated key decision landed while this one was still open')


@skipUnless(os.environ.get('DAROOBANK_RESTORE_TESTS') == '1' and shutil.which('pg_dump')
            and shutil.which('pg_restore'),
            'Optional replay of the measured stale-archive restore needs DAROOBANK_RESTORE_TESTS=1 '
            'and matching PostgreSQL clients on PATH')
@override_settings(DEBUG=True)
class StaleArchiveReplayTests(TransactionTestCase):
    """Re-perform the replay the plan quotes, on synthetic data in throwaway databases."""

    def fixture(self):
        from catalog.identity import digest, package_snapshot, review_package
        from catalog.models import IdentityPackageDraft, IdentityPackageReview
        from catalog.test_identity import ALL, build, user
        author = user('synthetic-restore-author', *ALL)
        reviewer = user('synthetic-restore-reviewer', *ALL)
        package = build(author)[-1]
        graph_hash = digest(package_snapshot(package))
        event = review_package(actor=reviewer, package_id=package.pk, decision='defer',
                               reason='دلیل ساختگی برای تمرین بازگردانی', expected_review=0,
                               expected_graph_hash=graph_hash)
        self.assertEqual(IdentityPackageDraft.objects.count(), 1)
        self.assertEqual(IdentityPackageReview.objects.count(), 1)
        from .synthetic_restore_fixture import build_cross_domain_fixture, verify_cross_domain_fixture
        build_cross_domain_fixture(author, reviewer)
        verify_cross_domain_fixture()
        return author, reviewer, package, event, graph_hash

    def later_fact(self, author, reviewer):
        """One business fact written after the archive that is about to be restored."""
        from catalog.identity import digest, package_snapshot, review_package
        from catalog.test_identity import build
        package = build(author)[-1]
        review_package(actor=reviewer, package_id=package.pk, decision='further_review',
                       reason='دلیل ساختگی پس از نخستین نسخهٔ پشتیبان', expected_review=0,
                       expected_graph_hash=digest(package_snapshot(package)))

    def environment(self):
        config = connection.settings_dict
        source = config['NAME']
        child = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'TMPDIR')
                 if key in os.environ}
        child.update(DAROOBANK_DEBUG='1', POSTGRES_DB=source, POSTGRES_HOST=str(config['HOST']),
                     POSTGRES_PORT=str(config['PORT']), POSTGRES_USER=str(config['USER']),
                     PGHOST=str(config['HOST']), PGPORT=str(config['PORT']),
                     PGUSER=str(config['USER']), PGDATABASE=source)
        if config.get('PASSWORD'):
            child['POSTGRES_PASSWORD'] = str(config['PASSWORD'])
            child['PGPASSWORD'] = str(config['PASSWORD'])
        sslmode = config.get('OPTIONS', {}).get('sslmode')
        if sslmode:
            child['POSTGRES_SSLMODE'] = str(sslmode)
            child['PGSSLMODE'] = str(sslmode)
        return source, child

    def runner(self, child):
        def run(command, env=None):
            started = time.monotonic()
            done = subprocess.run(command, cwd=ROOT, env=env or child, stdin=subprocess.DEVNULL,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90,
                                  check=False)
            return done, time.monotonic() - started
        return run

    def test_a_stale_archive_passes_every_verification_the_repository_has(self):
        import psycopg
        self.assertTrue(getattr(settings, 'DAROOBANK_RESTORE_ISOLATED', False),
                        'Use restore_test_settings')
        self.assertEqual(connection.vendor, 'postgresql')
        author, reviewer, package, event, graph_hash = self.fixture()
        source, child = self.environment()
        self.assertRegex(source, r'^test_daroobank_restore_[0-9a-f]{32}$')
        run = self.runner(child)
        target = f'test_daroobank_restore_target_{uuid4().hex}'
        created = False
        config = connection.settings_dict

        def params(dbname):
            options = {'dbname': dbname, 'host': config['HOST'], 'port': config['PORT'],
                       'user': config['USER'], 'password': config.get('PASSWORD') or '',
                       'connect_timeout': 5}
            if config.get('OPTIONS', {}).get('sslmode'):
                options['sslmode'] = config['OPTIONS']['sslmode']
            return options

        def counts(dbname):
            with psycopg.connect(**params(dbname)) as db, db.cursor() as cursor:
                found = {}
                cursor.execute("SELECT COUNT(*) FROM information_schema.tables "
                               "WHERE table_schema = 'public'")
                found['public tables'] = cursor.fetchone()[0]
                for table, key in (('catalog_identitypackagedraft', 'packages'),
                                   ('catalog_identitypackagereview', 'reviews'),
                                   ('auth_user', 'accounts'), ('django_session', 'sessions'),
                                   ('django_migrations', 'applied migrations')):
                    cursor.execute(f'SELECT COUNT(*) FROM public.{table}')
                    found[key] = cursor.fetchone()[0]
                return found

        try:
            with connection.cursor() as cursor:
                cursor.execute(f'CREATE DATABASE {connection.ops.quote_name(target)}')
            created = True
            with tempfile.TemporaryDirectory(prefix='daroobank-stale-replay-') as directory:
                self.assertEqual(stat.S_IMODE(os.stat(directory).st_mode), 0o700)
                stale = Path(directory) / 'stale.dump'
                os.close(os.open(stale, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
                dumped, _seconds = run(['pg_dump', '--no-password', '--format=custom', '--no-owner',
                                        '--no-acl', '--file', str(stale), '--dbname', source])
                self.assertEqual(dumped.returncode, 0, 'Replay pg_dump failed')
                self.assertEqual(stat.S_IMODE(stale.stat().st_mode), 0o600)
                listed, _seconds = run(['pg_restore', '--list', '--no-password', '--', str(stale)])
                self.assertEqual(listed.returncode, 0, 'Replay archive listing failed')
                header = listed.stdout.decode()
                stamps = [line.strip() for line in header.splitlines()
                          if 'Archive created at' in line]
                self.assertEqual(len(stamps), 1)
                # The archive's own inventory: no privileges, and every credential table.
                kinds = toc_kinds(header)
                self.assertEqual(sum(kinds.values()), REPLAY['toc entries'],
                                 f'TOC kinds {kinds} do not add up to the measured entry count')
                self.assertEqual(kinds.get('TABLE'), REPLAY['tables'])
                self.assertEqual(kinds.get('TABLE DATA'), REPLAY['table data'])
                self.assertEqual(kinds.get('SEQUENCE'), REPLAY['sequences'])
                self.assertEqual(kinds.get('SEQUENCE SET'), REPLAY['sequence sets'])
                self.assertEqual(kinds.get('INDEX'), REPLAY['indexes'])
                self.assertEqual(kinds.get('CONSTRAINT'), REPLAY['constraints'])
                self.assertEqual(kinds.get('FK CONSTRAINT'), REPLAY['foreign key constraints'],
                                 f'constraint kinds {kinds} moved')
                self.assertEqual(sum(kinds.get(kind, 0) for kind in PRIVILEGE_KINDS),
                                 REPLAY['acl entries'],
                                 'a --no-owner --no-acl dump started carrying privileges')
                self.assertEqual(kinds.get('unparsed', 0), 0, f'unparsed TOC lines in {kinds}')
                self.assertIn(f"TOC Entries: {REPLAY['header toc entries']}", header)
                for table in CREDENTIAL_TABLE_DATA:
                    with self.subTest(table=table):
                        self.assertRegex(header, rf'TABLE DATA \S* ?{table}\b',
                                         'the archive stopped carrying a credential table')
                self.assertEqual(counts(source)['packages'], REPLAY['stale packages'])

                self.later_fact(author, reviewer)
                after = counts(source)
                self.assertEqual(after['packages'], REPLAY['source packages'],
                                 'the later fact was not written, so the replay proves nothing')
                self.assertEqual(after['reviews'], REPLAY['source reviews'])

                fresh = Path(directory) / 'fresh.dump'
                os.close(os.open(fresh, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
                dumped, _seconds = run(['pg_dump', '--no-password', '--format=custom', '--no-owner',
                                        '--no-acl', '--file', str(fresh), '--dbname', source])
                self.assertEqual(dumped.returncode, 0, 'Replay second pg_dump failed')
                listed_fresh, _seconds = run(['pg_restore', '--list', '--no-password', '--',
                                              str(fresh)])
                self.assertEqual(listed_fresh.returncode, 0)
                fresh_stamps = [line.strip() for line in listed_fresh.stdout.decode().splitlines()
                                if 'Archive created at' in line]
                # The two archives differ only by their bytes: the stamp cannot tell them apart.
                self.assertNotEqual(stale.read_bytes(), fresh.read_bytes(),
                                    'two dumps of one database were byte-identical')
                self.assertEqual(fresh_stamps, stamps,
                                 'the archive stamp became able to distinguish two dumps taken in '
                                 'the same second, which closes the freshness gap the plan prices')

                restored_env = {**child, 'POSTGRES_DB': target, 'PGDATABASE': target,
                                'SYNTHETIC_PACKAGE_ID': str(package.pk),
                                'SYNTHETIC_REVIEW_ID': str(event.pk),
                                'SYNTHETIC_GRAPH_HASH': graph_hash}
                restored, _seconds = run(['pg_restore', '--no-password', '--exit-on-error',
                                          '--single-transaction', '--no-owner', '--no-acl',
                                          '--dbname', target, '--', str(stale)])
                self.assertEqual(restored.returncode, 0, 'Replay stale-archive restore failed')
                self.assertEqual(restored.stdout, b'', 'a restore started printing to stdout')
                self.assertEqual(restored.stderr, b'', 'a restore started printing to stderr')
                restored_counts = counts(target)
                for key, value in (('public tables', REPLAY['public tables']),
                                   ('applied migrations', REPLAY['applied migrations']),
                                   ('accounts', REPLAY['accounts']),
                                   ('sessions', REPLAY['sessions']),
                                   ('packages', REPLAY['stale packages']),
                                   ('reviews', REPLAY['stale reviews'])):
                    with self.subTest(count=key):
                        self.assertEqual(restored_counts[key], value,
                                         f'the stale archive restored an unexpected {key} count')

                # The four verifications the drill runs, against an archive missing a later fact.
                script = (
                    "import os; from daroobank.synthetic_restore_fixture import "
                    "verify_identity_fixture, verify_cross_domain_fixture, verify_post_restore_writes; "
                    "verify_identity_fixture(int(os.environ['SYNTHETIC_PACKAGE_ID']), "
                    "int(os.environ['SYNTHETIC_REVIEW_ID']), os.environ['SYNTHETIC_GRAPH_HASH']); "
                    "verify_cross_domain_fixture(); verify_post_restore_writes()"
                )
                for args in (['check'], ['migrate', '--check'], ['inspect_postgresql_schema'],
                             ['shell', '-c', script]):
                    check, _seconds = run([sys.executable, 'manage.py', *args], restored_env)
                    with self.subTest(verification=args[0]):
                        self.assertEqual(check.returncode, 0,
                                         'a check that passed on a stale archive now fails, so the '
                                         'plan has to be re-measured')
                        self.assertEqual(check.stderr, b'')
                self.assertEqual(counts(source)['packages'], REPLAY['source packages'],
                                 'the missing fact came back on its own')

                # The undocumented shape: a second restore into the database already restored.
                again, _seconds = run(['pg_restore', '--no-password', '--exit-on-error',
                                       '--single-transaction', '--no-owner', '--no-acl',
                                       '--dbname', target, '--', str(stale)])
                self.assertNotEqual(again.returncode, 0,
                                    'restoring over a populated database started succeeding without '
                                    '--clean, which changes option E')
                self.assertIn(b'already exists', again.stderr)
                clean, _seconds = run(['pg_restore', '--no-password', '--clean', '--if-exists',
                                       '--exit-on-error', '--single-transaction', '--no-owner',
                                       '--no-acl', '--dbname', target, '--', str(stale)])
                self.assertEqual(clean.returncode, 0,
                                 'the --clean --if-exists shape the plan measured stopped working')
                self.assertEqual(clean.stderr, b'')
                self.assertEqual(counts(target), restored_counts,
                                 'a --clean restore changed what the target holds')
                for args in (['check'], ['migrate', '--check']):
                    check, _seconds = run([sys.executable, 'manage.py', *args], restored_env)
                    with self.subTest(verification=args[0]):
                        self.assertEqual(check.returncode, 0)
        finally:
            # Only the database this test created is ever removed.
            if created:
                connection.close()
                subprocess.run(['dropdb', '--no-password', '--if-exists', target], cwd=ROOT,
                               env=child, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=90, check=False)
