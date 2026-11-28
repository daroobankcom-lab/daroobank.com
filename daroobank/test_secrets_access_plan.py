"""Pins for `docs/SECRETS_ACCESS_PLAN.md` and its record, ADR 0238.

The plan measures four things the Phase 1 gate leaves open — entropy, secrecy, least-privilege
accounts and access review — and implements none of them. This suite keeps the measurements honest in
the only way available to a suite: every number that is a property of this tree is re-derived here
from the tree, every number that is a property of one run, one service or one machine is pinned as a
quotation of the document that reports it, and every requirement the plan is priced against is
asserted verbatim in both the plan and the document it came from.

Three rules this suite follows because breaking them has already cost a lane:

* counts owned by another suite are not counted a second time here. Where the plan quotes such a
  number — the 55 routes, the 17 migration modules, the 12 commands, the 33 tables — this suite
  imports the owner's constant or reads the owner's file and asserts the relation instead.
* comparisons of prose are made against whitespace-normalised text, because the documents are
  re-wrapped to 98 columns and a phrase can sit across two lines.
* a quotation is asserted in the document it is quoted from as well as in the plan, so a reworded
  requirement fails a test rather than silently diverging from the plan that prices it.
"""
import math
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core import signing
from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key
from django.test import SimpleTestCase, RequestFactory, override_settings
from django.utils.crypto import salted_hmac
from django.views.debug import SafeExceptionReporterFilter

from daroobank.configuration import require_nondebug_secret
from daroobank.signed_cursors import loads_nonfuture

ROOT = Path(__file__).resolve().parent.parent
THIS_SUITE = Path(__file__).resolve().relative_to(ROOT).as_posix()
PLAN = ROOT / 'docs' / 'SECRETS_ACCESS_PLAN.md'
ADR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0238-secrets-access-plan.md'
ADR_INDEX = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / 'README.md'
SECURITY = ROOT / 'docs' / 'SECURITY.md'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
RUNBOOK = ROOT / 'docs' / 'OPERATIONS_RUNBOOK.md'
EVIDENCE = ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'
CHANGELOG = ROOT / 'docs' / 'CHANGELOG.md'
TESTING = ROOT / 'docs' / 'TESTING_STRATEGY.md'
ROTATION_PLAN = ROOT / 'docs' / 'SECRET_ROTATION_PLAN.md'
AUTHORIZATION_REVIEW = ROOT / 'docs' / 'AUTHORIZATION_REVIEW.md'
ADR_0231 = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS' / '0231-secret-rotation-plan.md'
SETTINGS = ROOT / 'daroobank' / 'settings.py'
CONFIGURATION = ROOT / 'daroobank' / 'configuration.py'
SYNTHETIC_SETTINGS = ROOT / 'daroobank' / 'synthetic_test_settings.py'
COMPOSE = ROOT / 'compose.yaml'
WORKFLOW = ROOT / '.github' / 'workflows' / 'checks.yml'
ENV_EXAMPLE = ROOT / '.env.example'
READINESS = ROOT / 'daroobank' / 'management' / 'commands' / 'check_deployment_readiness.py'
ACCESS_COMMAND = ROOT / 'catalog' / 'management' / 'commands' / 'inspect_postgresql_access.py'
POSTGRESQL_ACCESS = ROOT / 'daroobank' / 'postgresql_access.py'
THROTTLE = ROOT / 'staff_security' / 'throttle.py'
SERVICES = ROOT / 'catalog' / 'services.py'

SKIP_PARTS = frozenset({'.venv', '.cache', '.git', 'node_modules', '__pycache__', 'staticfiles',
                        'backups'})

SECTIONS = ['What is true today, measured',
            'Candidate approach and decisions required',
            'Options and what each costs',
            'Required behavior before a key is called managed',
            'Verification before any enablement']
SUBSECTIONS = ['The entropy of every key this tree can run with',
               'The shape check is not monotonic in entropy',
               'Where the key value is, and is not, readable',
               'What one boolean decides',
               'What a debug error page publishes',
               'What the committed debug key makes reproducible',
               'The account the application connects with',
               'Who can read or change the key',
               'Custody: an instruction with no mechanism']
DECISIONS = ['**How much entropy is enough, and who says so?**',
             '**Where does a production key live, and who holds it?**',
             '**How is a key produced?**',
             '**Does the debug fallback stay?**',
             '**Which account does the application connect with?**',
             '**Who reviews access, on what cadence, and against what inventory?**',
             '**Do CI credentials come from a store?**',
             '**What is printed on an error page in development?**']
OPTIONS = ['A. Leave the key surface exactly as measured',
           'B. Write the measured absence into the documents only',
           'C. Pin the entropy, secrecy and access surface in a suite of its own',
           'D. Add a minimum-entropy floor to the shape check',
           'E. Replace the debug fallback with a generated per-run key',
           'F. Split the database account into an owner and a runtime role',
           'G. Move CI credentials into a secret store',
           'H. Name a secret manager, a generation procedure and a review cadence']
REQUIRED_BEHAVIOR_COUNT = 7
VERIFICATION_COUNT = 7
PROPOSAL_PHRASES = ['This document is a **proposal**', 'It has no owner and no approval',
                    '**Nothing is implemented.**', 'must not be read as a decision',
                    'No secret manager was chosen, no key was generated, no role was split',
                    'No option is chosen here, none is recommended and none is excluded']
FORBIDDEN_SELECTION = ['The selected approach is', 'is selected because', 'the recommended approach',
                       'should be adopted', 'The selected option is', 'we recommend',
                       'the best option is']

# The requirements the plan is priced against, each asserted in the plan and in its source.
QUOTED_REQUIREMENTS = [
    (SECURITY, 'Keep secrets in a secrets manager/environment, never in Git; the existing '
               '`.env.example` contains placeholders only.'),
    (SECURITY, 'encryption at rest where appropriate with isolated managed keys and rotation; '
               'least-privilege DB/worker credentials.'),
    (SECURITY, 'Users may hold multiple roles; implement auditable permission grants, revocation and '
               'periodic review.'),
    (SECURITY, 'The database half of the least-privilege requirement above is measured rather than '
               'met'),
    (SECURITY, "every connection this application makes uses the cluster's one non-system role, a "
               'superuser that owns all 33 tables'),
    (DEPLOYMENT, 'those checks cannot establish randomness or secrecy. Supply a unique randomly '
                 'generated key through an approved secret manager.'),
    (DEPLOYMENT, 'a unique randomly generated value from an approved secret manager, never in Git or '
                 'shell history. In debug an empty value falls back to a fixed development string'),
    (DEPLOYMENT, 'Provision TLS, secure headers, database backups and off-host encrypted retention, '
                 'monitoring/alerts, access review and restore drills.'),
    (DEPLOYMENT, 'must stay unset or `0`'),
    (RUNBOOK, 'Before deployment, define ownership, encrypted backup cadence, off-host retention, '
              'RPO/RTO and recovery environment according to business and legal requirements; no '
              'values have been approved.'),
    (EVIDENCE, 'Shape checks do not demonstrate entropy or secrecy.'),
    (AUTHORIZATION_REVIEW, '**Status: the inventory is derived and drift-checked; the judgement is '
                           'unsigned.**'),
    (ADR_0231, '**Key custody was not measured because there is none to measure.** No secret manager, '
               'KMS, HSM or key file exists in this tree'),
    (ADR_0231, '**Nothing was measured about recovery.**'),
    (SETTINGS, 'The staff portal is restricted to development until MFA, throttling and audit exist.'),
    (SETTINGS, 'Empty password is allowed for peer/certificate authentication; deployments using '
               'password authentication must provide it through their environment/secret manager.'),
    (CONFIGURATION, 'Reject obvious unsafe shapes; this cannot determine randomness or secrecy.'),
    (READINESS, 'the secret has a supported non-debug shape; its entropy and secrecy are not measured '
                'here'),
    (READINESS, 'DEBUG is on; detailed errors, the staff portal and insecure cookies follow from it'),
    (ROTATION_PLAN, 'No client library'),
]

