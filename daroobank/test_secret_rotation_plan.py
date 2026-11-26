"""One secret, nine keyed digests, and a rotation that has never been rehearsed.

`docs/SECRET_ROTATION_PLAN.md` exists because four documents ask for key rotation and none of them
describes one. It stated its measurements as prose, so nothing tied it to this tree: a reader could
not tell whether rotating `DAROOBANK_SECRET_KEY` was a settings change, an outage, or something in
between. This suite pins the plan to what the key surface actually is and to what one rotation
actually does, so the options in it stay priced against the code and performing a rotation becomes a
documented event rather than an edit to an environment file.

What is measured here, and what the plan says because of it:

* there is one secret and one variable that supplies it. `SECRET_KEY` is
  `os.environ.get('DAROOBANK_SECRET_KEY', '')`; in debug an empty value becomes the published
  35-character constant `'development-only-not-for-production'`, which `require_nondebug_secret`
  already rejects, and outside debug the value must be 50-512 printable ASCII characters with at
  least 5 distinct ones and no `django-insecure-` prefix — a shape a dictionary phrase satisfies;
* every keyed digest inherits it. Of the 127 non-test project modules, 9 call `salted_hmac` and none
  of the 9 passes an explicit `secret=`, so all of them take `settings.SECRET_KEY`; they use 9 salts,
  8 named constants and one inline literal, and 5 of the 9 compose a per-purpose suffix onto theirs.
  Six modules also sign values through `django.core.signing`, whose default key is the same secret;
* the session store signs its own rows with it. `SESSION_ENGINE` is the database backend, its
  `key_salt` is `django.contrib.sessions.SessionStore`, and a row that does not verify decodes to an
  empty dict while `"Session data corrupted"` goes to a logger that has no handlers, because
  `LOGGING` is `{}` and no project module imports `logging`;
* nothing rotates it. `SECRET_KEY_FALLBACKS` is `[]` and no project module names it, no
  key-management package is in the hash-pinned lock, the 12 management commands include no rotate or
  rekey command, and the readiness report's only secret check says in its own message that "its
  entropy and secrecy are not measured here";
* one rotation, performed on synthetic data, turns a staff route that answered 200 into a 302 to the
  login page, leaves the `django_session` row in place but decodable to `{}`, hides that row from
  `list_staff_sessions` (`sessions_matched: 0`) and from `revoke_staff_sessions --all --apply`
  (`matched: 0, revoked: 0`), restarts both address-keyed limiters while orphaning their rows
  (1 → 2 in each window table, the prune reporting `deleted: 0` because its retention is 24 hours),
  and invalidates a signed cursor;
* a stored password survives it. The `password` column is byte-identical and the same passphrase
  still verifies, because PBKDF2 uses a per-password salt; what changes is `get_session_auth_hash()`,
  and with it the session fingerprint and the alias the inventory prints for the same session key;
* `SECRET_KEY_FALLBACKS` is a partial rescue this project defeats. With the old key listed, the
  session row decodes fully again, the signed cursor loads and Django's own `get_user` accepts the
  stored hash — but `authorization_fingerprint` embeds `get_session_auth_hash()` only and never
  consults `get_session_auth_fallback_hash()`, so the guard still ends the session, and
  `salted_hmac` has no fallback parameter for the limiter keys to use.

The prices in the plan are counted from these measurements, not prototyped: no rotation command was
built and reverted, so no cascade of pin failures was run, but the rotation itself was performed and
every number above is its result. What is not checked is whether a single inherited secret with no
rotation procedure is acceptable, who holds the key, what triggers a rotation, how a new one is
generated and where the event is recorded. Those are the eight numbered decisions the plan leaves
open, and no test can make them.
"""
import logging
import re
from io import StringIO
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import Permission
from django.contrib.sessions.backends.db import SessionStore as DbSessionStore
from django.contrib.sessions.models import Session
from django.core import signing
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.core.management import call_command
from django.test import SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse

from catalog import services as catalog_services
# Importing the guard connects the project's one auth-signal receiver; the other imports are used.
from daroobank import configuration, session_guard, signed_cursors
from daroobank.actor_recheck import recheck_actor
from daroobank.management.commands import check_deployment_readiness
from staff_security import read_limit, throttle
from staff_security.management.commands import (cleanup_staff_login_windows, list_staff_sessions,
                                                revoke_staff_sessions)
from staff_security.models import PublicReadWindow, StaffLoginWindow

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'SECRET_ROTATION_PLAN.md'
SECURITY = ROOT / 'docs' / 'SECURITY.md'
DEPLOYMENT = ROOT / 'docs' / 'DEPLOYMENT.md'
RUNBOOK = ROOT / 'docs' / 'OPERATIONS_RUNBOOK.md'
EVIDENCE = ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'
CHANGELOG = ROOT / 'docs' / 'CHANGELOG.md'
SETTINGS = ROOT / 'daroobank' / 'settings.py'
CONFIGURATION = ROOT / 'daroobank' / 'configuration.py'
SESSION_GUARD = ROOT / 'daroobank' / 'session_guard.py'
READINESS = ROOT / 'daroobank' / 'management' / 'commands' / 'check_deployment_readiness.py'
ADR = 'ARCHITECTURE_DECISIONS/0231-secret-rotation-plan.md'
ADR_DIR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS'

