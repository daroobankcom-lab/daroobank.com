"""The staff MFA plan is a proposal, its prices are the measured ones, and no factor exists.

`docs/MFA_IMPLEMENTATION_PLAN.md` was written as a list of flows an implementation would have to
satisfy. It stated no measurements, so nothing tied it to this tree: a reader could not tell whether
a second factor was one model away, or whether the project had anywhere to put one. This suite pins
the plan to what the authentication surface actually is, so the options in it stay priced against
the code and implementing one becomes a documented event rather than an edit.

What is measured here, and what the plan says because of it:

* there is one login entry point and one factor. `StaffLoginView` is the only `LoginView` subclass
  in the project, its template renders exactly `username` and `password`, and 41 test modules name
  that route — every test module except this one — so the flow is not a local edit;
* no factor state exists. No field on any installed model matches the vocabulary of a factor, no
  module mentions TOTP, WebAuthn, a passkey or an OTP, and the four modules that mention `MFA`
  mention it to exclude it;
* nothing interposes between the password and the session. `AUTH_USER_MODEL`,
  `AUTHENTICATION_BACKENDS`, `PASSWORD_HASHERS`, `SESSION_ENGINE`, `CACHES` and `LOGGING` are all
  left at Django's defaults, no project module calls `authenticate()`, `login()`, `cycle_key()` or
  `check_password()`, one project receiver is connected to `user_logged_in` and none to
  `user_login_failed`, so a failed login is observed by nothing except the optional throttle;
* the primitives a factor needs are absent. `argon2-cffi` and `cryptography` are not installed, the
  preferred hasher is PBKDF2-SHA256, the runtime lock is hash-pinned and audited in CI, the cache is
  per-process and `LOGGING` is empty, so a challenge, a seed at rest and an event record each need a
  decision before they need code.

The prices in the plan are counted from these measurements, not prototyped: no factor was built and
reverted, so no cascade was run. What is not checked is whether MFA should exist, which factors are
acceptable, who may recover one and what an authentication event may record. Those are the seven
numbered decisions the plan leaves open, and no test can make them.
"""
import importlib.util
import json
import re
import weakref
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import get_hasher
from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.test import SimpleTestCase

import daroobank.session_guard  # noqa: F401  (connects the one project auth-signal receiver)
from daroobank import authorization_review

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'MFA_IMPLEMENTATION_PLAN.md'
SECURITY = ROOT / 'docs' / 'SECURITY.md'
EVIDENCE = ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'
REVIEW = ROOT / 'docs' / 'AUTHORIZATION_REVIEW.md'
SETTINGS = ROOT / 'daroobank' / 'settings.py'
FORMS = ROOT / 'daroobank' / 'forms.py'
THROTTLE = ROOT / 'staff_security' / 'throttle.py'
READ_LIMIT = ROOT / 'staff_security' / 'read_limit.py'
WORKFLOW = ROOT / '.github' / 'workflows' / 'checks.yml'
LOGIN_TEMPLATE = ROOT / 'templates' / 'staff' / 'login.html'
SMOKE = ROOT / 'tests' / 'browser' / 'smoke.cjs'
BROWSER_PACKAGE = ROOT / 'tests' / 'browser' / 'package.json'
ADR_DIR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS'

SKIP_PARTS = frozenset({'.venv', '.cache', '.git', 'node_modules', '__pycache__', 'migrations',
                        'staticfiles'})
PROJECT_PACKAGES = ('catalog', 'clinical', 'daroobank', 'ingestion', 'pricing', 'sources',
                    'staff_security', 'tools')
SECTIONS = ['What is true today, measured',
            'Candidate approach and decisions required',
            'Options and what each costs',
            'Required flows',
            'Secret and session boundaries',
            'Verification before any enablement']
DECISIONS = ['Which factors are mandatory, and may a fallback be weaker than the primary?',
             'Where does the pending challenge live?',
             'Where does the factor secret live, and who holds the key?',
             'Which interposition point?',
             'Who may recover a factor, on what proof, and how is that not a bypass?',
             'What is recorded about an authentication event?',
             'What is the lockout policy?']
OPTIONS = ['A. Leave authentication as documented',
           'B. TOTP second factor, standard library only',
           'C. WebAuthn or passkey primary',
           'D. Account-aware lockout, always on, no second factor',
           'E. Delegate authentication to an identity provider at the edge',
           'F. Declare MFA out of Phase 1 scope']
