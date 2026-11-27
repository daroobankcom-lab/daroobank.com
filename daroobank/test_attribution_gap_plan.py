"""The two write paths that name nobody: a proposal, and what is true of them today.

ADR 0220 measured that 19 of the 24 project models name the account that appended them, and that
two places do not: `catalog.ProductPresentation`, the row the public reads, and price staging from
`manage.py stage_price_csv`. It recorded both as measurements and decided neither, which leaves the
question a reviewer actually asks — who is accountable for this row — without an answer and without
a proposal.

`docs/ATTRIBUTION_GAP_PLAN.md` is that proposal, in the form `docs/READ_AUDIT_PLAN.md` and
`docs/MFA_IMPLEMENTATION_PLAN.md` already use: what is true today, six options with a counted price
each, seven decisions owners have to make, and what has to be verified before any implementation.
This suite pins the plan and re-measures the two gaps, so that the proposal cannot drift away from
the code it describes and so that implementing one of its options is a documented event.

What is measured here beyond ADR 0220:

* nothing in project code creates a presentation, publishes one or sets its verification date —
  `published=True` appears once, as a read filter, and `verified_at` is only ever read, rendered,
  serialized or validated, so there is no publication step to attribute;
* a command-line import writes **no receipt and no items**, while the same CSV through the staff
  route writes one `ImportReceipt` naming a required actor plus an item per row, so the import
  inventory a reviewer reads cannot show a command-line staging at all;
* the command is the only project write path that is not debug-gated: neither the command module nor
  `pricing/importer.py` mentions `DEBUG`, and staging still succeeds with debug off, while the
  projection repair, the staff portal and the login throttle all refuse to run outside debug.

The plan is a proposal. Nothing here attributes a row, authorizes an import, approves a publication
path or closes a Phase 1 gate, and all data stays synthetic.
"""
import ast
import csv
import inspect
import io
import re
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command, load_command_class
from django.test import SimpleTestCase, TestCase, override_settings

from catalog.models import ProductPresentation
from ingestion.models import ImportReceipt, ImportReceiptItem
from ingestion.receipts import stage_price_with_receipt
from pricing.importer import FIELDS, stage_csv
from pricing.models import PriceCandidate

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs' / 'ATTRIBUTION_GAP_PLAN.md'
ADR_DIR = ROOT / 'docs' / 'ARCHITECTURE_DECISIONS'
PROJECT_DIRS = ('catalog', 'clinical', 'daroobank', 'ingestion', 'pricing', 'sources',
                'staff_security', 'tools')
OPERATOR_DOCS = ('DEVELOPMENT_GUIDE.md', 'OPERATIONS_RUNBOOK.md', 'DEPLOYMENT.md')
SECTIONS = ['Gap one: the published catalog names nobody, and nothing publishes it',
            'Gap two: command-line price staging names nobody and writes no receipt',
            'Why this is a decision rather than a bug fix',
            'Options and what each costs',
            'Decisions required before implementation',
            'Verification before any implementation']
DECISIONS = ['Is a self-declared name attribution?',
             'May a write path exist outside debug at all?',
             'Does an import without a receipt count as an import?',
             'What is an unattributed rights attestation worth?',
             'What happens to the rows that already exist?',
             'Does the published catalog need a publisher, or a statement that it has none?',
             'Where the record of a command invocation lives.']
OPTIONS = ['A. Leave both gaps as measured',
           'B. `--staged-by <username>` on the command',
           'C. Command staging requires an authenticated session',
           'D. Keep the command, make its rows explicitly terminal',
           'E. `published_by` and `published_at` on the catalog record',
           'F. Declare the catalog seed data loaded outside the application']
COMMAND = 'stage_price_csv'
COMMAND_OPTIONS = {'--attest-authorized', '--commit', '--source-name', '--source-url'}
BASE_OPTIONS = {'--force-color', '--help', '--no-color', '--pythonpath', '--settings',
                '--skip-checks', '--traceback', '--verbosity', '--version'}
WRITE_METHODS = ('create', 'get_or_create', 'bulk_create', 'update', 'save', 'update_or_create')
PUBLICATION_FIELDS = ('published', 'verified_at')
MODULE = re.compile(r'`([a-z][\w/]*\.py)`')
RECORD = re.compile(r'\bADR[s]? (\d{4})\b')
DOCUMENT = re.compile(r'`(docs/[\w.]+\.md)`')
# Counted for the plan's option C, and recounted here so the plan cannot quote a stale surface.
TEST_MODULES_NAMING_COMMAND = 9
COMMAND_MENTIONS_IN_TESTS = 20
TEST_CALLS_THAT_COMMIT = 8
OPERATOR_DOCS_NAMING_COMMAND = 1