SKIP_PARTS = frozenset({'.venv', '.cache', '.git', 'node_modules', '__pycache__', 'migrations',
                        'staticfiles'})
SECTIONS = ['What is true today, measured',
            'Candidate approach and decisions required',
            'Options and what each costs',
            'Required behavior before any rotation',
            'Verification before any enablement']
SUBSECTIONS = ['The key surface', 'The cascade, measured on one real login',
               'What the repository already says about it']
DECISIONS = ['Where does the key live, and who holds it?',
             'What triggers a rotation, and who authorizes it?',
             'Is a silent mass invalidation acceptable?',
             'May `SECRET_KEY_FALLBACKS` be used at all?',
             'What happens to the rows a rotation orphans?',
             'How is a new key generated, and how is its entropy verified?',
             'What is recorded about a rotation?',
             'What is the recovery path when the key is lost rather than rotated?']
OPTIONS = ['A. Leave key handling as documented',
           'B. Write the rotation procedure down only',
           'C. Add a read-only pre-rotation impact command',
           'D. Make rotation graceful with `SECRET_KEY_FALLBACKS`',
           'E. Give each purpose its own key material',
           'F. Take the key from an external secret manager or KMS',
           'G. Declare key rotation out of Phase 1 scope']
# The requirement each document states, quoted into the plan and pinned here, so the plan cannot
# drift away from the sentences it is written against.
QUOTED_REQUIREMENTS = [
    (SECURITY, 'isolated managed keys and rotation'),
    (DEPLOYMENT, 'Changing a key affects existing signatures and sessions; no production rotation '
                 'policy is implemented'),
    (RUNBOOK, 'rotate exposed credentials'),
    (EVIDENCE, 'secret manager, key generation/rotation and recovery'),
    (CHANGELOG, 'aliases are keyed on `SECRET_KEY`, so a rotation breaks correlation between '
                'reports'),
]
# The nine keyed digests, and the nine salts between them. None of them passes its own secret.
KEYED_SITES = ['catalog/identity_lineage.py:48', 'catalog/projection_repair.py:61',
               'catalog/quality_irc.py:45', 'catalog/services.py:36', 'clinical/lineage.py:35',
               'daroobank/session_guard.py:66',
               'staff_security/management/commands/list_staff_sessions.py:32',
               'staff_security/read_limit.py:42', 'staff_security/throttle.py:25']
SALTS = ['catalog.identity.lineage.v1', 'catalog.quality.irc.cursor.v1', 'catalog.search.cursor.v1',
         'catalog.synthetic-projection-repair.v1', 'clinical.draft.lineage.v1',
         'daroobank.staff.session.inventory.v1', 'daroobank.staff.session.v1',
         'staff_security.login.client.v1', 'staff_security.public_read.v1']
COMPOSED_SALT_SITES = 5
SIGNING_MODULES = ['catalog/identity_lineage.py', 'catalog/projection_repair.py',
                   'catalog/quality_irc.py', 'catalog/services.py', 'clinical/lineage.py',
                   'daroobank/signed_cursors.py']
DEBUG_SECRET = 'development-only-not-for-production'
SHAPE_FRAGMENTS = ['50 <= len(value) <= 512', 'len(set(value)) < 5',
                   "value.lower().startswith('django-insecure-')", '33 <= ord(char) <= 126',
                   'this cannot determine randomness or secrecy']
# A shape-valid secret with no entropy at all: the shape check accepts it and says so.
DICTIONARY_PHRASE = 'the-quick-brown-fox-jumps-over-the-lazy-dog-in-tehran'
PROJECT_MODULE_COUNT = 127
TEST_MODULE_COUNT = 237
COMMAND_COUNT = 12
READINESS_CHECKS = ['debug_disabled', 'staff_portal_disabled', 'secret_key_shape',
                    'allowed_hosts_explicit', 'cookies_secure', 'session_flags',
                    'ssl_redirect_enabled', 'migrations_applied', 'migration_history_consistent',
                    'database_reachable']
LOCK_FACTS = {'names': 7, 'hashes': 78, 'template variables': 12, 'compose variables': 12}
DIRECT_REQUIREMENTS = ['Django==5.2.19', 'asgiref==3.13.0', 'sqlparse==0.6.1',
                       'psycopg[binary]==3.3.9']
KEY_MANAGEMENT_WORDS = ('argon2', 'cryptography', 'kms', 'vault', 'keyring', 'boto', 'secretmanager')
# The measured cascade: what one rotation did to one live synthetic staff session.
CASCADE = {'route before': 200, 'route after': 302, 'warnings': 1, 'login windows before': 1,
           'login windows after': 2, 'read windows before': 1, 'read windows after': 2}