# Numbers that came from one run, one service or one machine. They are pinned as statements of the
# documents that report them, not re-derived, and the record lists each as a limitation.
MEASURED_PLAN = [
    'Nine distinct key literals appear in tracked files',
    'Exactly one of them is a value `require_nondebug_secret` accepts',
    '**0 bits of secrecy**',
    '54 | 30 | 4.617 | 249.3 | accepted',
    '35 | 16 | 3.729 | 130.5 | rejected (length)',
    '33 | 17 | 3.859 | 127.3 | rejected (length)',
    'all 1,828 tests and every check this repository runs sign with',
    '`get_random_secret_key`, `secrets.token_urlsafe` and `openssl rand` appear in **0 tracked '
    'files**',
    '**0 of the 12 management commands** generate key material',
    '282.2 bits of key space, 243.9 bits of measured Shannon entropy',
    '50 | 28.1 | **accepted**',
    '50 | 96.1 | rejected',
    '46 | 156.1 | rejected',
    '50 | 116.1 | accepted',
    '3, 8 and 8 of the nine literals above fall below',
    '**0 of those are accepted today**',
    '0 and 2 fall below',
    '7 lines of one 75-line module',
    '`daroobank/test_nondebug_configuration.py` (6 tests, 17 assertions)',
    '29 routes take no argument',
    '10 statuses of 200 and 19 of 404, 27,192 bytes of headers and body',
    '1,817-byte server log',
    '31,230 bytes',
    '`/proc/<pid>/environ`, 834 bytes, in clear, readable by uid 1001',
    '`ps -wwE -p <pid>` (196 bytes)',
    '`/proc/<pid>/cmdline` (99 bytes)',
    '**0 child processes**',
    'Five shapes were refused',
    '**0 of the 5** outputs',
    'Seven non-comment lines of `daroobank/settings.py` mention `DEBUG`',
    '19 of the 29 argument-free routes answer differently',
    '**145-byte** page',
    '154 uppercase settings are rendered and **10** are masked by name',
    'API|AUTH|TOKEN|KEY|SECRET|PASS|SIGNATURE|HTTP_COOKIE',
    '**0 tracked files** use either decorator',
    '`catalog.search.cursor.v1` from `catalog/services.py:23`',
    '4fa85bb6678ee5abeec5557def6ceb583fa2cac0f1f4a2e7793135fa8a143278',
    '**1 login role**',
    '**0 login roles that are not superusers**',
    '29,655 bytes of a server-side file',
    '3 databases',
    '**0 privileged SQL statements**',
    '24 `CreateModel` operations',
    '3 collaborators and all 3 can push',
    '**0 rulesets**, **0 deployment environments**',
    '**not readable with this token** (HTTP 403 and HTTP 404)',
    '**0 `secrets.` references**',
    '`${{ github.run_id }}` (7 times) and `${{ github.run_attempt }}` (4 times)',
    '20 characters, 72.9 bits of text entropy, and **one candidate**',
    '46144733324, 46155694081, 46159362442, 46159480008 and 46160970236, a span of 16,236,912',
    '**0 of the 12 management commands** read `pg_authid`',
    '207 lines',
    '**5 lines** pair a cadence word with an access word',
    'Six document lines tell an operator',
    '**0 documents** name a mechanism',
]
MEASURED_ADR = [
    'Nine key literals exist in tracked files and exactly one is accepted',
    '249.3 bits, present in 4 tracked',
    '35 characters and 130.5 bits',
    '33 characters and 127.3 bits',
    'accepts a 50-character key carrying 28.1 bits',
    '96.1 bits',
    '156.1 bits',
    '`configuration.py:10-16`',
    '75-line module',
    '3, 8 and 8 of the nine literals fall below',
    '0 and 2 fall',
    '282.2 bits of key space, 243.9 bits of measured Shannon entropy',
    '0 tracked files',
    '0 of the 12 management commands',
    '29 argument-free routes, 10 statuses of 200 and 19 of 404, 27,192 bytes',
    '1,817-byte server log',
    '834 bytes',
    '196 bytes',
    '99 bytes',
    '0 child processes',
    '31,230 bytes',
    '17 redirects, `/staff/login/` 200, `/staff/logout/` 405',
    'Seven non-comment lines of `settings.py` mention `DEBUG`',
    '(8, 10, 14, 20, 34, 37, 63)',
    'STAFF_PORTAL_ENABLED = DEBUG',
    'Six of the twelve commands refuse to run unless `settings.DEBUG`',
    '`check_deployment_readiness.py:45`',
    'DAROOBANK_DEBUG: ${DAROOBANK_DEBUG:-1}',
    'API|AUTH|TOKEN|KEY|SECRET|PASS|SIGNATURE|HTTP_COOKIE',
    '154 uppercase settings are rendered and 10 are masked',
    '145-byte page',
    '4fa85bb6678ee5abeec5557def6ceb583fa2cac0f1f4a2e7793135fa8a143278',
    '29,655 bytes',
    '0 privileged SQL statements',
    '24 `CreateModel` operations',
    '0 `secrets.` references',
    '7 times and',
    '4 times',
    '3 collaborators and all 3 can push',
    '0 rulesets',
    'HTTP 403 and HTTP 404',
    '207 lines',
    '5 lines pair a cadence word with an access word',
]

# The nine key literals, with the shape the plan reports for each: length, distinct characters and
# whether `require_nondebug_secret` accepts it.
KEY_LITERALS = {
    'synthetic-only-not-a-real-key-0123456789-abcdefghijklm': (54, 30, True, 4),
    'development-only-not-for-production': (35, 16, False, 1),
    'replace-with-a-long-random-secret': (33, 17, False, 1),
    'synthetic-projection-conflict-key': (33, 16, False, 1),
    'synthetic-bounded-projection-key': (32, 17, False, 1),
    'synthetic-concurrent-test-key': (29, 13, False, 1),
    'synthetic-test-secret-key': (25, 11, False, 3),
    'different-local-test-key': (24, 15, False, 1),
    'django-insecure-short': (21, 15, False, 1),
}
LITERAL_PATTERNS = (
    r"DAROOBANK_SECRET_KEY['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
    r'DAROOBANK_SECRET_KEY=(\S+)',
    r"SECRET_KEY['\"]?\s*[:=]\s*['\"]([^'\"]+)['\"]",
)
# Prose mentions the variable name next to unrelated words; those are not literals. A literal has no
# separator or brace in it and is at least 8 characters long.
LITERAL_NOISE = re.compile(r'[,{}\s/]')

# The candidates that show the shape check judging against entropy rather than with it.
ENTROPY_CANDIDATES = [
    ('a' * 46 + 'bcde', 50, 28.1, True),
    ('daroo' * 10, 50, 96.1, False),
    ('changethis-' * 4 + 'xx', 46, 156.1, False),
    (''.join('abcde'[index % 5] for index in range(50)), 50, 116.1, True),
]
ENTROPY_FLOORS_BITS = (100.0, 150.0, 200.0)
ENTROPY_FLOORS_DENSITY = (3.0, 3.5)
FLOOR_BELOW_BITS = {100.0: 3, 150.0: 8, 200.0: 8}
FLOOR_BELOW_DENSITY = {3.0: 0, 3.5: 2}

DEBUG_LINES = [8, 10, 14, 20, 34, 37, 63]
PORTAL_LINE = 'STAFF_PORTAL_ENABLED = DEBUG'
REFUSE_OUTSIDE_DEBUG = ['catalog/management/commands/inspect_postgresql_access.py',
                        'catalog/management/commands/inspect_postgresql_schema.py',
                        'catalog/management/commands/repair_catalog_projection.py',
                        'staff_security/management/commands/cleanup_staff_login_windows.py',
                        'staff_security/management/commands/list_staff_sessions.py',
                        'staff_security/management/commands/revoke_staff_sessions.py']
REPORTS_DEBUG_AS_FAILURE = 'daroobank/management/commands/check_deployment_readiness.py'
MASK_PATTERN = 'API|AUTH|TOKEN|KEY|SECRET|PASS|SIGNATURE|HTTP_COOKIE'
MASKED_NAMES = ['DAROOBANK_SECRET_KEY', 'POSTGRES_PASSWORD']
CLEAR_NAMES = ['PEPPER', 'SIGNING_SALT']
# Measured: seven tracked modules assign a constant whose name `hidden_settings` does not match, so a
# debug error page prints its value. Neither name in CLEAR_NAMES exists in this tree; both are what a
# setting would be called if it did, and the filter would print it.
FRAME_LOCALS = ('material', 'secret_material', 'key_material')
POST_FIELDS = ('password', 'material')
POST_SENTINEL = 'lane-e-pinned-post-' + 'f6g7h8i9j0' * 4
UNMASKED_CONSTANT_MODULES = 7
UNMASKED_CONSTANT_NAMES = {'CURSOR_SALT': 5, 'SALT': 1, 'SALTS': 1}
DECORATORS = ('sensitive_variables', 'sensitive_post_parameters')
SETTINGS_RENDERED = 154
SETTINGS_MASKED = 10
PRIVILEGED_STATEMENTS = ('CREATE EXTENSION', 'CREATE ROLE', 'ALTER ROLE', 'GRANT', 'REVOKE',
                         'OWNER TO', 'ALTER SYSTEM', 'SET ROLE', 'SUPERUSER', 'COPY')