# The counted price of the option an owner is most likely to choose, pinned cell by cell, and the
# measured sentence the schema prices are quoted from.
OPTION_B_PRICE = ('project migrations 17 → 18, `staff_security` 2 → 3, applied 32 → 33, schema '
                  '33 → 34 tables and 19 → 20 attributed models of 25; `requirements.in` 4 → 5 '
                  'pins, `requirements.txt` 94 lines / 7 names / 78 hashes all move, `pip-audit '
                  '--strict` and `tools.verify_runtime_lock` re-run; `AUTHENTICATION_BACKENDS` '
                  'and `CACHES` become project settings; `.env.example` 12 → 13+ variables, '
                  '`compose.yaml` 6 → 7, both counted by '
                  '`daroobank/test_environment_documentation.py`')
MEASURED_SCHEMA_SENTENCE = ('The schema is 33 tables, 279 columns, 111 indexes, 138 '
                            'constraints, 50 foreign keys and 32 applied migrations, built by')
FACTOR_WORDS = re.compile(r'(?i)(mfa|totp|webauthn|passkey|otp|factor|device|credential|'
                          r'challenge|recovery)')
FACTOR_MECHANISMS = re.compile(r'(?i)\b(totp|webauthn|passkey|otp|two[-_ ]factor|'
                               r'multi[-_ ]factor|second factor)\b')
MFA_MENTIONS = ['daroobank/actor_recheck.py',
                'daroobank/management/commands/check_deployment_readiness.py',
                'daroobank/session_guard.py',
                'daroobank/settings.py']
PROJECT_MODULE_COUNT = 127
TEST_MODULE_COUNT = 236
LOGIN_ROUTE_TESTS = 41
ROUTE_COUNT = 55
STAFF_ROWS = 43
PUBLIC_ROWS = 12
USER_COLUMNS = ['id', 'password', 'last_login', 'is_superuser', 'username', 'first_name',
                'last_name', 'email', 'is_staff', 'is_active', 'date_joined']
# The schema and migration counts the plan prices a factor table against, measured on this tree.
CURRENT_SCHEMA = {'tables': 33, 'columns': 279, 'indexes': 111, 'constraints': 138,
                  'foreign keys': 50, 'applied migrations': 32}
MIGRATION_COUNTS = {'catalog': 8, 'clinical': 2, 'ingestion': 2, 'pricing': 2, 'sources': 1,
                    'staff_security': 2}
DIRECT_REQUIREMENTS = ['Django==5.2.19', 'asgiref==3.13.0', 'sqlparse==0.6.1',
                       'psycopg[binary]==3.3.9']
DIGEST_SURFACE = {'salted_hmac': 9, 'constant_time_compare': 7, r'^\s*import hashlib\b': 9,
                  r'^\s*import hmac\b': 1}
LOGIN_MATCH = re.compile(r'staff_login|StaffLoginView|staff/login')


def read(path):
    return path.read_text(encoding='utf-8')


def flat(text):
    """The document as one line, so a hard-wrapped phrase can be matched."""
    return ' '.join(text.split())


def sections(text):
    return re.findall(r'^## (.*)$', text, re.M)


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
    return sorted(str(path.relative_to(ROOT)) for path in pool if re.search(pattern, read(path), re.M))


def other_test_modules():
    """The tree's test modules, minus this suite.

    The counts the plan quotes describe the tree the plan was measured against, so this module
    is excluded from them: naming `staff_login` here must not move the number it pins.
    """
    return [path for path in python_modules()
            if is_test_module(path) and path.name != 'test_mfa_implementation_plan.py']


def project_receivers(signal):
    """The receivers of an auth signal that belong to this project, not to Django."""
    names = []
    for entry in signal.receivers:
        receiver = entry[1]
        target = receiver() if isinstance(receiver, weakref.ref) else receiver
        module = getattr(target, '__module__', '') or ''
        if module.split('.')[0] in PROJECT_PACKAGES:
            names.append(f'{module}.{getattr(target, "__qualname__", target)}')
    return names


def option_rows(text):
    rows = []
    for line in section(text, 'Options and what each costs').splitlines():
        if line.startswith('|') and not set(line.replace('|', '').strip()) <= {'-', ' ', ':'}:
            cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
            if cells and cells[0] != 'Option':
                rows.append(cells)
    return rows