def flat(text):
    """The document as one line, so a hard-wrapped phrase can be matched."""
    return ' '.join(text.split())


def read(path):
    return Path(path).read_text(encoding='utf-8')


def sections(text):
    return re.findall(r'^## (.*)$', text, re.M)


def section(text, heading):
    """The body of one `##` section, up to the next heading of any level."""
    match = re.search(rf'^## {re.escape(heading)}$(.*?)(?=^## |\Z)', text, re.M | re.S)
    return match.group(1) if match else ''


def project_modules(include_tests=False):
    files = [ROOT / 'manage.py']
    for name in PROJECT_DIRS:
        for path in sorted((ROOT / name).rglob('*.py')):
            if 'migrations' in path.parts:
                continue
            if not include_tests and 'test' in path.name:
                continue
            files.append(path)
    return sorted(files)


def table_rows(markdown):
    """The cells of every body row of the first table in a section."""
    rows = []
    for line in markdown.splitlines():
        if not line.startswith('|'):
            continue
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if cells and set(cells[0]) <= {'-', ' ', ':'}:
            continue
        rows.append(cells)
    return rows[1:] if rows else []


def write_calls(model_name):
    """`(module, method)` for every literal `Model.<write method>(...)` in project code."""
    sites = []
    for path in project_modules():
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in WRITE_METHODS:
                continue
            receiver = ast.unparse(node.func.value)
            if receiver == model_name or receiver.startswith(f'{model_name}.'):
                sites.append((str(path.relative_to(ROOT)), node.func.attr))
    return sorted(sites)


def published_writes():
    """Writes to a publication field of the catalog record, as `(module, field)`.

    Only the modules that name `ProductPresentation` are scanned, because `published` is also a
    local name in the price importer, where it is a parsed source date and not this field. Two
    shapes count: an attribute assignment such as `product.published = True`, and a keyword argument
    of that name on an ORM write call. A field declaration in a model is neither, and a
    `models.Q(published=False)` inside a database constraint is a read, so both are excluded.
    """
    found = []
    for path in project_modules():
        text = path.read_text(encoding='utf-8')
        if 'ProductPresentation' not in text:
            continue
        relative = str(path.relative_to(ROOT))
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if ast.unparse(node.value).startswith('models.'):
                    continue  # a field declaration, not a write of a value
                targets = [ast.unparse(target) for target in node.targets]
            elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
                targets = [ast.unparse(node.target)]
            else:
                targets = []
            for target in targets:
                # An attribute write only: `published` is also a local name in the price importer,
                # where it holds a parsed source date and has nothing to do with this field.
                if '.' in target and target.rsplit('.', 1)[-1] in PUBLICATION_FIELDS:
                    found.append((relative, target.rsplit('.', 1)[-1]))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr not in WRITE_METHODS:
                    continue
                for keyword in node.keywords:
                    if keyword.arg in PUBLICATION_FIELDS:
                        found.append((relative, keyword.arg))
    return sorted(found)


def command_options():
    """The command's own options, without the base options every Django command accepts."""
    parser = load_command_class('pricing', COMMAND).create_parser('manage.py', COMMAND)
    return {option for action in parser._actions for option in action.option_strings
            if option.startswith('--')} - BASE_OPTIONS


def command_test_surface():
    """`(modules, mentions, committing calls)` for the command across test modules."""
    modules = mentions = 0
    committing = 0
    for path in project_modules(include_tests=True):
        if 'test' not in path.name:
            continue
        text = path.read_text(encoding='utf-8')
        count = text.count(COMMAND)
        if not count:
            continue
        modules += 1
        mentions += count
        for node in ast.walk(ast.parse(text)):
            if not isinstance(node, ast.Call) or ast.unparse(node.func) != 'call_command':
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            if node.args[0].value != COMMAND:
                continue
            if any(keyword.arg == 'commit' and keyword.value is not None
                   and getattr(keyword.value, 'value', None) is True for keyword in node.keywords):
                committing += 1
    return modules, mentions, committing