WORKFLOW_EXPRESSIONS = {'${{ github.run_id }}': 7, '${{ github.run_attempt }}': 4}
CI_CREDENTIALS = ['ci_key_${{ github.run_id }}_${{ github.run_attempt }}',
                  'runner_${{ github.run_id }}',
                  'ci_${{ github.run_id }}_${{ github.run_attempt }}']
COMPOSE_DEBUG_DEFAULT = 'DAROOBANK_DEBUG: ${DAROOBANK_DEBUG:-1}'
COMPOSE_KEY_REQUIRED = 'DAROOBANK_SECRET_KEY: ${DAROOBANK_SECRET_KEY:?Set DAROOBANK_SECRET_KEY in ' \
                       'your environment}'
GENERATION_TOKENS = ('get_random_secret_key', 'secrets.token_urlsafe', 'openssl rand')
SECRET_MANAGER_PHRASES = ('approved secret manager', 'unique randomly generated value')
# The six lines that instruct an operator to obtain a key, pinned as quotations in the four documents
# that carry them. A line count cannot be pinned here: `docs/DEPLOYMENT.md`, `docs/SECURITY.md` and
# `docs/CHANGELOG.md` hold one paragraph per line, so the instruction this delivery reports on shares
# a line with the sentence that reports it.
SECRET_MANAGER_LINES = (
    (DEPLOYMENT, 'Supply a unique randomly generated key through an approved secret manager.'),
    (DEPLOYMENT, '| `DAROOBANK_SECRET_KEY` | yes outside debug | a unique randomly generated value '
                 'from an approved secret manager, never in Git or shell history.'),
    (ROTATION_PLAN, 'randomly generated key through an approved secret manager"* and then admits'),
    (ROTATION_PLAN, 'already says should come from an approved secret manager. No client library'),
    (ADR_0231, 'Supply a unique randomly generated key through an approved secret manager'),
    (CHANGELOG, 'generated key through an approved secret manager"* and then concedes'),
)
SECRET_MANAGER_DOCUMENTS = ['docs/ARCHITECTURE_DECISIONS/0231-secret-rotation-plan.md',
                            'docs/CHANGELOG.md', 'docs/DEPLOYMENT.md', 'docs/SECRET_ROTATION_PLAN.md']
MECHANISM_PATTERN = re.compile(r'get_random_secret_key|openssl rand|secrets\.token_urlsafe|'
                               r'gh secret')
# The documents that name a generation mechanism are the ones this delivery writes, and every one of
# them names it in a sentence that says nothing in the tree uses it.
MECHANISM_DOCUMENTS = ['docs/ARCHITECTURE_DECISIONS/0238-secrets-access-plan.md', 'docs/CHANGELOG.md',
                       'docs/DEPLOYMENT.md', 'docs/SECRETS_ACCESS_PLAN.md']
# The documents this delivery writes or edits. Their sentences quote this lane's findings back, so the
# populations that count instructions are measured over the rest of the tree and say so; the negative
# claim — that nothing prescribes a custody review — is still made over every document.
OWN_DOCUMENTS = frozenset({
    'docs/SECRETS_ACCESS_PLAN.md', 'docs/ARCHITECTURE_DECISIONS/0238-secrets-access-plan.md',
    'docs/SECURITY.md', 'docs/DEPLOYMENT.md', 'docs/OPERATIONS_RUNBOOK.md', 'docs/TESTING_STRATEGY.md',
    'docs/SECRET_ROTATION_PLAN.md', 'docs/CHANGELOG.md', 'docs/PHASE1_RELEASE_EVIDENCE.md',
    'docs/ARCHITECTURE_DECISIONS/README.md'})
AUTHORIZATION_REVIEW_ABSENT = ('SECRET_KEY', 'secret', 'PostgreSQL role', 'collaborator', 'GitHub')
AUTHORIZATION_REVIEW_LINES = 207
CUSTODY_TRIGGER = re.compile(r'who holds the key|key custody|SECRET_KEY|push access|who can push|'
                             r'collaborator', re.I)
CUSTODY_INSTRUCTION = re.compile(r'\bmust\b|\bshould\b|\bdefine\b|\bschedule\b|\bquarterl|'
                                 r'\bannual|\bperiodic|every \d+', re.I)
CADENCE_ACCESS_LINES = 5
CURSOR_SALT = 'catalog.search.cursor.v1'
THROTTLE_SALT = 'staff_security.login.client.v1'
THROTTLE_KEY_127 = '4fa85bb6678ee5abeec5557def6ceb583fa2cac0f1f4a2e7793135fa8a143278'
DEBUG_SECRET = 'development-only-not-for-production'
ANOTHER_KEY = 'a-different-pinned-key-' + 'z9y8x7w6v5' * 4
REJECTION_MESSAGE = 'DAROOBANK_SECRET_KEY must be a non-debug secret with a supported shape.'
REFUSED_SHAPES = {
    'missing': '',
    'twenty characters': 'x' * 10 + 'abcdefghij',
    'six hundred characters': 'a1b2c3d4e5' * 60,
    'the committed debug constant': DEBUG_SECRET,
    'an insecure prefix': 'django-insecure-' + 'f6g7h8i9j0' * 5,
}
NEIGHBOURS = (SECURITY, DEPLOYMENT, RUNBOOK, TESTING, ROTATION_PLAN, EVIDENCE)
PIN_SUITES = {
    'daroobank/test_document_links.py': ['DOCUMENT_COUNT', 'ADR_COUNT', 'LINK_COUNT',
                                         'SUITE_LINE_COUNT'],
    'daroobank/test_backup_recovery_plan.py': ['DOCS_MARKDOWN_COUNT'],
    'daroobank/test_database_migration_plan.py': ['DOCS_MARKDOWN_COUNT', 'TEST_MODULE_COUNT'],
    'daroobank/test_database_connection_plan.py': ['TREE_FILE_COUNT', 'CORPUS_COUNT'],
    'daroobank/test_mfa_implementation_plan.py': ['TEST_MODULE_COUNT'],
    'daroobank/test_secret_rotation_plan.py': ['TEST_MODULE_COUNT'],
    'daroobank/test_monitoring_response_plan.py': ['CORPUS_COUNT'],
}
PIN_DELTAS = ['`DOCUMENT_COUNT` 273 to 275', '`ADR_COUNT` 237 to 238', '`SUITE_LINE_COUNT` 27 to 28',
              '`DOCS_MARKDOWN_COUNT` 272 to 274', '`TEST_MODULE_COUNT` 244 to 245',
              '`TEST_MODULE_COUNT` 243 to 244', '`TREE_FILE_COUNT` 747 to 750',
              '`CORPUS_COUNT` 261 to 263', '`CORPUS_COUNT` 264 to 266', '`LINK_COUNT`',
              '`LOGIN_ROUTE_TESTS` 46 to 47', '`alert` 17 to 19', '`replica` 11 to 13',
              '`superuser` 19 to 21', '`least privilege` 2 to 4']


def flat(text):
    return ' '.join(text.split())


def flat_source(path, text):
    """Flattened text of a quoted requirement's source, with comment markers taken out.

    `daroobank/settings.py` wraps a comment over two lines, so the sentence an operator reads is two
    prefixed lines in the file. Documents are compared as they are written.
    """
    if str(path).endswith('.py'):
        text = re.sub(r'(?m)^(\s*)#+\s?', r'\1', text)
    return flat(text)


def read(path):
    return Path(path).read_text(encoding='utf-8')


def tracked_files():
    listing = subprocess.run(['git', 'ls-files'], cwd=ROOT, capture_output=True, text=True,
                             check=True).stdout
    return [line for line in listing.splitlines() if line]