SESSION_KEYS = ['_auth_user_backend', '_auth_user_hash', '_auth_user_id', 'staff_auth_fingerprint']
OLD_KEY = 'measured-rotation-old-key-' + 'a1b2c3d4e5' * 4
NEW_KEY = 'measured-rotation-new-key-' + 'f6g7h8i9j0' * 4
OTHER_KEY = 'another-measured-key-' + 'z9y8x7w6v5' * 4
ADDRESS = '203.0.113.7'
USERNAME = 'synthetic-rotation-staff'
PASSPHRASE = 'synthetic-rotation-passphrase'


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


def python_modules():
    return sorted(path for path in ROOT.rglob('*.py')
                  if not (SKIP_PARTS & set(path.relative_to(ROOT).parts)))


def is_test_module(path):
    return path.name.startswith('test_') or path.name == 'tests.py'


def project_modules():
    return [path for path in python_modules() if not is_test_module(path)]


def modules_matching(pattern, pool):
    return sorted(str(path.relative_to(ROOT)) for path in pool
                  if re.search(pattern, read(path), re.M))


def other_test_modules():
    """The tree's test modules, minus this suite.

    The counts the plan quotes describe the tree the plan was measured against, so this module is
    excluded from them: naming `salted_hmac` here must not move the number it pins.
    """
    return [path for path in python_modules()
            if is_test_module(path) and path.name != 'test_secret_rotation_plan.py']


def command_modules():
    """The project's management command modules, one file per command."""
    return [path for path in project_modules()
            if 'management/commands' in path.relative_to(ROOT).as_posix()
            and path.name != '__init__.py']


def keyed_sites():
    """Every `salted_hmac` call in a non-test project module, as `path:line`."""
    sites = []
    for path in project_modules():
        for number, line in enumerate(read(path).splitlines(), start=1):
            if 'salted_hmac(' in line:
                sites.append(f'{path.relative_to(ROOT).as_posix()}:{number}')
    return sorted(sites)


def option_rows(text):
    rows = []
    for line in section(text, 'Options and what each costs').splitlines():
        if line.startswith('|') and not set(line.replace('|', '').strip()) <= {'-', ' ', ':'}:
            cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
            if cells and cells[0] != 'Option':
                rows.append(cells)
    return rows


def command_output(command, *arguments):
    """One management command's JSON report, as a single line."""
    out = StringIO()
    call_command(command, *arguments, stdout=out)
    return ' '.join(out.getvalue().split())


def inventory_alias(report):
    return re.search(r'"alias": "(\w+)"', report).group(1)


class PlanDocumentTests(SimpleTestCase):
    def test_the_plan_is_an_unowned_proposal_with_eight_numbered_decisions(self):
        text = read(PLAN)
        flat_text = flat(text)
        self.assertEqual(sections(text), SECTIONS, 'the plan lost or reordered a section')
        self.assertEqual(subsections(text), SUBSECTIONS, 'the measurements lost a subsection')
        for phrase in ('This document is a **proposal**', 'It has no owner and no approval',
                       'must not treat the single environment variable this project has as a '
                       'key-management system',
                       'not an implemented or approved key-management control',
                       'no rotation was implemented and reverted',
                       'no cascade of pin failures was run',
                       'the rotation itself **was** performed',
                       'every number below is the result of that run'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_text, 'the plan stopped limiting itself')
        decisions = section(text, SECTIONS[1])
        numbered = re.findall(r'^\d+\. \*\*(.*?)\*\*', decisions, re.M)
        self.assertEqual(numbered, DECISIONS, 'a decision was added, removed or reworded')
        self.assertEqual(len(numbered), 8, 'the plan says eight decisions and lists another count')
        self.assertEqual(len(re.findall(r'^\d+\. \*\*', section(
            text, 'Required behavior before any rotation'), re.M)), 7,
            'the required-behavior list changed length')

    def test_the_plan_quotes_the_documents_that_ask_for_rotation(self):
        text = read(PLAN)
        flat_plan = flat(text)
        for document, phrase in QUOTED_REQUIREMENTS:
            with self.subTest(document=document.name):
                self.assertIn(phrase, flat(read(document)),
                              f'{document.name} no longer asks for what the plan quotes')
                self.assertIn(phrase, flat_plan, f'the plan stopped quoting {document.name}')
        self.assertIn(f']({ADR})', text, 'the plan does not link the record that measures it')

    def test_every_option_names_a_counted_price_and_something_it_does_not_answer(self):
        rows = option_rows(read(PLAN))
        self.assertEqual([row[0].strip('* ') for row in rows], OPTIONS,
                         'the options changed order, count or name')
        for row in rows:
            with self.subTest(option=row[0]):
                self.assertEqual(len(row), 4, 'an option row lost a cell')
                price, limit = row[2], row[3]
                self.assertGreaterEqual(len(price), 40, 'an option has no counted price')
                self.assertGreaterEqual(len(limit), 30, 'an option claims to answer everything')
                self.assertTrue(re.search(r'\d', price), 'a price names no count to check')
        prices = {row[0].strip('* '): row[2] for row in rows}
        self.assertIn('`COMMANDS` 12 → 13', prices[OPTIONS[2]],
                      'the command-count price of option C moved with no measurement behind it')
        self.assertIn('`READS` 16 → 17+', prices[OPTIONS[4]],
                      'the variable-inventory price of option E moved with no measurement behind it')
        for fragment in ('367 lines', '54 `session_auth_hash=` references', '14 non-test modules'):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, prices[OPTIONS[3]],
                              'the price of option D moved with no measurement behind it')

    def test_every_module_document_and_record_the_plan_names_exists(self):
        text = read(PLAN)
        for name in set(re.findall(r'`([\w./-]+\.py)`', text)):
            with self.subTest(module=name):
                self.assertTrue((ROOT / name).is_file(), f'the plan names {name}, which is missing')
        for name in set(re.findall(r'`([\w./-]+\.(?:cjs|json|yaml|md|txt))`', text)):
            with self.subTest(file=name):
                self.assertTrue((ROOT / name).is_file(), f'the plan names {name}, which is missing')
        for number in set(re.findall(r'\b0\d{3}\b', text)):
            with self.subTest(record=number):
                self.assertTrue(list(ADR_DIR.glob(f'{number}-*.md')),
                                f'the plan cites decision record {number}, which does not exist')
        self.assertIn(ADR, text, 'the plan does not name the record that measures it')
        for site in KEYED_SITES:
            with self.subTest(site=site):
                self.assertIn(site, text, 'the plan stopped naming a keyed digest it prices')
                self.assertIn(site, keyed_sites(), 'the plan names a keyed site that is not one')

    def test_the_cascade_the_plan_describes_is_the_measured_one(self):
        flat_text = flat(read(PLAN))
        for phrase in ('answers **302 to the login page** after it', 'Session data corrupted',
                       'scanned: 1, sessions_matched: 0, sessions_unbound: 0',
                       'matched: 0, revoked: 0, scanned: 1', '{"deleted": 0, "limit": 500}',
                       '1 → **2**', 'byte-identical', 'no fallback parameter at all',
                       'bound: true, guard_would_end_it: true',
                       'raises `PermissionDenied` afterwards', 'scanned: 0',
                       '54 references in 14 non-test modules',
                       'test_key_rotation_invalidates_old_cursor',
                       'its entropy and secrecy are not measured here',
                       'django.contrib.sessions.SessionStore', DEBUG_SECRET,
                       'There is one secret'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_text,
                              'the plan stopped stating a measured consequence of a rotation')