class PlanDocumentTests(SimpleTestCase):
    def test_the_plan_is_a_proposal_with_no_owner(self):
        text = flat(read(PLAN))
        self.assertIn('This document is a **proposal**, not an implemented or approved control, '
                      'and it has no owner', text)
        self.assertIn('All data stays synthetic', text)
        self.assertIn('nothing here authorizes importing real price data or publishing a real '
                      'catalog row', text)
        self.assertIn('The prices below are counted, not prototyped', text,
                      'the plan should say that no option was built and reverted')

    def test_the_plan_names_both_gaps_before_it_names_any_option(self):
        self.assertEqual(sections(read(PLAN)), SECTIONS)

    def test_the_plan_lists_seven_decisions_in_order(self):
        body = section(read(PLAN), 'Decisions required before implementation')
        self.assertEqual(re.findall(r'^\d+\. \*\*(.+?)\*\*', body, re.M), DECISIONS)

    def test_the_plan_quotes_the_requirements_it_answers(self):
        text = flat(read(PLAN))
        security = flat(read(ROOT / 'docs' / 'SECURITY.md'))
        evidence = flat(read(ROOT / 'docs' / 'PHASE1_RELEASE_EVIDENCE.md'))
        quotes = ('actor, role, target, before/after versions or hashes, decision, time and '
                  'request correlation',
                  'qualified legal/privacy and clinical governance, source rights, retention, '
                  'protected audit and explicit publication approval')
        for quote in quotes:
            with self.subTest(quote=quote[:40]):
                self.assertIn(quote, security + evidence, 'the plan quotes a requirement loosely')
                self.assertIn(quote, text, 'the plan stopped quoting the requirement it answers')

    def test_every_option_names_a_price_and_a_limit(self):
        body = section(read(PLAN), 'Options and what each costs')
        rows = table_rows(body)
        self.assertEqual([row[0].strip('* ') for row in rows], OPTIONS)
        for row in rows:
            with self.subTest(option=row[0][:12]):
                self.assertEqual(len(row), 4, 'an option row lost its price or its limit')
                self.assertGreaterEqual(len(row[2]), 40, 'an option has no real price')
                self.assertGreaterEqual(len(row[3]), 30, 'an option claims to answer everything')

    def test_every_module_record_and_document_the_plan_names_exists(self):
        text = read(PLAN)
        for module in sorted(set(MODULE.findall(text))):
            with self.subTest(module=module):
                relative = module if '/' in module else f'daroobank/{module}'
                self.assertTrue((ROOT / relative).is_file(),
                                'the plan names a module that does not exist')
        for number in sorted(set(RECORD.findall(text))):
            with self.subTest(record=number):
                self.assertTrue(list(ADR_DIR.glob(f'{number}-*.md')),
                                f'ADR {number} does not exist')
        for document in sorted(set(DOCUMENT.findall(text))):
            with self.subTest(document=document):
                self.assertTrue((ROOT / document).is_file(),
                                'the plan names a document that does not exist')
        for name in ('READ_AUDIT_PLAN.md', 'MFA_IMPLEMENTATION_PLAN.md'):
            with self.subTest(plan=name):
                self.assertTrue((ROOT / 'docs' / name).is_file())

    def test_the_counts_the_plan_quotes_are_the_counts_the_code_has(self):
        self.assertEqual(command_options(), COMMAND_OPTIONS,
                         'the command surface the plan prices changed')
        modules, mentions, committing = command_test_surface()
        self.assertEqual((modules, mentions, committing),
                         (TEST_MODULES_NAMING_COMMAND, COMMAND_MENTIONS_IN_TESTS,
                          TEST_CALLS_THAT_COMMIT),
                         'the test surface the plan prices for option C changed')
        documents = [name for name in OPERATOR_DOCS if COMMAND in read(ROOT / 'docs' / name)]
        self.assertEqual(len(documents), OPERATOR_DOCS_NAMING_COMMAND,
                         'the operator documents that name the command changed')
        self.assertEqual(documents, ['DEVELOPMENT_GUIDE.md'])

    def test_the_plan_implements_nothing(self):
        self.assertNotIn('--staged-by', command_options(),
                         'option B was implemented without a decision')
        fields = {field.name for field in ProductPresentation._meta.fields}
        self.assertEqual(fields & {'published_by', 'published_at', 'actor', 'created_at'}, set(),
                         'option E was implemented without a decision')
        signature = inspect.signature(stage_csv)
        self.assertIsNone(signature.parameters['staged_by'].default,
                          'command-line staging now defaults to an account')


