"""Every environment variable the application reads is documented where it is set.

Configuration is the part of this project an operator touches without reading code: sixteen
environment variables decide whether debug mode is on, which hosts are served, whether the
staff portal exists, whether health probes are reachable, whether HSTS is sent, whether a proxy
header is trusted, and how the database is reached — including whether that connection is
encrypted. All sixteen are read in one module, `daroobank/settings.py`, and the fail-closed
shape of each is measured elsewhere (`test_nondebug_configuration.py`,
`test_hsts_configuration.py`, `test_database_configuration.py`, and the readiness report of
ADR 0217).

What nothing measured is the documentation side: that the inventory stays complete, that the
template and the Compose stack do not drift from it, and that the deployment guide — the
document an operator follows for a non-debug deployment — names the variables that decide
production behavior. Before this suite, that guide named six of them and never mentioned
`DAROOBANK_DEBUG` or a single `POSTGRES_*` variable, so whether the database connection is
encrypted in transit was documented only in a development template.

The checks are: a pinned AST inventory of what the code reads and what it defaults; the
template naming exactly those variables; Compose setting only variables the code reads, with a
fail-fast form for the four that are required; the deployment guide naming every variable that
is not development-only, stating that the debug switch stays off and that the database link is
verified; the development guide naming the ones a local operator sets; and, in the reverse
direction, no document or deployment file naming a variable the code does not read.

This checks that names appear where they belong. It cannot check that a documented default,
range or warning is the right one, and it does not read the meaning of any sentence.
"""
import ast
import re
from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
SOURCE_DIRS = ('catalog', 'clinical', 'daroobank', 'ingestion', 'pricing', 'sources',
               'staff_security', 'tools', 'tests')
SETTINGS_HELPER = 'required_database_setting'
ENVIRONMENT_FILE = '.env.example'
COMPOSE_FILE = 'compose.yaml'
DEPLOYMENT_GUIDE = 'docs/DEPLOYMENT.md'
DEVELOPMENT_GUIDE = 'docs/DEVELOPMENT_GUIDE.md'
DOCUMENTS = ('README.md', DEPLOYMENT_GUIDE, DEVELOPMENT_GUIDE, 'docs/OPERATIONS_RUNBOOK.md',
             'docs/SECURITY.md', 'docs/TESTING_STRATEGY.md', ENVIRONMENT_FILE, COMPOSE_FILE,
             '.github/workflows/checks.yml')

# The sixteen variables the application reads, and the module that reads each of them.
READS = {
    'DAROOBANK_ALLOWED_HOSTS': 'daroobank/settings.py',
    'DAROOBANK_DEBUG': 'daroobank/settings.py',
    'DAROOBANK_HEALTH_PROBES_ENABLED': 'daroobank/settings.py',
    'DAROOBANK_HSTS_SECONDS': 'daroobank/settings.py',
    'DAROOBANK_PUBLIC_READ_LIMIT': 'daroobank/settings.py',
    'DAROOBANK_SECRET_KEY': 'daroobank/settings.py',
    'DAROOBANK_STAFF_LOGIN_THROTTLE': 'daroobank/settings.py',
    'DAROOBANK_TRUSTED_PROXY_CIDRS': 'daroobank/settings.py',
    'DAROOBANK_TRUST_PROXY_SSL_HEADER': 'daroobank/settings.py',
    'POSTGRES_CONN_MAX_AGE': 'daroobank/settings.py',
    'POSTGRES_DB': 'daroobank/settings.py',
    'POSTGRES_HOST': 'daroobank/settings.py',
    'POSTGRES_PASSWORD': 'daroobank/settings.py',
    'POSTGRES_PORT': 'daroobank/settings.py',
    'POSTGRES_SSLMODE': 'daroobank/settings.py',
    'POSTGRES_USER': 'daroobank/settings.py',
}
# Variables the project only ever gives a default for, and the modules that do it.
DEFAULTS = {'DJANGO_SETTINGS_MODULE': ('catalog/test_synthetic_search_benchmark.py', 'daroobank/wsgi.py',
                                      'manage.py', 'tools/wait_for_database.py')}