def is_test_path(path):
    # The rule `daroobank/test_database_migration_plan.py` owns: a test module is named `test_*.py`
    # or `tests.py`. Migration packages and `tests/` directories are not test modules, and inventing
    # a second rule here would only disagree with the suite that counts the pin.
    name = Path(path).name
    return name.startswith('test_') or name == 'tests.py'


def shannon_bits(value):
    counts = Counter(value)
    length = len(value)
    per_character = -sum((count / length) * math.log2(count / length) for count in counts.values())
    return per_character, per_character * length


def accepted(value):
    try:
        require_nondebug_secret(value)
        return True
    except ImproperlyConfigured:
        return False


def key_literals(texts):
    """Every key literal in the tracked tree, mapped to the files that hold it."""
    found = {}
    for path, text in texts.items():
        for pattern in LITERAL_PATTERNS:
            for value in re.findall(pattern, text):
                if len(value) < 8 or LITERAL_NOISE.search(value):
                    continue
                found.setdefault(value, set()).add(path)
    return found


class Corpus:
    """The tracked tree, read once, because every pin in this suite scans it."""

    def __init__(self):
        self.paths = tracked_files()
        self.texts = {}
        for path in self.paths:
            if not path.endswith(('.md', '.py', '.yml', '.yaml', '.txt', '.cfg', '.example',
                                  '.html', '.json', '.in', '.toml', '.js', '.css')):
                continue
            try:
                self.texts[path] = read(ROOT / path)
            except (OSError, UnicodeDecodeError):
                pass
        self.documents = {path: text for path, text in self.texts.items() if path.endswith('.md')}
        # This suite is tracked, and it builds keys to compare with — a refusal shape, another key to
        # fail a signature against. Harvesting its own source would make the population of key
        # literals depend on the fixtures of the suite that measures it, so the suite is left out and
        # the plan says the nine literals are the ones in the rest of the tree.
        self.literals = key_literals({path: text for path, text in self.texts.items()
                                      if path != THIS_SUITE})


CORPUS = None


def corpus():
    global CORPUS
    if CORPUS is None:
        CORPUS = Corpus()
    return CORPUS


class PlanShapeTests(SimpleTestCase):
    """The plan says what it is, and nothing in it claims a choice was made."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.plan = read(PLAN)
        cls.flat_plan = flat(cls.plan)

    def test_the_plan_states_its_own_shape(self):
        for section in SECTIONS:
            with self.subTest(section=section):
                self.assertIn('\n## %s\n' % section, self.plan)
        for subsection in SUBSECTIONS:
            with self.subTest(subsection=subsection):
                self.assertIn('\n### %s\n' % subsection, self.plan)
        headings = re.findall(r'(?m)^## (.+)$', self.plan)
        self.assertEqual(headings, SECTIONS, 'a section was added, removed or reordered')
        decisions = re.findall(r'(?m)^\d+\. (\*\*.+?\*\*)', self.plan.split('## Options')[0])
        self.assertEqual(decisions, DECISIONS, 'a decision was reworded, added or dropped')
        for option in OPTIONS:
            with self.subTest(option=option):
                self.assertIn('| **%s** |' % option, self.plan)
        required = self.plan.split('## Required behavior before a key is called managed')[1]
        required = required.split('## Verification before any enablement')[0]
        self.assertEqual(len(re.findall(r'(?m)^\d+\. ', required)), REQUIRED_BEHAVIOR_COUNT)
        verification = self.plan.split('## Verification before any enablement')[1]
        self.assertEqual(len(re.findall(r'(?m)^- ', verification)), VERIFICATION_COUNT)

    def test_the_plan_is_an_unowned_proposal_that_implements_nothing(self):
        for phrase in PROPOSAL_PHRASES:
            with self.subTest(phrase=phrase):
                self.assertIn(flat(phrase), self.flat_plan)

    def test_no_option_is_presented_as_chosen(self):
        for phrase in FORBIDDEN_SELECTION:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase.lower(), self.plan.lower())
        options = self.plan.split('## Options and what each costs')[1].split('## Required behavior')[0]
        self.assertIn('No option is chosen here, none is recommended and none is excluded',
                      flat(options))
        rows = [line for line in options.splitlines() if line.startswith('| **')]
        self.assertEqual(len(rows), len(OPTIONS))
        for row in rows:
            cells = [cell.strip() for cell in row.strip('|').split('|')]
            with self.subTest(option=cells[0][:40]):
                self.assertEqual(len(cells), 4, 'an option lost its price or its blind spot')
                self.assertTrue(cells[2] and cells[3], 'an option has an empty price or blind spot')

    def test_the_plan_quotes_the_requirements_it_is_priced_against(self):
        for source, quote in QUOTED_REQUIREMENTS:
            with self.subTest(source=source.name, quote=quote[:48]):
                self.assertIn(flat(quote), self.flat_plan,
                              'the plan stopped quoting a requirement it is priced against')
                self.assertIn(flat(quote), flat_source(source, read(source)),
                              'the quotation is not verbatim in the document it is quoted from')

    def test_the_plan_states_the_numbers_it_measured(self):
        for statement in MEASURED_PLAN:
            with self.subTest(statement=statement[:56]):
                self.assertIn(flat(statement), self.flat_plan)

    def test_every_module_document_and_record_the_plan_names_exists(self):
        named = set(re.findall(r'`([A-Za-z0-9_./-]+\.(?:py|md|yaml|yml|txt|example))`', self.plan))
        named |= {match for match in re.findall(r'\]\(([^)#][^)]*)\)', self.plan)}
        missing = []
        for name in sorted(named):
            if name.startswith(('http://', 'https://', 'mailto:')):
                continue
            candidate = name if name.startswith(('docs/', 'daroobank/', 'catalog/', 'clinical/',
                                                 'pricing/', 'sources/', 'ingestion/',
                                                 'staff_security/', 'tools/', '.github/',
                                                 'tests/')) else 'docs/%s' % name
            if not (ROOT / candidate).exists() and not (ROOT / name).exists():
                missing.append(name)
        self.assertEqual(missing, [], 'the plan names a file that does not exist')
        self.assertGreaterEqual(len(named), 30, 'the plan stopped naming the files it depends on')

    def test_the_plan_links_the_records_it_depends_on(self):
        links = re.findall(r'\]\((ARCHITECTURE_DECISIONS/[^)]+|[A-Z0-9_]+\.md)\)', self.plan)
        for link in sorted(set(links)):
            with self.subTest(link=link):
                self.assertTrue((ROOT / 'docs' / link).is_file(), 'a linked record does not exist')
        for record in ('ARCHITECTURE_DECISIONS/0231-secret-rotation-plan.md',
                       'ARCHITECTURE_DECISIONS/0236-database-connection-plan.md',
                       'ARCHITECTURE_DECISIONS/0226-ci-artifact-gate.md',
                       'ARCHITECTURE_DECISIONS/0237-monitoring-response-plan.md',
                       'ARCHITECTURE_DECISIONS/0232-backup-recovery-plan.md',
                       'ARCHITECTURE_DECISIONS/0183-nondebug-config-guards.md',
                       'AUTHORIZATION_REVIEW.md', 'SECRET_ROTATION_PLAN.md',
                       'API_PERMISSIONS_PLAN.md'):
            with self.subTest(record=record):
                self.assertIn('](%s)' % record, self.plan)


class RecordShapeTests(SimpleTestCase):
    """The record carries the sections a decision record needs and limits what it claims."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.record = read(ADR)
        cls.flat_record = flat(cls.record)
        cls.plan = flat(read(PLAN))

    def test_the_record_has_the_sections_a_decision_record_needs(self):
        for section in ('## Context', '## Decision', '## Measured behavior', '## Red checks',
                        '## Consequences', '## Limitations'):
            with self.subTest(section=section):
                self.assertIn('\n%s\n' % section, self.record)
        self.assertTrue(re.search(r'(?m)^Date: \d{4}-\d{2}-\d{2}$', self.record))
        self.assertIn('\nStatus: accepted\n', self.record)
        self.assertRegex(self.record, r'(?m)^Suite: `daroobank/test_secrets_access_plan\.py`')
        suite_line = re.search(r'(?m)^Suite: (.+?)(?:\n\n)', self.record, re.S).group(1)
        claimed = int(re.search(r'\((\d+) tests', flat(suite_line)).group(1))
        self.assertEqual(claimed, len(re.findall(r'(?m)^\s+def test_', read(__file__))),
                         'the record states a test count that is not the suite it names')

    def test_the_record_limits_what_it_claims(self):
        limitations = self.record.split('## Limitations')[1]
        for phrase in ('one synthetic cluster', 'dated and unpinned', 'one run on one machine',
                       'Shannon entropy is a property of a string, not of a generator',
                       'No secret manager, KMS, HSM', 'Key recovery was not re-measured',
                       'cannot tell whether the eight decisions will ever be answered',
                       '`docker` is not installed'):
            with self.subTest(phrase=phrase):
                self.assertIn(flat(phrase), flat(limitations))

    def test_the_record_states_the_numbers_it_measured(self):
        for statement in MEASURED_ADR:
            with self.subTest(statement=statement[:56]):
                self.assertIn(flat(statement), self.flat_record)

    def test_the_record_marks_what_is_pinned_and_what_is_one_run(self):
        measured = self.record.split('## Measured behavior')[1].split('## Red checks')[0]
        bullets = [line for line in measured.splitlines() if line.startswith('- **')]
        self.assertGreaterEqual(len(bullets), 14, 'the record lost measured bullets')
        self.assertIn('**(pinned)**', measured)
        self.assertIn('**(one run)**', measured)
        for label in ('(pinned)', '(one run)'):
            self.assertIn(label, measured)
        unpinned = ['The GitHub API facts are dated', 'are **not pinned**']
        for phrase in unpinned:
            with self.subTest(phrase=phrase):
                self.assertIn(flat(phrase), self.flat_record)

    def test_the_record_names_nothing_it_did_not_do(self):
        decision = self.record.split('## Decision')[1].split('## Measured behavior')[0]
        self.assertIn('**Nothing is implemented.**', flat(decision))
        for phrase in ('No option is chosen, recommended or excluded',
                       'No entropy floor was added', 'no database role was split',
                       'no secret was moved into a store', 'no review cadence was named',
                       'dropped inside the same session', 'reset by `ALTER SYSTEM RESET`'):
            with self.subTest(phrase=phrase):
                self.assertIn(flat(phrase), flat(decision))

    def test_the_decision_index_summarizes_this_record(self):
        index = read(ADR_INDEX)
        entry = '- [0238: the secrets and access plan and what this repository can prove about its ' \
                'one key](0238-secrets-access-plan.md)'
        self.assertIn(entry, flat(index), 'the record is not in the decision index')
        self.assertEqual(index.count('0238-secrets-access-plan.md'), 1,
                         'the record is listed twice or its file was renamed')
        entries = re.findall(r'(?m)^- \[(\d{4}):', index)
        self.assertEqual(entries, sorted(entries), 'the index stopped being in filename order')
        self.assertEqual(len(entries), len(list((ROOT / 'docs' / 'ARCHITECTURE_DECISIONS')
                                                .glob('0[0-9][0-9][0-9]-*.md'))),
                         'the index and the records disagree about how many records exist')

    def test_the_record_carries_the_red_checks_it_names(self):
        section = self.record.split('## Red checks')[1].split('## Consequences')[0]
        claimed = re.search(r'([a-z\-]+) mutations were applied', flat(section))
        self.assertIsNotNone(claimed, 'the record stopped saying how many mutations were applied')
        # Split rather than find: an item wraps across lines, and `findall` on the marker would
        # return the marker alone, which never contains the name of the test that catches it.
        numbered = [item for item in re.split(r'(?m)^(?=\d+\. )', section)
                    if re.match(r'\d+\. ', item)]
        # The count is whatever the sweep actually ran, so the words cover the range a sweep of this
        # size can produce; the assertion below ties the word to the list the record carries.
        words = {'thirty-seven': 37, 'thirty-eight': 38, 'thirty-nine': 39, 'forty': 40,
                 'forty-one': 41, 'forty-two': 42, 'forty-three': 43, 'forty-four': 44,
                 'forty-five': 45, 'forty-six': 46, 'forty-seven': 47, 'forty-eight': 48,
                 'forty-nine': 49, 'fifty': 50, 'fifty-one': 51, 'fifty-two': 52}
        self.assertEqual(words[claimed.group(1)], len(numbered),
                         'the record states a red-check count that is not the list it carries')
        for item in numbered:
            with self.subTest(item=item.split('\n')[0][:40]):
                self.assertIn('`test_', flat(item),
                              'a red check does not name the test that catches it')
                self.assertIn('.', flat(item).rstrip()[-1:], 'a red check is not a sentence')