class MeasuredKeySurfaceTests(SimpleTestCase):
    def test_one_environment_variable_supplies_the_only_secret(self):
        settings_text = read(SETTINGS)
        self.assertIn("SECRET_KEY = os.environ.get('DAROOBANK_SECRET_KEY', '')", settings_text,
                      'the secret stopped coming from one environment variable')
        self.assertIn(f"SECRET_KEY = '{DEBUG_SECRET}'", settings_text,
                      'the published debug fallback moved or changed')
        self.assertEqual(len(DEBUG_SECRET), 35, 'the debug constant changed length')
        with self.assertRaises(ImproperlyConfigured):
            configuration.require_nondebug_secret(DEBUG_SECRET)
        self.assertEqual(modules_matching(r"os\.environ\.get\('DAROOBANK_SECRET_KEY'",
                                          project_modules()), ['daroobank/settings.py'],
                         'a second module started reading the secret variable')
        self.assertEqual(settings.SECRET_KEY_FALLBACKS, [],
                         'a fallback key was configured, which the plan says is absent')
        self.assertEqual(modules_matching(r'SECRET_KEY_FALLBACKS', project_modules()), [],
                         'a project module started naming SECRET_KEY_FALLBACKS')

    def test_nine_keyed_digests_use_nine_salts_and_none_passes_its_own_secret(self):
        project = project_modules()
        self.assertEqual(len(project), PROJECT_MODULE_COUNT,
                         'the non-test module count the plan quotes moved')
        self.assertEqual(len(other_test_modules()), TEST_MODULE_COUNT,
                         'the test module count the plan quotes moved')
        self.assertEqual(keyed_sites(), sorted(KEYED_SITES),
                         'a keyed digest moved, appeared or disappeared')
        self.assertEqual(len(keyed_sites()), 9, 'the plan prices nine keyed digests')
        self.assertEqual(modules_matching(r'salted_hmac\([^)]*secret=', project), [],
                         'a keyed digest started passing its own secret, which is option E')
        found = set()
        for site in KEYED_SITES:
            relative, line = site.split(':')
            text = read(ROOT / relative)
            found |= set(re.findall(r"'([a-z][a-z0-9._-]*\.v1)'", text))
            self.assertIn('sha256', text.splitlines()[int(line) - 1],
                          f'{site} stopped naming its digest algorithm')
        self.assertEqual(sorted(found), sorted(SALTS), 'the salt inventory moved')
        composed = []
        for site in KEYED_SITES:
            relative, line = site.split(':')
            if re.search(r"salted_hmac\((f'|\w+ \+)", read(ROOT / relative).splitlines()[int(line) - 1]):
                composed.append(site)
        self.assertEqual(len(composed), COMPOSED_SALT_SITES,
                         'the count of sites that compose a per-purpose suffix moved')
        self.assertEqual(modules_matching(r'from django\.core import signing', project),
                         SIGNING_MODULES, 'the modules that sign with the same secret moved')

    def test_the_session_store_signs_its_own_rows_and_keeps_no_record_of_a_failure(self):
        store = DbSessionStore()
        self.assertEqual(settings.SESSION_ENGINE, 'django.contrib.sessions.backends.db')
        self.assertEqual(store.key_salt, 'django.contrib.sessions.SessionStore')
        blob = store.encode({'_auth_user_id': '1', 'staff_auth_fingerprint': 'digest'})
        self.assertEqual(sorted(store.decode(blob)), ['_auth_user_id', 'staff_auth_fingerprint'])
        with override_settings(SECRET_KEY=OTHER_KEY):
            with self.assertLogs('django.security.SuspiciousSession', level='WARNING') as caught:
                self.assertEqual(store.decode(blob), {},
                                 'a row signed under one secret still decoded under another')
            self.assertEqual([record.getMessage() for record in caught.records],
                             ['Session data corrupted'])
        self.assertEqual(settings.LOGGING, {}, 'the application grew a logging configuration')
        self.assertEqual(modules_matching(r'^\s*import logging\b', project_modules()), [],
                         'a project module started importing logging, which the plan says none does')
        self.assertEqual(logging.getLogger('django.security.SuspiciousSession').handlers, [],
                         'the suspicious-session logger gained a handler')

    def test_a_signed_cursor_dies_with_the_key_and_a_fallback_rescues_only_the_signature(self):
        salt = catalog_services.CURSOR_SALT
        age = catalog_services.CURSOR_MAX_AGE
        token = signing.dumps({'query': 'digest', 'pk': 1}, salt=salt)
        self.assertEqual(signed_cursors.loads_nonfuture(token, salt=salt, max_age=age),
                         {'query': 'digest', 'pk': 1})
        with override_settings(SECRET_KEY=OTHER_KEY):
            with self.assertRaises(signing.BadSignature):
                signed_cursors.loads_nonfuture(token, salt=salt, max_age=age)
        with override_settings(SECRET_KEY=OTHER_KEY, SECRET_KEY_FALLBACKS=[settings.SECRET_KEY]):
            self.assertEqual(signed_cursors.loads_nonfuture(token, salt=salt, max_age=age),
                             {'query': 'digest', 'pk': 1},
                             'a listed fallback stopped rescuing a signed value')
        self.assertIn('def test_key_rotation_invalidates_old_cursor',
                      read(ROOT / 'catalog' / 'test_pagination.py'),
                      'the route-level rotation pin this plan cites disappeared')

    def test_nothing_rotates_the_key_and_the_only_check_is_a_shape_check(self):
        commands = command_modules()
        self.assertEqual(len(commands), COMMAND_COUNT,
                         'the management command count the plan quotes moved')
        self.assertEqual([path.name for path in commands if re.search(r'(?i)rotat|rekey',
                                                                     path.name)], [],
                         'a rotation or rekey command appeared')
        self.assertEqual([name for name, _check in check_deployment_readiness.REQUIRED],
                         READINESS_CHECKS, 'the readiness checks moved')
        body = read(READINESS).partition('def secret_key_shape')[2].partition('\ndef ')[0]
        self.assertIn('DAROOBANK_SECRET_KEY does not have a supported non-debug shape', body)
        self.assertIn('its entropy and secrecy are not measured here', body)
        self.assertEqual(cleanup_staff_login_windows.BATCH_LIMIT, 500)
        self.assertEqual(cleanup_staff_login_windows.RETENTION.total_seconds(), 24 * 3600,
                         'the login-window retention the plan quotes moved')
        self.assertEqual(revoke_staff_sessions.SCAN_LIMIT, 5000)
        self.assertEqual(revoke_staff_sessions.BATCH_LIMIT, 500)
        self.assertEqual(list_staff_sessions.SCAN_LIMIT, 5000)
        self.assertEqual(list_staff_sessions._ID_SALT, 'daroobank.staff.session.inventory.v1')
        self.assertEqual(modules_matching(r'PublicReadWindow', commands), [],
                         'a command started pruning public read windows, which none does today')

    def test_the_shape_check_accepts_a_dictionary_phrase_and_rejects_the_debug_constant(self):
        self.assertEqual(len(DICTIONARY_PHRASE), 53, 'the phrase stopped being shape-valid')
        self.assertEqual(configuration.require_nondebug_secret(DICTIONARY_PHRASE),
                         DICTIONARY_PHRASE,
                         'the shape check started rejecting a dictionary phrase, which would be a '
                         'control the plan says does not exist')
        for candidate in ('short-but-distinct-1234567890', 'django-insecure-' + 'x' * 40, 'a' * 60,
                          'distinct-1234567890-' + 'y' * 30 + '\t'):
            with self.subTest(candidate=candidate[:24]):
                with self.assertRaises(ImproperlyConfigured):
                    configuration.require_nondebug_secret(candidate)
        source = read(CONFIGURATION)
        for fragment in SHAPE_FRAGMENTS:
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, source, 'the shape limits the plan quotes moved')

    def test_the_guard_compares_the_primary_auth_hash_and_the_limiter_keys_move_with_it(self):
        source = read(SESSION_GUARD)
        self.assertIn('current.get_session_auth_hash()', source,
                      'the fingerprint stopped embedding the primary session auth hash')
        self.assertNotIn('get_session_auth_fallback_hash', source,
                         'the guard learned about fallback hashes, which is option D')
        self.assertEqual(session_guard._KEY_SALT, 'daroobank.staff.session.v1')
        self.assertEqual(session_guard.SESSION_FINGERPRINT_KEY, 'staff_auth_fingerprint')
        self.assertEqual(throttle.ATTEMPT_LIMIT, 10)
        self.assertEqual(throttle.WINDOW.total_seconds(), 60)
        self.assertEqual(read_limit.READ_LIMIT, 120)
        self.assertEqual(read_limit.WINDOW.total_seconds(), 60)
        self.assertEqual(read_limit.SCOPE, 'staff_security.public_read.v1')
        login_key = throttle._client_key(ADDRESS)
        read_key = read_limit.client_key(ADDRESS)
        self.assertEqual(len(login_key), 64)
        self.assertNotEqual(login_key, read_key, 'the two limiters started sharing a key')
        with override_settings(SECRET_KEY=OTHER_KEY):
            self.assertNotEqual(throttle._client_key(ADDRESS), login_key,
                                'the throttle key did not move with the secret')
            self.assertNotEqual(read_limit.client_key(ADDRESS), read_key,
                                'the read-limit key did not move with the secret')
            self.assertEqual(throttle._client_key(ADDRESS), throttle._client_key(ADDRESS))

    def test_no_key_management_dependency_exists_and_configuration_is_counted(self):
        requirements = read(ROOT / 'requirements.txt')
        names = re.findall(r'^([A-Za-z0-9_.\[\]-]+)==', requirements, re.M)
        self.assertEqual(len(names), LOCK_FACTS['names'], 'the pinned-name count moved')
        for name in names:
            with self.subTest(name=name):
                self.assertFalse(any(word in name.lower() for word in KEY_MANAGEMENT_WORDS),
                                 'a key-management package entered the hash-pinned lock')
        self.assertEqual(len(re.findall(r'--hash=', requirements)), LOCK_FACTS['hashes'],
                         'the hash count the plan quotes moved')
        self.assertEqual([line for line in read(ROOT / 'requirements.in').splitlines()
                          if line.strip()], DIRECT_REQUIREMENTS,
                         'the direct pins moved')
        self.assertEqual(len(re.findall(r'^[A-Z_][A-Z0-9_]*=', read(ROOT / '.env.example'), re.M)),
                         LOCK_FACTS['template variables'],
                         'the environment template the plan prices against moved')
        compose = read(ROOT / 'compose.yaml')
        variables = sorted(set(re.findall(r'\b(?:DAROOBANK|POSTGRES)_[A-Z_]+\b', compose)))
        self.assertEqual(len(variables), LOCK_FACTS['compose variables'])
        self.assertIn('DAROOBANK_SECRET_KEY', variables,
                      'Compose stopped supplying the one secret')