class PlanDocumentTests(SimpleTestCase):
    def test_the_plan_is_an_unowned_proposal_with_seven_numbered_decisions(self):
        text = read(PLAN)
        flat_text = flat(text)
        self.assertEqual(sections(text), SECTIONS, 'the plan lost or reordered a section')
        for phrase in ('This document is a **proposal**',
                       'not an implemented or approved authentication control',
                       'It has no owner and no approval',
                       'must not treat the existing password form',
                       'counted from the pins and files above, not prototyped',
                       'no factor was built and reverted'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_text, 'the plan stopped stating what it is')
        for claim in ('Owner:', 'owned by', 'approved by', 'signed off by'):
            self.assertNotIn(claim, text, 'the plan grew an owner it does not have')
        decisions = re.findall(r'^(\d)\. \*\*(.+?)\*\*', section(
            text, 'Candidate approach and decisions required'), re.M)
        self.assertEqual([number for number, _ in decisions], [str(n) for n in range(1, 8)],
                         'the blocking decisions are no longer seven, numbered in order')
        self.assertEqual([title for _, title in decisions], DECISIONS,
                         'a blocking decision was reworded, reordered or dropped')
        self.assertIn('none of them is answered here', flat_text,
                      'the plan started answering a decision that belongs to an owner')

    def test_the_plan_quotes_the_requirements_it_is_written_against(self):
        plan = flat(read(PLAN))
        security = flat(read(SECURITY))
        for fragment in ('MFA for administrators', 'Argon2-compatible password hashing',
                         'lockout/recovery controls',
                         'This is **not a production security model**. No MFA'):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, security, 'SECURITY.md no longer asks for this')
        self.assertIn('Sixteen guarded write services', flat(read(EVIDENCE)),
                      'the evidence checklist reworded the write-service count')
        self.assertIn('sixteen guarded write services', plan,
                      'the plan stopped pricing its lockout option against the guarded writes')
        self.assertIn('until MFA, throttling and audit exist', read(SETTINGS),
                      'the settings comment that keeps the portal development-only changed')
        self.assertIn('restricted to development until MFA, throttling and audit exist', plan,
                      'the plan stopped quoting the gate it is written against')
        review = flat(read(REVIEW))
        self.assertIn('There is no MFA', review, 'the authorization review dropped its residual')
        self.assertIn('Is MFA in scope for Phase 1', review, 'the review dropped the open question')
        self.assertIn('docs/AUTHORIZATION_REVIEW.md', plan,
                      'the plan stopped naming the review that carries the question')

    def test_every_option_names_a_counted_price_and_something_it_does_not_answer(self):
        rows = option_rows(read(PLAN))
        self.assertEqual([row[0].strip('*` ') for row in rows], OPTIONS,
                         'the options changed order, count or name')
        for row in rows:
            with self.subTest(option=row[0]):
                self.assertEqual(len(row), 4, 'an option row lost a cell')
                price, limit = row[2], row[3]
                self.assertGreaterEqual(len(price), 40, 'an option has no counted price')
                self.assertGreaterEqual(len(limit), 30, 'an option claims to answer everything')
                self.assertTrue(re.search(r'\d', price), 'a price names no count to check')
        prices = {row[0].strip('*` '): row[2] for row in rows}
        self.assertEqual(prices['B. TOTP second factor, standard library only'], OPTION_B_PRICE,
                         'the price of the TOTP option was edited with no measurement behind it')

    def test_every_module_document_and_record_the_plan_names_exists(self):
        text = read(PLAN)
        for name in set(re.findall(r'`([\w./-]+\.py)`', text)):
            with self.subTest(module=name):
                self.assertTrue((ROOT / name).is_file(), f'the plan names {name}, which is missing')
        for name in set(re.findall(r'`([\w./-]+\.(?:cjs|json|yaml|md|txt))`', text)):
            with self.subTest(file=name):
                self.assertTrue((ROOT / name).is_file(), f'the plan names {name}, which is missing')
        for name in set(re.findall(r'`(tools\.[\w.]+)`', text)):
            with self.subTest(dotted=name):
                self.assertIsNotNone(importlib.util.find_spec(name), f'{name} cannot be imported')
        for number in set(re.findall(r'\b0\d{3}\b', text)):
            with self.subTest(adr=number):
                self.assertTrue(list(ADR_DIR.glob(f'{number}-*.md')),
                                f'the plan cites decision record {number}, which does not exist')
        self.assertIn('0230-mfa-implementation-plan.md', text,
                      'the plan does not name the record that measures it')