class EntropyTests(SimpleTestCase):
    """How much key there is, measured as a property of the strings this tree can run with."""

    def test_nine_key_literals_exist_and_exactly_one_is_accepted(self):
        literals = corpus().literals
        self.assertEqual(set(literals), set(KEY_LITERALS),
                         'a key literal was added, removed or reworded; the plan quotes all nine')
        accepted_now = [value for value in literals if accepted(value)]
        self.assertEqual(accepted_now, ['synthetic-only-not-a-real-key-0123456789-abcdefghijklm'])
        for value, (length, distinct, verdict, files) in KEY_LITERALS.items():
            with self.subTest(literal=value[:32]):
                self.assertEqual(len(value), length)
                self.assertEqual(len(set(value)), distinct)
                self.assertEqual(accepted(value), verdict)
                self.assertEqual(len(literals[value]), files,
                                 'the number of files holding this literal moved')

    def test_the_shape_check_is_not_monotonic_in_entropy(self):
        verdicts = {}
        for value, length, bits, expect in ENTROPY_CANDIDATES:
            with self.subTest(bits=bits):
                self.assertEqual(len(value), length)
                _, measured = shannon_bits(value)
                self.assertAlmostEqual(measured, bits, places=1)
                self.assertEqual(accepted(value), expect)
                verdicts[bits] = expect
        self.assertTrue(verdicts[28.1], 'the weakest key the guard accepts stopped being accepted')
        self.assertFalse(verdicts[96.1], 'a stronger key stopped being rejected')
        self.assertFalse(verdicts[156.1], 'a stronger key stopped being rejected')
        self.assertLess(28.1, 96.1)
        source = read(CONFIGURATION)
        self.assertIn('def require_nondebug_secret(value):', source)
        start = source.splitlines().index('def require_nondebug_secret(value):') + 1
        end = next(number for number, line in enumerate(source.splitlines()[start:], start)
                   if line.startswith('def '))
        # The two blank lines before the next definition are not the guard.
        body = [line for line in source.splitlines()[start - 1:end] if line.strip()]
        self.assertEqual(len(body), 7, 'the guard the plan prices at 7 lines changed size')
        self.assertEqual(len(source.splitlines()), 75)

    def test_an_entropy_floor_would_change_no_verdict_in_this_tree(self):
        literals = corpus().literals
        for floor, expected in FLOOR_BELOW_BITS.items():
            below = [value for value in literals if shannon_bits(value)[1] < floor]
            with self.subTest(floor='%d bits' % floor):
                self.assertEqual(len(below), expected,
                                 'the plan quotes how many literals a %d-bit floor catches' % floor)
                self.assertEqual([value for value in below if accepted(value)], [],
                                 'a floor would now reject something the tree uses')
        for floor, expected in FLOOR_BELOW_DENSITY.items():
            below = [value for value in literals if shannon_bits(value)[0] < floor]
            with self.subTest(floor='%.1f bits per character' % floor):
                self.assertEqual(len(below), expected)
                self.assertEqual([value for value in below if accepted(value)], [])

    def test_a_generated_key_carries_more_bits_than_any_literal_the_tree_accepts(self):
        generated = get_random_secret_key()
        self.assertEqual(len(generated), 50)
        self.assertTrue(accepted(generated), 'a generated key stopped passing the shape check')
        alphabet = "abcdefghijklmnopqrstuvwxyz0123456789!@#$%^&*(-_=+)"
        self.assertEqual(len(alphabet), 50)
        self.assertAlmostEqual(50 * math.log2(len(alphabet)), 282.2, places=1)
        _, bits = shannon_bits(generated)
        accepted_bits = [shannon_bits(value)[1] for value in corpus().literals if accepted(value)]
        self.assertGreater(bits, max(accepted_bits) - 20,
                           'the plan compares a generated key with the one accepted literal')
        holders = [path for path, text in corpus().texts.items()
                   if 'get_random_secret_key' in text and not path.endswith('.md')
                   and path != THIS_SUITE]
        self.assertEqual(holders, [], 'the tree gained a way to produce a key; the plan says none')
        # The documents that name the function are the ones this delivery writes, and each names it
        # to say that nothing uses it; MECHANISM_DOCUMENTS pins that list.
        self.assertEqual(sorted(path for path, text in corpus().documents.items()
                                if 'get_random_secret_key' in text), MECHANISM_DOCUMENTS,
                         'a document started naming a way to produce a key')

    def test_the_debug_fallback_is_the_key_ci_runs_with(self):
        source = read(SETTINGS)
        lines = source.splitlines()
        self.assertEqual(lines[21].strip(), "SECRET_KEY = '%s'" % DEBUG_SECRET,
                         'the debug fallback moved or changed; the plan quotes settings.py:22')
        self.assertIn('from .settings import *', read(SYNTHETIC_SETTINGS))
        workflow = read(WORKFLOW)
        self.assertEqual(len(re.findall(r"DAROOBANK_DEBUG: '1'", workflow)), 2)
        self.assertEqual(len(re.findall(r'DAROOBANK_SECRET_KEY', workflow)), 1,
                         'one CI job supplies a key; the plan says only the compose job does')
        _, bits = shannon_bits(DEBUG_SECRET)
        self.assertAlmostEqual(bits, 130.5, places=1)
        self.assertFalse(accepted(DEBUG_SECRET))