# Opt-in switches read by test modules; they gate optional probes and are documented for that audience.
TEST_SWITCHES = {
    'DAROOBANK_BROWSER_TESTS': 'daroobank/test_browser.py',
    'DAROOBANK_ENCRYPTED_RESTORE_TESTS': 'daroobank/test_synthetic_encrypted_restore.py',
    'DAROOBANK_RESTORE_TESTS': 'daroobank/test_synthetic_restore.py',
    'DAROOBANK_SEARCH_BENCHMARK': 'catalog/test_synthetic_search_benchmark.py',
}
# Environment the project reads but does not own.
EXTERNAL = {'GITHUB_ACTIONS': 'daroobank/test_browser.py'}
SWITCH_DOCUMENTS = ('docs/DEVELOPMENT_GUIDE.md', 'docs/TESTING_STRATEGY.md', '.github/workflows/checks.yml')
# Development-only: the opt-in login limiter the development guide documents (ADR 0219).
DEVELOPMENT_ONLY = frozenset({'DAROOBANK_STAFF_LOGIN_THROTTLE'})
PRODUCTION = frozenset(READS) - DEVELOPMENT_ONLY
# What the local Compose stack passes to the application service.
COMPOSE_SETS = frozenset({'DAROOBANK_ALLOWED_HOSTS', 'DAROOBANK_DEBUG', 'DAROOBANK_HEALTH_PROBES_ENABLED',
                          'DAROOBANK_PUBLIC_READ_LIMIT', 'DAROOBANK_SECRET_KEY',
                          'DAROOBANK_STAFF_LOGIN_THROTTLE', 'POSTGRES_CONN_MAX_AGE', 'POSTGRES_DB',
                          'POSTGRES_HOST', 'POSTGRES_PASSWORD', 'POSTGRES_PORT', 'POSTGRES_USER'})
# Required variables, and how many Compose services set them: the database service needs the
# three connection settings too, while only the application service reads the secret key.
COMPOSE_REQUIRED = {'DAROOBANK_SECRET_KEY': 1, 'POSTGRES_DB': 2, 'POSTGRES_PASSWORD': 2,
                    'POSTGRES_USER': 2}
# What a local operator sets by hand, per the development guide.
DEVELOPMENT_SETS = frozenset({'DAROOBANK_ALLOWED_HOSTS', 'DAROOBANK_DEBUG', 'DAROOBANK_SECRET_KEY',
                              'DAROOBANK_STAFF_LOGIN_THROTTLE', 'POSTGRES_CONN_MAX_AGE', 'POSTGRES_DB',
                              'POSTGRES_HOST', 'POSTGRES_PASSWORD', 'POSTGRES_PORT', 'POSTGRES_SSLMODE',
                              'POSTGRES_USER'})
VARIABLE = re.compile(r'\b(?:DAROOBANK|POSTGRES)_[A-Z0-9_]+\b')
ASSIGNMENT = re.compile(r'^#?\s*((?:DAROOBANK|POSTGRES)_[A-Z0-9_]+)=')
ENVIRONMENT_ENTRY = re.compile(r'^\s+((?:DAROOBANK|POSTGRES)_[A-Z0-9_]+):(.*)$')
OFF_MARKERS = ('0', 'off', 'not `1`', 'unset', 'disabled')


def project_modules():
    """Every project Python module, including tests but never migrations."""
    files = [ROOT / 'manage.py']
    files += [path for name in SOURCE_DIRS for path in sorted((ROOT / name).rglob('*.py'))
              if 'migrations' not in path.parts]
    return sorted(files)