class MeasuredAuthenticationSurfaceTests(SimpleTestCase):
    def test_there_is_one_login_entry_point_rendering_two_credential_fields(self):
        project = project_modules()
        tests = other_test_modules()
        self.assertEqual(len(project), PROJECT_MODULE_COUNT,
                         'the non-test module count the plan quotes moved')
        self.assertEqual(len(tests), TEST_MODULE_COUNT, 'the test module count the plan quotes moved')
        self.assertEqual(modules_matching(r'\(LoginView\)', project), ['pricing/staff_views.py'],
                         'a second login view appeared')
        self.assertEqual(modules_matching(r'\(LogoutView\)', project), ['pricing/staff_views.py'])
        self.assertEqual(len([path for path in tests if LOGIN_MATCH.search(read(path))]),
                         LOGIN_ROUTE_TESTS,
                         'the count of test modules downstream of the login route moved')
        self.assertEqual(len(list(authorization_review.route_names())), ROUTE_COUNT,
                         'the route count the plan quotes moved')
        self.assertEqual(len(list(authorization_review.staff_rows())), STAFF_ROWS)
        self.assertEqual(len(list(authorization_review.public_rows())), PUBLIC_ROWS)
        self.assertEqual(authorization_review.AUTH_ORDER, ('staff_login', 'staff_logout'))
        template = read(LOGIN_TEMPLATE)
        self.assertEqual(sorted(set(re.findall(r'form\.(\w+)', template)) - {'errors'}),
                         ['password', 'username'],
                         'the login form grew a field, which is a factor decision')
        self.assertIn('csrf_token', template)

    def test_no_factor_state_exists_in_the_schema_or_the_code(self):
        named = [(model._meta.label, field.name)
                 for model in apps.get_models(include_auto_created=True)
                 for field in model._meta.get_fields() if FACTOR_WORDS.search(field.name)]
        self.assertEqual(named, [], f'factor-like fields appeared: {named}')
        project = project_modules()
        self.assertEqual(modules_matching(FACTOR_MECHANISMS.pattern, project), [],
                         'a project module started naming a factor mechanism')
        self.assertEqual(modules_matching(r'\bMFA\b', project), MFA_MENTIONS,
                         'the set of modules that mention MFA changed')
        self.assertEqual(sorted(model.__name__ for model in
                                apps.get_app_config('staff_security').get_models()),
                         ['PublicReadWindow', 'StaffLoginWindow'],
                         'staff_security gained a model, which is an implementation')

    def test_the_account_model_is_stock_django_and_nineteen_models_point_at_it(self):
        settings_text = read(SETTINGS)
        for name in ('AUTH_USER_MODEL', 'AUTHENTICATION_BACKENDS', 'PASSWORD_HASHERS',
                     'SESSION_ENGINE', 'CACHES', 'LOGGING'):
            with self.subTest(setting=name):
                self.assertNotIn(name, settings_text,
                                 f'{name} became a project setting, which the plan says it is not')
        user = get_user_model()
        self.assertEqual(user._meta.label, 'auth.User')
        self.assertEqual([field.name for field in user._meta.local_fields], USER_COLUMNS,
                         'the stock account columns changed')
        self.assertEqual(settings.AUTHENTICATION_BACKENDS,
                         ['django.contrib.auth.backends.ModelBackend'])
        project_models = [model for model in apps.get_models()
                          if model._meta.app_label not in
                          ('auth', 'contenttypes', 'sessions', 'admin', 'staticfiles')]
        self.assertEqual(len(project_models), 24, 'the project model count the plan quotes moved')
        attributed = [model for model in project_models
                      if any(getattr(field, 'remote_field', None)
                             and field.remote_field.model._meta.label == settings.AUTH_USER_MODEL
                             for field in model._meta.get_fields())]
        self.assertEqual(len(attributed), 19, 'the attributed-model count the plan quotes moved')

    def test_nothing_interposes_between_the_password_and_the_session(self):
        project = project_modules()
        for pattern in (r'\b(login|authenticate)\(request', r'\bcycle_key\b', r'\bcheck_password\b'):
            with self.subTest(pattern=pattern):
                self.assertEqual(modules_matching(pattern, project), [],
                                 'project code started doing what Django does at login')
        self.assertEqual(project_receivers(user_logged_in),
                         ['daroobank.session_guard._bind_fingerprint'],
                         'the login signal gained or lost a project receiver')
        self.assertEqual(project_receivers(user_login_failed), [],
                         'something started observing a failed login')
        self.assertEqual(project_receivers(user_logged_out), [],
                         'something started observing a logout')
        self.assertEqual(settings.SESSION_ENGINE, 'django.contrib.sessions.backends.db')
        self.assertEqual(settings.SESSION_COOKIE_AGE, 3600)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertFalse(settings.SESSION_SAVE_EVERY_REQUEST)
        self.assertTrue(settings.SESSION_COOKIE_HTTPONLY)
        self.assertEqual(settings.SESSION_COOKIE_SAMESITE, 'Lax')
        self.assertEqual(settings.CACHES['default']['BACKEND'],
                         'django.core.cache.backends.locmem.LocMemCache',
                         'the cache became shared, which changes where a challenge can live')
        self.assertEqual(settings.LOGGING, {}, 'an application logging configuration appeared')
        self.assertEqual(modules_matching(r'^\s*(import logging|from logging\b)', project), [],
                         'a project module started importing logging')

    def test_both_limiters_are_address_keyed_opt_in_and_neither_is_a_lockout(self):
        throttle = read(THROTTLE)
        self.assertIn('ATTEMPT_LIMIT = 10', throttle)
        self.assertIn('WINDOW = timedelta(seconds=60)', throttle)
        self.assertIn("return 'unavailable'", throttle, 'the throttle stopped failing open')
        self.assertEqual(re.findall(r'def _client_key\((\w+)\)', throttle), ['remote_addr'],
                         'the throttle key gained a dimension, which is an implementation')
        self.assertIn('(client_key, started_at, attempts)', throttle,
                      'the login window grew a column, which would make it account-aware')
        self.assertEqual([field.name for field in apps.get_model(
            'staff_security', 'StaffLoginWindow')._meta.local_fields],
                         ['client_key', 'started_at', 'attempts'],
                         'the login window model grew an account dimension')
        settings_text = read(SETTINGS)
        self.assertIn('STAFF_LOGIN_THROTTLE_ENABLED = DEBUG and', settings_text,
                      'the login throttle is no longer debug-gated and opt-in')
        self.assertIn('PUBLIC_READ_LIMIT_ENABLED = os.environ.get', settings_text)
        self.assertIn('READ_LIMIT = 120', read(READ_LIMIT))
        self.assertIn('WINDOW = timedelta(seconds=60)', read(READ_LIMIT))
        self.assertIn('HMAC of normalized REMOTE_ADDR, not a raw IP or account identifier',
                      read(ROOT / 'staff_security' / 'models.py'),
                      'the window models stopped stating that they hold no account')

    def test_no_cryptographic_primitive_is_available_for_a_secret_at_rest(self):
        for library in ('argon2', 'cryptography', 'pyotp', 'fido2', 'webauthn'):
            with self.subTest(library=library):
                self.assertIsNone(importlib.util.find_spec(library),
                                  f'{library} was installed, which is a dependency decision')
        self.assertEqual(get_hasher('default').algorithm, 'pbkdf2_sha256',
                         'the preferred hasher changed')
        self.assertEqual(len(settings.AUTH_PASSWORD_VALIDATORS), 4)
        self.assertEqual([validator['OPTIONS']['min_length']
                          for validator in settings.AUTH_PASSWORD_VALIDATORS
                          if 'MinimumLength' in validator['NAME']], [12])
        self.assertIn('STAFF_PASSWORD_MAX_CHARACTERS = 4096', read(FORMS))
        project = project_modules()
        for pattern, expected in DIGEST_SURFACE.items():
            with self.subTest(pattern=pattern):
                self.assertEqual(len(modules_matching(pattern, project)), expected,
                                 'the keyed-digest surface the plan counts moved')

    def test_a_dependency_is_a_gated_event_and_configuration_is_counted(self):
        lock = read(ROOT / 'requirements.txt')
        environment = read(ROOT / '.env.example')
        self.assertEqual([line for line in read(ROOT / 'requirements.in').splitlines()
                          if line.strip()], DIRECT_REQUIREMENTS,
                         'the direct requirements the plan prices against moved')
        self.assertEqual(len(re.findall(r'^[A-Za-z0-9_.\[\]-]+==', lock, re.M)), 7,
                         'the pinned name count moved')
        self.assertEqual(len(lock.splitlines()), 94, 'the lock length moved')
        self.assertEqual(lock.count('--hash='), 78, 'the hash count moved')
        workflow = read(WORKFLOW)
        for gate in ('python -m tools.verify_runtime_lock', 'pip install --require-hashes',
                     'pip-audit" --strict'):
            with self.subTest(gate=gate):
                self.assertIn(gate, workflow, 'a CI gate on dependencies disappeared')
        self.assertEqual(len(re.findall(r'^[A-Z_]+=', environment, re.M)), 12,
                         'the .env.example variable count moved')
        self.assertEqual(len(re.findall(r'^DAROOBANK_\w+', environment, re.M)), 6)
        self.assertEqual(len(set(re.findall(r'DAROOBANK_\w+', read(ROOT / 'compose.yaml')))), 6,
                         'the compose variable count moved')

    def test_signed_tokens_are_stateless_and_the_browser_harness_has_no_authenticator(self):
        repair = read(ROOT / 'catalog' / 'projection_repair.py')
        self.assertIn('TOKEN_AGE = 600', repair)
        self.assertIn('MAX_TOKEN_LENGTH = 512', repair)
        self.assertIn('signing.loads(token, salt=SALT, max_age=TOKEN_AGE)', repair)
        self.assertIn('signing.loads', read(ROOT / 'daroobank' / 'signed_cursors.py'))
        smoke = read(SMOKE)
        self.assertEqual(len(smoke.splitlines()), 1564, 'the browser harness changed size')
        self.assertEqual(len(re.findall(r'(?i)webauthn|authenticator', smoke)), 0,
                         'the browser harness grew an authenticator, which is an implementation')
        dependencies = json.loads(read(BROWSER_PACKAGE))['devDependencies']
        self.assertEqual(dependencies['playwright-core'], '1.65.1')
        self.assertIn('@sparticuz/chromium', dependencies)
        self.assertIn('@axe-core/playwright', dependencies)
        self.assertEqual(len(re.findall(r'def test_', read(ROOT / 'daroobank' / 'test_browser.py'))),
                         1, 'the browser suite grew a test')

    def test_the_schema_and_migration_prices_are_the_measured_ones(self):
        plan = flat(read(PLAN))
        for label, value in CURRENT_SCHEMA.items():
            with self.subTest(measurement=label):
                self.assertIn(f'{value} {label}', plan,
                              'the plan quotes a schema number that is not the measured one')
        counts = {app: len(list((ROOT / app / 'migrations').glob('0*.py')))
                  for app in MIGRATION_COUNTS}
        self.assertEqual(counts, MIGRATION_COUNTS, 'the migration inventory changed')
        self.assertEqual(sum(counts.values()), 17, 'the project migration count moved')
        self.assertIn("the project's 17 migrations", plan)
        self.assertIn(MEASURED_SCHEMA_SENTENCE, plan,
                      'the plan quotes a schema sentence that is not the measured one')
        self.assertIn('project migrations 17 → 18', plan,
                      'the plan stopped pricing a factor migration')
        self.assertIn('applied 32 → 33', plan)