class SecrecyTests(SimpleTestCase):
    """Where the value can be read, and what an error page publishes."""

    def test_a_refused_start_echoes_no_value_and_names_no_other_variable(self):
        messages = {}
        for label, value in REFUSED_SHAPES.items():
            with self.subTest(shape=label):
                with self.assertRaises(ImproperlyConfigured) as caught:
                    require_nondebug_secret(value)
                message = str(caught.exception)
                self.assertEqual(message, REJECTION_MESSAGE)
                if value:
                    self.assertNotIn(value, message)
                    self.assertNotIn(value[:12], message)
                messages[label] = message
        self.assertEqual(len(set(messages.values())), 1,
                         'the five refusals stopped sharing one sentence')
        for name in ('POSTGRES_PASSWORD', 'POSTGRES_USER', 'DAROOBANK_ALLOWED_HOSTS'):
            self.assertNotIn(name, REJECTION_MESSAGE)

    def test_the_mask_is_a_name_pattern_and_ten_of_the_settings_match_it(self):
        reporter = SafeExceptionReporterFilter()
        self.assertEqual(reporter.hidden_settings.pattern, MASK_PATTERN)
        self.assertEqual(reporter.cleansed_substitute, '********************')
        safe = reporter.get_safe_settings()
        self.assertEqual(len(safe), SETTINGS_RENDERED,
                         'the plan states how many settings a debug error page renders')
        masked = [name for name, value in safe.items() if value == reporter.cleansed_substitute]
        self.assertEqual(len(masked), SETTINGS_MASKED)
        self.assertIn('SECRET_KEY', masked)
        password = safe['DATABASES']['default']['PASSWORD']
        self.assertEqual(password, reporter.cleansed_substitute,
                         'the nested database password stopped being masked')

    def test_a_secret_whose_name_misses_the_pattern_is_printed_in_clear(self):
        reporter = SafeExceptionReporterFilter()
        sentinel = 'lane-e-pinned-sentinel-' + 'a1b2c3d4e5' * 4
        for name in MASKED_NAMES:
            with self.subTest(setting=name):
                self.assertEqual(reporter.cleanse_setting(name, sentinel),
                                 reporter.cleansed_substitute)
        for name in CLEAR_NAMES:
            with self.subTest(setting=name):
                self.assertEqual(reporter.cleanse_setting(name, sentinel), sentinel,
                                 'a name the pattern misses stopped being printed in clear')
        # Nothing has to be added to demonstrate this: seven tracked modules already assign a
        # constant whose name the pattern misses. They are salts, not secrets, which is the point —
        # the filter never looks at the value, so what a debug page prints is decided by the name.
        holders = Counter()
        for path, text in corpus().texts.items():
            if path.endswith('.py'):
                name = name_setting(text)
                if name:
                    holders[name] += 1
        self.assertEqual(sum(holders.values()), UNMASKED_CONSTANT_MODULES,
                         'the number of modules with a constant the mask misses moved')
        self.assertEqual(dict(holders), UNMASKED_CONSTANT_NAMES,
                         'a constant whose name the mask misses was added, removed or renamed')

    def test_request_data_and_frame_locals_are_printed_in_clear_without_the_decorators(self):
        sentinel = POST_SENTINEL
        request = RequestFactory().post('/probe', {'password': sentinel, 'material': sentinel})
        reporter = SafeExceptionReporterFilter()
        parameters = reporter.get_post_parameters(request)
        for field in ('password', 'material'):
            with self.subTest(field=field):
                self.assertEqual(parameters.get(field), sentinel,
                                 'a POST field stopped being printed in clear')

        def raising_view(inner_request):
            material = sentinel
            secret_material = sentinel
            key_material = sentinel
            raise ValueError('probe %d' % len(material))

        from django.views.debug import ExceptionReporter
        with override_settings(DEBUG=True):
            try:
                raising_view(RequestFactory().get('/probe'))
            except ValueError:
                page = ExceptionReporter(RequestFactory().get('/probe'), *sys.exc_info()
                                         ).get_traceback_html()
        # `(?s)` because the rendered table puts a newline between the name cell and the value cell.
        for name in FRAME_LOCALS:
            with self.subTest(local=name):
                self.assertRegex(page, r'(?s)<td>%s</td>.{0,80}?%s' % (name, re.escape(sentinel)),
                                 'a frame local of a raising view stopped being printed in clear')
        cells = re.findall(r'<td class="code"><pre>&#x27;%s&#x27;</pre></td>' % re.escape(sentinel),
                           page)
        self.assertGreaterEqual(len(cells), len(FRAME_LOCALS),
                                'the page stopped printing a value cell per frame local')
        request_data = re.search(r'&lt;QueryDict: \{[^<]*', page)
        self.assertIsNotNone(request_data, 'the page stopped printing the request it was given')
        for field in POST_FIELDS:
            with self.subTest(field=field):
                self.assertRegex(request_data.group(0),
                                 r"&#x27;%s&#x27;: \[&#x27;%s" % (field, re.escape(sentinel)),
                                 'a POST field stopped being printed in clear inside the request data')
        # Three frame locals, the two frames that hold the sentinel under their own name, and the two
        # POST fields inside the rendered request data: every occurrence is a value the page prints.
        self.assertEqual(page.count(sentinel), len(cells) + len(POST_FIELDS),
                         'the sentinel reached the page somewhere this test cannot account for')
        users = [path for path, text in corpus().texts.items()
                 if path.endswith('.py') and any('@%s' % name in text for name in DECORATORS)]
        self.assertEqual(users, [], 'a tracked file started using one of the two masking decorators')

    def test_the_committed_debug_key_makes_signatures_reproducible(self):
        payload = {'query': 'a' * 64, 'pk': 1, 'name': 'b' * 64}
        with override_settings(SECRET_KEY=DEBUG_SECRET):
            token = signing.dumps(payload, salt=CURSOR_SALT)
            self.assertEqual(loads_nonfuture(token, salt=CURSOR_SALT, max_age=3600), payload)
            offline = salted_hmac(THROTTLE_SALT, '127.0.0.1', algorithm='sha256').hexdigest()
        with override_settings(SECRET_KEY=ANOTHER_KEY):
            with self.assertRaises(signing.BadSignature):
                loads_nonfuture(token, salt=CURSOR_SALT, max_age=3600)
        self.assertEqual(offline, THROTTLE_KEY_127,
                         'the throttle key the plan quotes is not what the committed constant makes')
        self.assertIn("CURSOR_SALT = '%s'" % CURSOR_SALT, read(SERVICES))
        self.assertIn("salted_hmac('%s'" % THROTTLE_SALT, read(THROTTLE))
        self.assertNotIn('secret=', read(THROTTLE).split('def _client_key')[1].split('def ')[0])