class PublishedCatalogGapTests(SimpleTestCase):
    def test_no_project_code_creates_publishes_or_dates_a_presentation(self):
        self.assertEqual(write_calls('ProductPresentation'),
                         [('catalog/projection_repair.py', 'update')],
                         'the published catalog gained a write path; the plan prices six options '
                         'against a schema nothing writes')
        self.assertEqual(published_writes(), [],
                         'project code now publishes a presentation or sets its verification date')
        source = read(ROOT / 'catalog' / 'services.py')
        self.assertEqual(source.count('published=True'), 1)
        self.assertIn('published=True, verified_at__isnull=False', source,
                      'the one occurrence is no longer the read filter the plan describes')
        verified_at = ProductPresentation._meta.get_field('verified_at')
        self.assertTrue(verified_at.null, 'the verification date became required')
        self.assertFalse(verified_at.has_default(),
                         'a default verification date would claim a check nobody performed')


class CommandLineStagingGapTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.stager = user_model.objects.create_user('cli-stager', is_staff=True,
                                                    password='synthetic-only-passphrase')
        for codename in ('view_pricecandidate', 'add_pricecandidate'):
            cls.stager.user_permissions.add(Permission.objects.get(
                codename=codename, content_type__app_label='pricing'))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def write_csv(self, record_id):
        path = Path(self.directory.name) / f'prices-{record_id}.csv'
        with path.open('w', encoding='utf-8', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerow(dict(
                source_record_id=record_id, irc='۰۰۱۲۳۴', manufacturer='شرکت نمونه',
                strength='5 میلی گرم', dosage_form='قرص', package_description='10 عدد',
                amount='۱۲۳٫۵', currency='TOMAN', category='official_consumer', unit='package',
                effective_date='2026-01-02', source_published_date=''))
        return path

    def stage_from_command_line(self, record_id):
        call_command(COMMAND, str(self.write_csv(record_id)), source_name='Synthetic',
                     source_url='https://example.org/feed', commit=True, attest_authorized=True,
                     stdout=io.StringIO())
        return PriceCandidate.objects.get(source_record_id=record_id)

    def test_a_command_line_import_writes_no_receipt_and_no_items(self):
        candidate = self.stage_from_command_line('plan-cli')
        self.assertIsNone(candidate.staged_by_id, 'a command-line staging named an account')
        self.assertTrue(candidate.source_rights_attested,
                        'the attestation the plan calls unattributed is not stored on the row')
        self.assertEqual(ImportReceipt.objects.count(), 0,
                         'a command-line import wrote a receipt')
        self.assertEqual(ImportReceiptItem.objects.count(), 0)

    def test_the_same_csv_through_the_route_writes_a_receipt_naming_the_actor(self):
        path = self.write_csv('plan-route')
        with path.open('rb') as handle:
            stage_price_with_receipt(handle, 'منبع ساختگی', 'https://example.org/feed',
                                     actor=self.stager, rights_attested=True)
        candidate = PriceCandidate.objects.get(source_record_id='plan-route')
        receipt = ImportReceipt.objects.get()
        self.assertEqual(candidate.staged_by_id, self.stager.pk)
        self.assertEqual(receipt.kind, ImportReceipt.PRICE)
        self.assertEqual(receipt.actor_id, self.stager.pk)
        self.assertEqual(receipt.items.count(), 1)
        self.assertEqual(ImportReceiptItem.objects.get().price_candidate_id, candidate.pk)
        self.assertFalse(ImportReceipt._meta.get_field('actor').null,
                         'a receipt can now exist without an account, which is what makes the '
                         'command-line gap a decision rather than an omission')

    def test_the_command_stages_with_debug_off_and_no_module_gates_it(self):
        for relative in ('pricing/management/commands/stage_price_csv.py', 'pricing/importer.py'):
            with self.subTest(module=relative):
                self.assertNotIn('DEBUG', read(ROOT / relative),
                                 'the command grew a debug gate; the plan prices its absence')
        # The positive control: the write paths that do refuse outside debug say so in their source.
        self.assertIn('DEBUG', read(ROOT / 'catalog' / 'projection_repair.py'))
        self.assertIn('STAFF_PORTAL_ENABLED = DEBUG', read(ROOT / 'daroobank' / 'settings.py'))
        with override_settings(DEBUG=False):
            candidate = self.stage_from_command_line('plan-nodebug')
        self.assertIsNone(candidate.staged_by_id)
        self.assertEqual(ImportReceipt.objects.count(), 0,
                         'staging outside debug wrote a receipt')