def literal_environment_accesses(path):
    """`(variable, kind)` for each environment name this module mentions as a literal."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if isinstance(node, ast.Call):
            attribute = isinstance(node.func, ast.Attribute)
            name = node.func.attr if attribute else getattr(node.func, 'id', None)
            base = ast.unparse(node.func.value) if attribute else ''
            if not (node.args and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                continue
            if base == 'os.environ' and name in ('get', 'setdefault'):
                found.append((node.args[0].value, name))
            elif name == SETTINGS_HELPER:
                found.append((node.args[0].value, 'get'))
        elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == 'os.environ' \
                and isinstance(node.slice, ast.Constant) and isinstance(node.slice.value, str):
            found.append((node.slice.value, 'get'))
    return found


def environment_inventory():
    """Four `{variable: (modules)}` inventories: application reads, test switches, defaults, foreign."""
    buckets = {'reads': {}, 'switches': {}, 'defaults': {}, 'external': {}}
    for path in project_modules():
        relative = str(path.relative_to(ROOT))
        for variable, kind in literal_environment_accesses(path):
            if variable in DEFAULTS or kind == 'setdefault':
                bucket = 'defaults'
            elif 'test' not in path.name:
                bucket = 'reads'
            elif variable.startswith(('DAROOBANK_', 'POSTGRES_')):
                bucket = 'switches'
            else:
                bucket = 'external'
            buckets[bucket].setdefault(variable, set()).add(relative)
    return {name: {variable: tuple(sorted(modules)) for variable, modules in found.items()}
            for name, found in buckets.items()}


def compose_environment():
    """`[(variable, value expression)]` for every environment entry of the Compose file.

    A variable can appear more than once — the database service and the application service each
    set the connection settings — so occurrences are kept rather than collapsed into a dict.
    """
    entries = []
    for line in (ROOT / COMPOSE_FILE).read_text(encoding='utf-8').splitlines():
        match = ENVIRONMENT_ENTRY.match(line)
        if match:
            entries.append((match.group(1), match.group(2).strip()))
    return entries


def expectation_cell(relative, variable):
    """The 'expected in production' cell of the configuration table row for one variable."""
    for line in (ROOT / relative).read_text(encoding='utf-8').splitlines():
        if line.startswith('|') and f'`{variable}`' in line:
            cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
            if len(cells) >= 3:
                return cells[2]
    return ''


class EnvironmentInventoryTests(SimpleTestCase):
    def test_the_environment_inventory_is_pinned(self):
        found = environment_inventory()
        self.assertEqual(found['reads'], {name: (module,) for name, module in READS.items()},
                         'the set of environment variables the application reads changed')
        self.assertEqual(found['switches'], {name: (module,) for name, module in TEST_SWITCHES.items()},
                         'the set of opt-in test switches changed')
        self.assertEqual(found['defaults'], {name: modules for name, modules in DEFAULTS.items()},
                         'the set of environment variables the code defaults changed')
        self.assertEqual(found['external'], {name: (module,) for name, module in EXTERNAL.items()},
                         'the project reads a foreign environment variable nobody pinned')
        self.assertEqual(set(found['reads']) & set(found['switches']), set())

    def test_the_template_names_every_variable_and_nothing_else(self):
        named = set()
        for line in (ROOT / ENVIRONMENT_FILE).read_text(encoding='utf-8').splitlines():
            match = ASSIGNMENT.match(line)
            if match:
                named.add(match.group(1))
        self.assertEqual(named, set(READS),
                         f'{ENVIRONMENT_FILE} drifted from the variables the code reads')

    def test_compose_sets_only_variables_the_code_reads(self):
        entries = compose_environment()
        self.assertEqual({name for name, _value in entries}, COMPOSE_SETS)
        self.assertLessEqual({name for name, _value in entries}, set(READS),
                             'the Compose stack sets a variable the application never reads')
        for variable, occurrences in sorted(COMPOSE_REQUIRED.items()):
            values = [value for name, value in entries if name == variable]
            with self.subTest(variable=variable):
                self.assertEqual(len(values), occurrences,
                                 'the services that set a required variable changed')
                for value in values:
                    self.assertIn(':?', value,
                                  'a required variable should make Compose refuse to start without it')

    def test_no_document_names_a_variable_the_code_does_not_read(self):
        known = set(READS) | set(DEFAULTS) | set(TEST_SWITCHES)
        for relative in DOCUMENTS:
            text = (ROOT / relative).read_text(encoding='utf-8')
            for variable in sorted(set(VARIABLE.findall(text))):
                with self.subTest(document=relative, variable=variable):
                    self.assertIn(variable, known,
                                  'a variable is documented that the application does not read')


class EnvironmentDocumentationTests(SimpleTestCase):
    def test_the_deployment_guide_names_every_production_variable(self):
        text = (ROOT / DEPLOYMENT_GUIDE).read_text(encoding='utf-8')
        for variable in sorted(PRODUCTION):
            with self.subTest(variable=variable):
                self.assertIn(variable, text,
                              'a variable that decides production behavior is absent from the deployment guide')

    def test_the_deployment_guide_states_the_debug_switch_is_off_and_the_link_verified(self):
        debug = expectation_cell(DEPLOYMENT_GUIDE, 'DAROOBANK_DEBUG')
        self.assertTrue(debug, 'the deployment guide has no configuration row for the debug switch')
        self.assertTrue(any(marker in debug for marker in OFF_MARKERS),
                        'the deployment guide names DAROOBANK_DEBUG without saying it stays off')
        sslmode = expectation_cell(DEPLOYMENT_GUIDE, 'POSTGRES_SSLMODE')
        self.assertTrue(sslmode, 'the deployment guide has no configuration row for the database TLS mode')
        self.assertIn('verify-full', sslmode,
                      'the deployment guide names POSTGRES_SSLMODE without naming a verified mode')

    def test_every_opt_in_test_switch_is_documented(self):
        haystack = '\n'.join((ROOT / relative).read_text(encoding='utf-8') for relative in SWITCH_DOCUMENTS)
        for variable in sorted(TEST_SWITCHES):
            with self.subTest(variable=variable):
                self.assertIn(variable, haystack,
                              'an opt-in switch exists that no document tells a reader how to turn on')

    def test_the_development_guide_names_what_a_local_operator_sets(self):
        text = (ROOT / DEVELOPMENT_GUIDE).read_text(encoding='utf-8')
        for variable in sorted(DEVELOPMENT_SETS):
            with self.subTest(variable=variable):
                self.assertIn(variable, text)
        self.assertEqual(DEVELOPMENT_SETS | PRODUCTION, set(READS),
                         'the two audiences no longer cover the inventory between them')