@override_settings(DEBUG=True, SECRET_KEY=OLD_KEY, STAFF_PORTAL_ENABLED=True,
                   STAFF_LOGIN_THROTTLE_ENABLED=True, PUBLIC_READ_LIMIT_ENABLED=True)
class MeasuredRotationCascadeTests(TransactionTestCase):
    """What one rotation does to a live synthetic session, measured rather than described."""

    def setUp(self):
        self.account = get_user_model().objects.create_user(
            username=USERNAME, password=PASSPHRASE, is_staff=True)
        self.account.user_permissions.add(
            Permission.objects.get(content_type__app_label='pricing',
                                   codename='view_pricecandidate'))
        response = self.client.post(reverse('staff_login'),
                                    {'username': USERNAME, 'password': PASSPHRASE},
                                    REMOTE_ADDR=ADDRESS)
        self.assertEqual(response.status_code, 302, 'the synthetic login did not succeed')
        self.session_key = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.assertEqual(self.client.get(reverse('staff_prices'), REMOTE_ADDR=ADDRESS).status_code,
                         CASCADE['route before'])
        self.assertEqual(self.client.get(reverse('home'), REMOTE_ADDR=ADDRESS).status_code, 200)
        self.assertEqual(StaffLoginWindow.objects.count(), CASCADE['login windows before'])
        self.assertEqual(PublicReadWindow.objects.count(), CASCADE['read windows before'])
        self.assertEqual(Session.objects.count(), 1, 'the baseline created an extra session row')

    def stored_row(self):
        row = Session.objects.get(session_key=self.session_key)
        return row, DbSessionStore().decode(row.session_data)

    def test_a_rotation_turns_a_staff_200_into_a_302_and_empties_the_session_row(self):
        row_before, decoded_before = self.stored_row()
        self.assertEqual(sorted(decoded_before), SESSION_KEYS,
                         'a live staff session does not hold the four keys the plan names')
        password_before = get_user_model().objects.get(pk=self.account.pk).password
        with override_settings(SECRET_KEY=NEW_KEY):
            response = self.client.get(reverse('staff_prices'), REMOTE_ADDR=ADDRESS)
            self.assertEqual(response.status_code, CASCADE['route after'],
                             'a rotation stopped ending the staff session at its next request')
            self.assertIn(reverse('staff_login'), response.url)
            row_after, decoded_after = self.stored_row()
            self.assertEqual(decoded_after, {}, 'the session row was deleted instead of emptied')
            self.assertEqual(row_after.session_key, row_before.session_key,
                             'the rotation issued a new session key rather than emptying the row')
            self.assertGreaterEqual(row_after.expire_date, row_before.expire_date,
                                    'the emptied row did not keep a live expiry')
            account = get_user_model().objects.get(pk=self.account.pk)
            self.assertEqual(account.password, password_before,
                             'a rotation touched a stored password hash')
            self.assertTrue(check_password(PASSPHRASE, account.password),
                            'the passphrase stopped verifying after a rotation')
            self.assertNotEqual(account.get_session_auth_hash(), decoded_before['_auth_user_hash'],
                                'the session auth hash did not change with the key')

    def test_a_rotation_emits_one_warning_that_nothing_keeps(self):
        with override_settings(SECRET_KEY=NEW_KEY):
            with self.assertLogs('django.security.SuspiciousSession', level='WARNING') as caught:
                self.client.get(reverse('staff_prices'), REMOTE_ADDR=ADDRESS)
        self.assertEqual(len(caught.records), CASCADE['warnings'],
                         'the warning count a rotation produces moved')
        self.assertEqual([record.getMessage() for record in caught.records],
                         ['Session data corrupted'])
        self.assertEqual(caught.records[0].name, 'django.security.SuspiciousSession')
        self.assertEqual(settings.LOGGING, {}, 'the application grew a logging configuration')
        self.assertEqual(logging.getLogger('django.security.SuspiciousSession').handlers, [],
                         'the logger that reports a rotation gained a handler')

    def test_a_rotation_hides_the_invalidated_rows_from_both_session_commands(self):
        before = command_output('list_staff_sessions')
        self.assertIn(f'"username": "{USERNAME}"', before)
        self.assertIn('"sessions_matched": 1', before)
        self.assertIn('"bound": true', before)
        self.assertIn('"guard_would_end_it": false', before)
        alias_before = inventory_alias(before)
        with override_settings(SECRET_KEY=NEW_KEY):
            self.client.get(reverse('staff_prices'), REMOTE_ADDR=ADDRESS)
            after = command_output('list_staff_sessions')
            self.assertIn('"scanned": 1', after, 'the row a rotation emptied was not scanned')
            self.assertIn('"sessions_matched": 0', after,
                          'an invalidated session still appeared in the inventory')
            self.assertIn('"sessions_unbound": 0', after,
                          'an emptied row was reported as unbound rather than invisible')
            self.assertIn('"accounts": []', after)
            revoke = command_output('revoke_staff_sessions', '--all', '--apply')
            self.assertIn('"matched": 0', revoke, 'the revoke command still saw the session')
            self.assertIn('"revoked": 0', revoke, 'the revoke command removed an invalidated row')
            self.assertEqual(Session.objects.count(), 1,
                             'the emptied session row was deleted rather than left behind')
            prune = command_output('cleanup_staff_login_windows', '--apply')
            self.assertIn('"deleted": 0', prune,
                          'the orphaned login windows became prunable immediately')
            self.assertIn('"limit": 500', prune)
        with override_settings(SECRET_KEY=NEW_KEY):
            self.assertNotEqual(list_staff_sessions.session_alias(self.session_key), alias_before,
                                'the inventory alias did not move with the key')

    def test_a_rotation_restarts_both_limiters_and_orphans_their_rows(self):
        login_before = StaffLoginWindow.objects.get()
        read_before = PublicReadWindow.objects.get()
        self.assertEqual(throttle.consume_attempt(ADDRESS), 'allowed')
        self.assertEqual(read_limit.consume_read(ADDRESS), ('allowed', 0))
        self.assertEqual(StaffLoginWindow.objects.count(), CASCADE['login windows before'])
        self.assertEqual(PublicReadWindow.objects.count(), CASCADE['read windows before'])
        with override_settings(SECRET_KEY=NEW_KEY):
            self.assertEqual(throttle.consume_attempt(ADDRESS), 'allowed',
                             'a rotation did not restart the login counter at zero')
            self.assertEqual(read_limit.consume_read(ADDRESS), ('allowed', 0),
                             'a rotation did not restart the read counter at zero')
            self.assertEqual(StaffLoginWindow.objects.count(), CASCADE['login windows after'],
                             'a rotation did not orphan the old login window')
            self.assertEqual(PublicReadWindow.objects.count(), CASCADE['read windows after'],
                             'a rotation did not orphan the old read window')
            keys = set(StaffLoginWindow.objects.values_list('client_key', flat=True))
            self.assertEqual(len(keys), 2, 'the two login windows share a key')
            self.assertIn(login_before.client_key, keys)
            self.assertNotEqual(PublicReadWindow.objects.exclude(
                client_key=read_before.client_key).count(), 0,
                'no new read window was written under the new key')

    def test_a_rotation_denies_a_guarded_write_rechecked_with_the_old_hash(self):
        account = get_user_model().objects.get(pk=self.account.pk)
        old_hash = account.get_session_auth_hash()
        self.assertEqual(recheck_actor(account, ('pricing.view_pricecandidate',),
                                       session_auth_hash=old_hash).pk, account.pk,
                         'the recheck did not accept the account before the rotation')
        with override_settings(SECRET_KEY=NEW_KEY):
            with self.assertRaises(PermissionDenied):
                recheck_actor(account, ('pricing.view_pricecandidate',), session_auth_hash=old_hash)
            self.assertEqual(recheck_actor(account, ('pricing.view_pricecandidate',)).pk, account.pk,
                             'a rotation started denying writes that pass no hash at all')
        with override_settings(SECRET_KEY=NEW_KEY, SECRET_KEY_FALLBACKS=[OLD_KEY]):
            with self.assertRaises(PermissionDenied):
                recheck_actor(account, ('pricing.view_pricecandidate',), session_auth_hash=old_hash)

    def test_a_fallback_rescues_the_row_and_the_signature_but_not_this_projects_guard(self):
        alias_old = inventory_alias(command_output('list_staff_sessions'))
        with override_settings(SECRET_KEY=NEW_KEY, SECRET_KEY_FALLBACKS=[OLD_KEY]):
            row = Session.objects.get(session_key=self.session_key)
            decoded = DbSessionStore().decode(row.session_data)
            self.assertEqual(sorted(decoded), SESSION_KEYS,
                             'a listed fallback stopped rescuing the stored session row')
            self.assertNotEqual(decoded['staff_auth_fingerprint'],
                                session_guard.authorization_fingerprint(self.account.pk),
                                'the guard started accepting a fingerprint made under the old key')
            inventory = command_output('list_staff_sessions')
            self.assertIn('"sessions_matched": 1', inventory,
                          'a fallback stopped making the session visible to the inventory')
            self.assertIn('"bound": true', inventory)
            self.assertIn('"guard_would_end_it": true', inventory,
                          'the inventory stopped reporting the session the guard will end')
            self.assertNotEqual(inventory_alias(inventory), alias_old,
                                'a fallback kept the inventory alias stable, which the plan denies')
            response = self.client.get(reverse('staff_prices'), REMOTE_ADDR=ADDRESS)
            self.assertEqual(response.status_code, CASCADE['route after'],
                             'SECRET_KEY_FALLBACKS made this project\'s guard accept an old hash, '
                             'which is exactly what option D would have to change')
            self.assertEqual(Session.objects.count(), 0,
                             'the cycled session row survived the guard: Django cycles the key '
                             'under a fallback hash and this project then deletes the row')
            self.assertEqual(command_output('list_staff_sessions'),
                             '{"accounts": [], "scan_limit": 5000, "scanned": 0, '
                             '"sessions_matched": 0, "sessions_unbound": 0, "username": null}',
                             'the inventory still described a session a fallback rescue ended')
            fallback_key = throttle._client_key(ADDRESS)
            with self.assertRaises(PermissionDenied):
                recheck_actor(self.account, ('pricing.view_pricecandidate',),
                              session_auth_hash=decoded['_auth_user_hash'])
        with override_settings(SECRET_KEY=NEW_KEY):
            self.assertEqual(throttle._client_key(ADDRESS), fallback_key,
                             'a listed fallback changed the throttle key, which salted_hmac '
                             'cannot do: the limiter keys move with the primary secret alone')
            self.assertNotEqual(StaffLoginWindow.objects.order_by('-started_at').values_list(
                                 'client_key', flat=True).first(), fallback_key,
                                'a listed fallback rewrote the stored login window, which nothing '
                                'in this project does')