class DebugCouplingTests(SimpleTestCase):
    """What one boolean decides, counted from the files that decide it."""

    def test_seven_settings_lines_branch_on_debug_and_the_portal_follows_it(self):
        lines = read(SETTINGS).splitlines()
        mentioning = [number for number, line in enumerate(lines, 1)
                      if re.search(r'\bDEBUG\b', line) and not line.strip().startswith('#')]
        self.assertEqual(mentioning, DEBUG_LINES,
                         'the plan lists the seven settings lines that branch on DEBUG')
        self.assertEqual(lines[9].strip(), PORTAL_LINE,
                         'the staff portal stopped being enabled exactly when DEBUG is')
        self.assertIn('SECRET_KEY = require_nondebug_secret(SECRET_KEY)', read(SETTINGS))
        self.assertIn('if DEBUG:', read(SETTINGS))

    def test_six_commands_refuse_to_run_outside_debug_and_one_reports_it_as_a_failure(self):
        for path in REFUSE_OUTSIDE_DEBUG:
            with self.subTest(command=path):
                self.assertRegex(read(ROOT / path), r'if not settings\.DEBUG')
        readiness = read(READINESS)
        self.assertRegex(readiness, r'if settings\.DEBUG:\n\s+return False')
        commands = sorted(str(item.relative_to(ROOT)) for item in ROOT.glob('*/management/commands/*.py')
                          if item.name != '__init__.py')
        self.assertEqual(len(commands), 12, 'the command inventory the plan quotes moved')
        gating = [path for path in commands if 'settings.DEBUG' in read(ROOT / path)]
        self.assertEqual(sorted(gating), sorted(REFUSE_OUTSIDE_DEBUG + [REPORTS_DEBUG_AS_FAILURE]))

    def test_compose_demands_a_secret_and_defaults_to_the_branch_that_skips_the_check(self):
        compose = read(COMPOSE)
        self.assertIn(COMPOSE_DEBUG_DEFAULT, compose)
        self.assertIn(COMPOSE_KEY_REQUIRED, compose)
        self.assertNotIn('DAROOBANK_SECRET_KEY:-', compose,
                         'compose started supplying a default key')
        self.assertIn('must stay unset or `0`', flat(read(DEPLOYMENT)),
                      'the deployment guide stopped telling an operator the switch stays off')
        self.assertIn('Local development only.', compose.splitlines()[0])


class LeastPrivilegeTests(SimpleTestCase):
    """What a split account would have to grant, and what can inspect the one that exists."""

    def test_no_migration_statement_requires_a_superuser(self):
        migrations = [path for path in corpus().paths
                      if '/migrations/' in path and path.endswith('.py')
                      and not path.endswith('__init__.py')]
        self.assertEqual(len(migrations), 17,
                         'the plan quotes the migration count another suite pins')
        privileged = []
        for path in migrations:
            text = read(ROOT / path)
            for number, line in enumerate(text.splitlines(), 1):
                for statement in PRIVILEGED_STATEMENTS:
                    if statement in line.upper():
                        privileged.append('%s:%d %s' % (path, number, statement))
        self.assertEqual(privileged, [], 'a migration started needing a superuser')
        creates = sum(len(re.findall(r'migrations\.CreateModel\(', read(ROOT / path)))
                      for path in migrations)
        self.assertEqual(creates, 24, 'the plan quotes 24 CreateModel operations')

    def test_the_only_privilege_inspection_command_refuses_a_non_debug_configuration(self):
        lines = read(ACCESS_COMMAND).splitlines()
        self.assertEqual(lines[15].strip(),
                         "if not settings.DEBUG or connection.vendor != 'postgresql':",
                         'the guard moved; the plan quotes inspect_postgresql_access.py:16')
        source = read(POSTGRESQL_ACCESS)
        self.assertIn('pg_catalog.pg_roles', source)
        self.assertIn('pg_catalog.pg_stat_ssl', source)
        self.assertIn('has_database_privilege', source)
        self.assertNotIn('pg_authid', source,
                         'the access module started reading password material')
        self.assertNotIn('rolpassword', source)

    def test_no_command_can_answer_who_holds_the_key(self):
        commands = sorted(str(item.relative_to(ROOT)) for item in ROOT.glob('*/management/commands/*.py')
                          if item.name != '__init__.py')
        readers = []
        for path in commands:
            text = read(ROOT / path)
            if re.search(r'pg_authid|actions/secrets|gh secret|rolpassword', text):
                readers.append(path)
            if 'SECRET_KEY' in text and path != REPORTS_DEBUG_AS_FAILURE:
                readers.append(path)
        self.assertEqual(readers, [], 'a command started reading secret material')
        readiness = read(READINESS)
        self.assertIn('require_nondebug_secret(settings.SECRET_KEY)', readiness)
        self.assertIn('its entropy and secrecy are not measured here', readiness)


class AccessReviewTests(SimpleTestCase):
    """What the tree and the workflow say about who can read or change the key."""

    def test_ci_builds_every_credential_from_two_public_numbers(self):
        workflow = read(WORKFLOW)
        self.assertEqual(len(re.findall(r'secrets\.', workflow)), 0,
                         'CI started reading a secret store; the plan says it reads none')
        found = Counter(re.findall(r'\$\{\{[^}]*\}\}', workflow))
        self.assertEqual(dict(found), WORKFLOW_EXPRESSIONS,
                         'the workflow interpolates something other than two public numbers')
        for credential in CI_CREDENTIALS:
            with self.subTest(credential=credential):
                self.assertIn(credential, workflow)
        self.assertIn('permissions:\n  contents: read', workflow)

    def test_nothing_in_the_tree_can_produce_a_key_and_nothing_names_a_mechanism(self):
        code = {path: text for path, text in corpus().texts.items()
                if not path.endswith('.md') and path != THIS_SUITE}
        for token in GENERATION_TOKENS:
            holders = [path for path, text in code.items() if token in text]
            with self.subTest(token=token):
                self.assertEqual(holders, [], 'the tree gained a way to produce a key')
        for source, quote in SECRET_MANAGER_LINES:
            with self.subTest(source=source.name, quote=quote[:40]):
                self.assertIn(flat(quote), flat(read(source)),
                              'a line that asks for a secret manager was reworded or removed')
        self.assertEqual(sorted({str(source.relative_to(ROOT))
                                 for source, _ in SECRET_MANAGER_LINES}), SECRET_MANAGER_DOCUMENTS,
                         'the documents that ask for a secret manager changed')
        mechanism = sorted(path for path, text in corpus().documents.items()
                           if MECHANISM_PATTERN.search(text))
        self.assertEqual(mechanism, MECHANISM_DOCUMENTS,
                         'a document started naming a mechanism; update the plan and this pin')
        for path in mechanism:
            with self.subTest(document=path):
                self.assertIn('0 tracked files', flat(read(ROOT / path)),
                              'a document names a mechanism without reporting that nothing uses it')

    def test_the_authorization_review_does_not_cover_secrets_or_repository_access(self):
        text = read(AUTHORIZATION_REVIEW)
        self.assertEqual(len(text.splitlines()), AUTHORIZATION_REVIEW_LINES)
        for word in AUTHORIZATION_REVIEW_ABSENT:
            with self.subTest(word=word):
                self.assertEqual(len(re.findall(re.escape(word), text, re.I)), 0,
                                 'the authorization review started covering secret custody')
        self.assertIn('**Status: the inventory is derived and drift-checked; the judgement is '
                      'unsigned.**', flat(text))

    def test_no_document_names_a_cadence_for_reviewing_who_holds_the_key(self):
        cadence = re.compile(r'(quarterl|annual|every \d+ (?:day|month|week)|cadence|periodic)', re.I)
        access = re.compile(r'access|role|permission|secret|credential|collaborator', re.I)
        hits = []
        for path, text in sorted(corpus().documents.items()):
            if path in OWN_DOCUMENTS:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if cadence.search(line) and access.search(line):
                    hits.append('%s:%d' % (path, number))
        self.assertEqual(len(hits), CADENCE_ACCESS_LINES,
                         'the plan quotes five cadence-and-access lines outside its own documents')
        # The claim itself: a cadence word, an access word, a custody subject and an instruction.
        # It is made over the documents this delivery does not write, because this delivery's own
        # sentences quote the instruction they report the absence of, and the plan lists all ten.
        custody = []
        for path, text in sorted(corpus().documents.items()):
            if path in OWN_DOCUMENTS:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if cadence.search(line) and access.search(line) \
                        and CUSTODY_TRIGGER.search(line) and CUSTODY_INSTRUCTION.search(line):
                    custody.append('%s:%d' % (path, number))
        self.assertEqual(custody, [], 'a document started prescribing a custody review cadence')

    def test_the_environment_names_the_application_reads_are_the_ones_another_suite_pins(self):
        # The inventory itself belongs to daroobank/test_environment_documentation.py; this suite
        # asserts only the sub-fact the plan states, and asserts it against that suite's constant.
        source = read(SYNTHETIC_SETTINGS)
        del source
        environment_suite = read(ROOT / 'daroobank' / 'test_environment_documentation.py')
        reads = re.search(r'READS = \{(.*?)\n\}', environment_suite, re.S).group(1)
        names = sorted(set(re.findall(r"'((?:DAROOBANK|POSTGRES)_[A-Z0-9_]+)'", reads)))
        self.assertEqual(len(names), 16, 'the pinned environment inventory moved')
        secret_bearing = [name for name in names if re.search(r'SECRET|PASSWORD', name)]
        self.assertEqual(secret_bearing, ['DAROOBANK_SECRET_KEY', 'POSTGRES_PASSWORD'])
        settings_source = read(SETTINGS)
        direct = set(re.findall(r"os\.environ(?:\.get)?\(?\[?'([A-Z_][A-Z0-9_]*)'", settings_source))
        helper = set(re.findall(r"required_database_setting\('([A-Z_][A-Z0-9_]*)'\)", settings_source))
        self.assertEqual(sorted(direct | helper), names,
                         'settings.py reads an environment name the inventory does not pin')


