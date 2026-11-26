"""Every management command is documented where an operator looks, with its real interface.

The project's administrative work happens through management commands, because
`django.contrib.admin` is deliberately not installed (ADR 0218). A command nobody can find
is a command nobody runs: `cleanup_staff_login_windows` existed for a long time documented
only inside a decision record, which is where a reader goes to understand a decision, not to
learn what to type.

So the operator documents — the development guide, the operations runbook and the deployment
guide — are held to the commands themselves:

* the project's command inventory is pinned, so a new command is a deliberate documentation
  decision rather than a silent addition;
* every command is named in at least one operator document;
* every option a command accepts, other than Django's own base options, is mentioned in the
  documents that name it, so the documented interface cannot fall behind the real one;
* a command that writes is documented as read-only without its `--apply`/`--commit` flag, and
  the flag itself is documented;
* every `manage.py <name>` the documents mention is a command that exists;
* a command file on disk and a registered command name are the same set.

This checks that documentation exists and matches the interface. It cannot check that the
documentation is correct, complete, or safe to follow.
"""
import re
from pathlib import Path

from django.core.management import get_commands, load_command_class
from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / 'docs'
OPERATOR_DOCS = ('DEVELOPMENT_GUIDE.md', 'OPERATIONS_RUNBOOK.md', 'DEPLOYMENT.md')
PROJECT_APPS = frozenset({'catalog', 'clinical', 'daroobank', 'ingestion', 'pricing', 'sources',
                          'staff_security'})
BASE_OPTIONS = frozenset({'--force-color', '--help', '--no-color', '--pythonpath', '--settings',
                          '--skip-checks', '--traceback', '--verbosity', '--version'})
WRITE_FLAGS = frozenset({'--apply', '--commit'})
COMMANDS = {
    'check_deployment_readiness': 'daroobank',
    'cleanup_staff_login_windows': 'staff_security',
    'inspect_catalog_irc': 'catalog',
    'inspect_catalog_quality': 'catalog',
    'inspect_ingestion_window': 'ingestion',
    'inspect_postgresql_access': 'catalog',
    'inspect_postgresql_schema': 'catalog',
    'list_price_candidates': 'pricing',
    'list_staff_sessions': 'staff_security',
    'repair_catalog_projection': 'catalog',
    'revoke_staff_sessions': 'staff_security',
    'stage_price_csv': 'pricing',
}
MENTION = re.compile(r'manage\.py ([a-z][a-z0-9_]*)')


def documents():
    return {name: (DOCS / name).read_text(encoding='utf-8') for name in OPERATOR_DOCS}


def project_commands():
    return {name: app for name, app in get_commands().items() if app in PROJECT_APPS}


def options_of(name, app):
    parser = load_command_class(app, name).create_parser('manage.py', name)
    return {option for action in parser._actions for option in action.option_strings
            if option.startswith('--')} - BASE_OPTIONS


def naming_documents(texts, name):
    """The operator documents that name a command, joined for substring checks."""
    return '\n'.join(text for document, text in sorted(texts.items()) if name in text)


class CommandDocumentationTests(SimpleTestCase):
    def test_the_project_command_inventory_is_pinned(self):
        self.assertEqual(project_commands(), COMMANDS,
                         'a management command was added, removed or moved; the operator documents must follow')

    def test_command_files_and_registered_names_are_the_same_set(self):
        for name, app in sorted(COMMANDS.items()):
            with self.subTest(command=name):
                self.assertTrue((ROOT / app / 'management' / 'commands' / f'{name}.py').is_file(),
                                'a registered command has no file in the app that owns it')
        on_disk = {path.stem for app in PROJECT_APPS
                   for path in (ROOT / app / 'management' / 'commands').glob('*.py')
                   if path.stem != '__init__'}
        self.assertEqual(on_disk, set(COMMANDS))

    def test_every_command_is_named_where_an_operator_looks(self):
        texts = documents()
        for name in sorted(COMMANDS):
            with self.subTest(command=name):
                named = [document for document, text in texts.items() if name in text]
                self.assertTrue(named,
                                f'{name} appears in no operator document; a decision record is not a runbook')

    def test_every_option_is_documented_with_its_command(self):
        texts = documents()
        for name, app in sorted(COMMANDS.items()):
            documented = naming_documents(texts, name)
            for option in sorted(options_of(name, app)):
                with self.subTest(command=name, option=option):
                    self.assertIn(option, documented,
                                  f'{name} accepts {option} and the documents that name it do not mention it')

    def test_a_command_that_writes_is_documented_as_read_only_without_its_flag(self):
        texts = documents()
        writers = 0
        for name, app in sorted(COMMANDS.items()):
            flags = sorted(options_of(name, app) & WRITE_FLAGS)
            if not flags:
                continue
            writers += 1
            documented = naming_documents(texts, name)
            with self.subTest(command=name):
                self.assertIn('read-only', documented,
                              f'{name} can write and the documents do not say what it does without a flag')
                for flag in flags:
                    self.assertIn(flag, documented)
        self.assertEqual(writers, 4, 'the set of write-capable commands changed')

    def test_every_command_the_documents_name_exists(self):
        known = set(get_commands())
        for relative in ('README.md', *(f'docs/{name}' for name in OPERATOR_DOCS)):
            text = (ROOT / relative).read_text(encoding='utf-8')
            for name in sorted(set(MENTION.findall(text))):
                with self.subTest(document=relative, command=name):
                    self.assertIn(name, known, 'the documents describe a command that does not exist')

    def test_the_operator_documents_are_the_ones_being_checked(self):
        for name in OPERATOR_DOCS:
            with self.subTest(document=name):
                self.assertTrue((DOCS / name).is_file())
                self.assertGreater(len((DOCS / name).read_text(encoding='utf-8')), 1000,
                                   'an operator document was emptied, which would make the checks pass trivially')