class NothingImplementedTests(SimpleTestCase):
    def test_no_rotation_control_exists_while_the_plan_says_so(self):
        flat_text = flat(read(PLAN))
        for phrase in ('This document is a **proposal**', 'no rotation was implemented and reverted',
                       'no cascade of pin failures was run', 'There is one secret'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_text,
                              'the plan stopped stating the absence it is priced against')
        for line in read(SETTINGS).splitlines():
            if 'ROTATION' in line or 'FALLBACK' in line:
                self.assertTrue(line.strip().startswith('#'),
                                'settings.py grew rotation code instead of a comment on its absence')
        self.assertNotIn('SECRET_KEY_ROTATION', read(SETTINGS))
        self.assertEqual([path.name for path in project_modules()
                          if re.search(r'(?i)rotat|rekey|keyring|vault|kms', path.name)], [],
                         'a module named like a key-management control appeared')
        self.assertEqual([path.name for path in command_modules()
                          if re.search(r'(?i)rotat|rekey', path.name)], [],
                         'a rotation command appeared')
        self.assertNotIn('get_session_auth_fallback_hash', read(SESSION_GUARD))
        self.assertEqual(settings.SECRET_KEY_FALLBACKS, [])
        self.assertEqual([line for line in read(ROOT / 'requirements.in').splitlines()
                          if line.strip()], DIRECT_REQUIREMENTS,
                         'a key-management dependency was added to the lock')