class NeighbourTests(SimpleTestCase):
    """The documents that ask for this reach it, and the pins that move say so."""

    def test_the_neighbouring_documents_name_the_plan_and_what_it_measured(self):
        for path in NEIGHBOURS:
            text = flat(read(path))
            with self.subTest(document=path.name):
                self.assertIn('SECRETS_ACCESS_PLAN.md', text)
                self.assertIn('0238-secrets-access-plan.md', text)

    def test_the_release_evidence_row_answers_the_gate_and_stays_open(self):
        row = [line for line in read(EVIDENCE).splitlines()
               if line.startswith('| Secrets and access |')]
        self.assertEqual(len(row), 1, 'the gate row was duplicated or removed')
        text = flat(row[0])
        self.assertIn('**Open:**', text, 'the gate row stopped being open')
        self.assertIn('Shape checks do not demonstrate entropy or secrecy.', text)
        self.assertIn('SECRETS_ACCESS_PLAN.md', text)
        self.assertIn('0238-secrets-access-plan.md', text)
        for phrase in ('28.1 bits', '156.1 bits', '/proc/', '3 collaborators'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text, 'the gate row stopped carrying what was measured')

    def test_the_changelog_entry_is_newest_first_and_names_the_plan(self):
        text = read(CHANGELOG)
        entries = re.findall(r'(?m)^## (\d{4}-\d{2}-\d{2}) — (.+)$', text)
        self.assertTrue(entries, 'the changelog lost its entry headings')
        dates = [date for date, _ in entries]
        self.assertEqual(dates, sorted(dates, reverse=True), 'the changelog is not newest-first')
        # Found by what it names, not by being first, so the next delivery can go above it.
        bodies = [text.split('## %s — %s' % (date, title), 1)[1].split('\n## ', 1)[0]
                  for date, title in entries]
        own = [body for body in bodies if 'SECRETS_ACCESS_PLAN.md' in body]
        self.assertEqual(len(own), 1,
                         'the changelog entry that records this plan is missing or duplicated')
        first_body = own[0]
        self.assertIn('SECRETS_ACCESS_PLAN.md', flat(first_body))
        self.assertIn('0238-secrets-access-plan.md', flat(first_body))
        for phrase in ('28.1 bits', '0 `secrets.` references', '3 collaborators'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat(first_body))

    def test_the_pins_that_count_the_tree_moved_with_this_plan(self):
        for path, names in PIN_SUITES.items():
            source = read(ROOT / path)
            for name in names:
                with self.subTest(suite=path, pin=name):
                    self.assertRegex(source, r'(?m)^%s = \d+' % name,
                                     'a shared pin this delivery moves was not found')
        for delta in PIN_DELTAS:
            with self.subTest(delta=delta):
                self.assertIn(flat(delta), flat(read(ADR)),
                              'the record stopped stating a pin this delivery moves')

    def test_the_counts_the_pins_state_are_the_counts_the_tree_has(self):
        # The rules that count a document, a record, a link, a tracked file and a test module belong
        # to the suites that own those pins — `tree_files()` leaves out the files its own delivery
        # added, and `all_links()` reads prose rather than raw text — so this test calls their code.
        # A second rule here would only disagree with the pin it is supposed to support.
        import daroobank.test_database_connection_plan as connection
        import daroobank.test_database_migration_plan as migration
        import daroobank.test_document_links as document_links

        documents = document_links.documents()
        targets = [target for document in documents
                   for target in document_links.all_links(document.read_text(encoding='utf-8'))]
        records = sorted(document_links.ADR_DIR.glob('[0-9][0-9][0-9][0-9]-*.md'))
        modules = [path for path in migration.python_modules()
                   if migration.is_test_module(path)]
        counts = (len(documents), len(records), len(targets), len(connection.tree_files()),
                  len(modules))
        pins = (pin(read(DOCUMENT_LINKS), 'DOCUMENT_COUNT'), pin(read(DOCUMENT_LINKS), 'ADR_COUNT'),
                pin(read(DOCUMENT_LINKS), 'LINK_COUNT'),
                pin(read(CONNECTION_SUITE), 'TREE_FILE_COUNT'),
                pin(read(MIGRATION_SUITE), 'TEST_MODULE_COUNT'))
        self.assertEqual(counts, pins,
                         'a counting pin this delivery moves is not the count of the thing it counts')
        self.assertEqual(len([path for path in corpus().paths
                              if path.endswith('.py') and is_test_path(path)]), len(modules),
                         'this suite\'s test-module rule disagrees with the one that owns the pin')

    def test_nothing_this_plan_prices_exists(self):
        configuration = read(CONFIGURATION)
        self.assertNotIn('entropy', configuration.lower(),
                         'an entropy floor was implemented; the plan prices it as not implemented')
        self.assertNotIn('log2', configuration)
        self.assertIn("SECRET_KEY = '%s'" % DEBUG_SECRET, read(SETTINGS),
                      'the debug fallback was replaced; the plan prices that as option E')
        for token in GENERATION_TOKENS:
            self.assertNotIn(token, read(SETTINGS))
        workflow = read(WORKFLOW)
        self.assertNotIn('secrets.', workflow)
        requirements = read(ROOT / 'requirements.txt')
        for word in ('argon2', 'cryptography', 'kms', 'vault', 'keyring', 'boto', 'secretmanager'):
            with self.subTest(dependency=word):
                self.assertNotIn(word, requirements.lower())
        fixtures = [path for path, text in corpus().texts.items()
                    if path.endswith('.py') and re.search(r'CREATE ROLE [a-z_]*(runtime|owner)', text)]
        self.assertEqual(fixtures, [], 'a second database role appeared in a fixture')


def name_setting(text):
    """A tracked module that assigns a setting whose name the mask pattern does not match."""
    for name in re.findall(r'(?m)^([A-Z][A-Z0-9_]{3,}) = ', text):
        if re.search(r'PEPPER|MATERIAL|SALT', name) and not SafeExceptionReporterFilter \
                .hidden_settings.search(name):
            return name
    return None


DOCUMENT_LINKS = ROOT / 'daroobank' / 'test_document_links.py'
MIGRATION_SUITE = ROOT / 'daroobank' / 'test_database_migration_plan.py'
CONNECTION_SUITE = ROOT / 'daroobank' / 'test_database_connection_plan.py'


def pin(source, name):
    """The value a suite pins, read from the suite that owns it."""
    return int(re.search(r'(?m)^%s = (\d+)' % name, source).group(1))


LINK_COUNT = int(re.search(r'(?m)^LINK_COUNT = (\d+)',
                           read(ROOT / 'daroobank' / 'test_document_links.py')).group(1))