class NothingImplementedTests(SimpleTestCase):
    def test_no_factor_exists_while_the_plan_says_so(self):
        flat_text = flat(read(PLAN))
        for phrase in ('This document is a **proposal**', 'no factor was built and reverted',
                       'no cascade was run', 'No factor state exists anywhere'):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, flat_text,
                              'the plan stopped stating the absence it is priced against')
        for line in read(SETTINGS).splitlines():
            if 'MFA' in line:
                self.assertTrue(line.strip().startswith('#'),
                                'settings.py grew MFA code rather than a comment about its absence')
        self.assertNotIn('STAFF_MFA', read(SETTINGS))
        self.assertEqual([path.name for path in project_modules()
                          if re.search(r'(?i)(mfa|factor|totp|webauthn|passkey|otp)', path.name)],
                         [], 'a module named like a factor appeared')
        self.assertEqual([name for name in authorization_review.route_names()
                          if re.search(r'(?i)factor|enroll|device|recover|mfa|passkey', name)], [],
                         'an authentication route appeared')
        self.assertEqual(len(list((ROOT / 'staff_security' / 'migrations').glob('0*.py'))), 2,
                         'staff_security gained a migration')
        self.assertEqual([line for line in read(ROOT / 'requirements.in').splitlines()
                          if line.strip()], DIRECT_REQUIREMENTS,
                         'a factor dependency was added to the lock')
