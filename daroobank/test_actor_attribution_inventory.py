"""Which rows in this schema can answer "who did this, and when".

Every staff write in this project appends a row: a draft, a review, a revision, a receipt.
Nothing is updated in place, so the schema has no `auto_now` field at all and instead relies
on a creation timestamp plus an actor foreign key on the row itself. That makes attribution a
property of the schema rather than of a log somebody has to remember to write, and it is worth
pinning, because the two places where the property does not hold are exactly the places a
reviewer will ask about:

* `catalog.ProductPresentation` — the published catalog the public reads — has no actor column
  and no creation timestamp, and no code path in the project creates one. The single write to
  it is the projection repair, which changes two derived search fields and records nothing.
* `pricing.PriceCandidate.staged_by` is the one nullable actor column. Staging through the
  staff route names the session account; staging through `manage.py stage_price_csv` names
  nobody (ADR 0195 records the choice), and because rows are reused on an identical payload, a
  candidate first staged from the command line never acquires an actor — and can never be
  reviewed in the portal, which requires a known stager.

These are measurements of what the schema records. They are not an audit log: nothing here is
tamper-resistant, nothing is retained on a policy, and no row records a change to another row.
"""
import ast
import csv
import io
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management import call_command
from django.db import models
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catalog.models import ProductPresentation
from catalog.projection_repair import preview_projection
from pricing.importer import FIELDS, stage_csv
from pricing.models import PriceCandidate

ROOT = Path(__file__).resolve().parent.parent
PROJECT_APPS = ('catalog', 'clinical', 'ingestion', 'pricing', 'sources', 'staff_security')
WRITE_METHODS = frozenset({'bulk_create', 'bulk_update', 'create', 'delete', 'get_or_create',
                           'save', 'update', 'update_or_create'})

# label -> the foreign key that names the account responsible for the row
ACTORS = {
    'catalog.ProductCandidate': 'staged_by',
    'catalog.ProductCandidateReview': 'reviewer',
    'catalog.IngredientDraft': 'recorded_by',
    'catalog.FormulationDraft': 'recorded_by',
    'catalog.IdentityProductDraft': 'recorded_by',
    'catalog.IdentityPackageDraft': 'recorded_by',
    'catalog.IdentityPackageReview': 'reviewer',
    'catalog.IdentityPackageRevision': 'recorded_by',
    'catalog.IngredientRevision': 'recorded_by',
    'catalog.FormulationRevision': 'recorded_by',
    'catalog.ProductRevision': 'recorded_by',
    'pricing.PriceCandidate': 'staged_by',
    'pricing.PriceCandidateReview': 'reviewer',
    'sources.SourceClaim': 'recorded_by',
    'sources.SourceClaimReview': 'reviewer',
    'ingestion.ImportReceipt': 'actor',
    'clinical.ClinicalDraft': 'author',
    'clinical.ClinicalDraftReview': 'reviewer',
    'clinical.ClinicalReferenceAssertion': 'recorded_by',
}
# label -> the field that records when the row appeared
CREATED = {
    'catalog.ProductCandidate': 'collected_at',
    'catalog.ProductCandidateReview': 'created_at',
    'catalog.IngredientDraft': 'created_at',
    'catalog.FormulationDraft': 'created_at',
    'catalog.IdentityProductDraft': 'created_at',
    'catalog.IdentityPackageDraft': 'created_at',
    'catalog.IdentityPackageReview': 'created_at',
    'catalog.IdentityPackageRevision': 'created_at',
    'catalog.IngredientRevision': 'created_at',
    'catalog.FormulationRevision': 'created_at',
    'catalog.ProductRevision': 'created_at',
    'pricing.PriceCandidate': 'collected_at',
    'pricing.PriceCandidateReview': 'created_at',
    'sources.SourceClaim': 'recorded_at',
    'sources.SourceClaimReview': 'created_at',
    'ingestion.ImportReceipt': 'created_at',
    'clinical.ClinicalDraft': 'created_at',
    'clinical.ClinicalDraftReview': 'created_at',
    'clinical.ClinicalReferenceAssertion': 'created_at',
}
UNATTRIBUTED = {
    'catalog.ProductPresentation': 'the published catalog record; no application code creates one',
    'catalog.FormulationComponent': 'a child of FormulationDraft, attributed through its parent',
    'ingestion.ImportReceiptItem': 'a child of ImportReceipt, attributed through its parent',
    'staff_security.StaffLoginWindow': 'a synthetic throttle row keyed by an address digest',
    'staff_security.PublicReadWindow': 'a synthetic read-counter row keyed by an address digest',
}
PARENTS = {'catalog.FormulationComponent': ('formulation', 'catalog.FormulationDraft'),
           'ingestion.ImportReceiptItem': ('receipt', 'ingestion.ImportReceipt')}
PRESENTATION_MODULES = frozenset({'catalog/models.py', 'catalog/services.py', 'catalog/quality.py',
                                  'catalog/quality_irc.py', 'catalog/projection_repair.py',
                                  'pricing/models.py', 'pricing/importer.py'})


def project_models():
    return {model._meta.label: model for app in PROJECT_APPS
            for model in apps.get_app_config(app).get_models()}


def user_fields(model):
    return [field for field in model._meta.get_fields()
            if isinstance(field, models.ForeignKey)
            and getattr(field.remote_field, 'model', None) is not None
            and field.remote_field.model._meta.label == settings.AUTH_USER_MODEL]


def project_sources():
    """Every project module that is not a test and not a migration."""
    return sorted(path for app in PROJECT_APPS for path in (ROOT / app).rglob('*.py')
                  if 'test' not in path.name and 'migrations' not in path.parts)


def write_call_sites(model_name):
    """`(module, method)` for each literal `Model....<write method>(...)` call in project code."""
    sites = []
    for path in project_sources():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in WRITE_METHODS:
                continue
            receiver = ast.unparse(node.func.value)
            if receiver == model_name or receiver.startswith(f'{model_name}.'):
                sites.append((str(path.relative_to(ROOT)), node.func.attr))
    return sorted(sites)


def modules_naming(model_name):
    return frozenset(str(path.relative_to(ROOT)) for path in project_sources()
                     if model_name in path.read_text(encoding='utf-8'))


class ActorInventoryTests(SimpleTestCase):
    def test_the_actor_inventory_is_pinned(self):
        models_by_label = project_models()
        self.assertEqual(len(models_by_label), 24, 'the project model count changed')
        attributed = {label for label, model in models_by_label.items() if user_fields(model)}
        self.assertEqual(attributed, set(ACTORS))
        self.assertEqual(set(models_by_label) - attributed, set(UNATTRIBUTED))
        for label, field in sorted(ACTORS.items()):
            with self.subTest(model=label):
                self.assertEqual([each.name for each in user_fields(models_by_label[label])], [field])

    def test_actor_columns_are_protected_and_required_except_one(self):
        nullable = []
        for label, name in sorted(ACTORS.items()):
            field = project_models()[label]._meta.get_field(name)
            with self.subTest(model=label):
                self.assertIs(field.remote_field.on_delete, models.PROTECT,
                              'deleting an account must not be able to erase who wrote a row')
                if field.null:
                    nullable.append(label)
        self.assertEqual(nullable, ['pricing.PriceCandidate'],
                         'the set of actor columns that may hold no account changed')

    def test_every_attributed_model_records_when_its_row_was_created(self):
        for label, name in sorted(CREATED.items()):
            field = project_models()[label]._meta.get_field(name)
            with self.subTest(model=label):
                self.assertIsInstance(field, models.DateTimeField)
                self.assertTrue(field.auto_now_add)
        self.assertEqual(set(CREATED), set(ACTORS))
        for label in sorted(UNATTRIBUTED):
            with self.subTest(model=label):
                self.assertEqual([field.name for field in project_models()[label]._meta.get_fields()
                                  if isinstance(field, models.DateTimeField) and field.auto_now_add], [])

    def test_no_project_model_records_when_a_row_changed(self):
        changed = [f'{label}.{field.name}' for label, model in sorted(project_models().items())
                   for field in model._meta.get_fields()
                   if isinstance(field, models.DateTimeField) and field.auto_now]
        self.assertEqual(changed, [],
                         'a modification timestamp appeared; the schema has always been append-only')

    def test_unattributed_children_point_at_an_attributed_parent(self):
        for label, (field_name, parent_label) in sorted(PARENTS.items()):
            field = project_models()[label]._meta.get_field(field_name)
            with self.subTest(model=label):
                self.assertEqual(field.remote_field.model._meta.label, parent_label)
                self.assertIs(field.remote_field.on_delete, models.PROTECT)
                self.assertIn(parent_label, ACTORS, 'a child is attributed through a parent that is not')
                self.assertFalse(field.null, 'the parent link must be required for the attribution to hold')

    def test_the_published_catalog_record_names_nobody_and_has_one_write_path(self):
        presentation = project_models()['catalog.ProductPresentation']
        self.assertEqual(user_fields(presentation), [])
        self.assertEqual(modules_naming('ProductPresentation'), PRESENTATION_MODULES,
                         'a module now touches the published catalog record; that is a documented event')
        self.assertEqual(write_call_sites('ProductPresentation'),
                         [('catalog/projection_repair.py', 'update')],
                         'the published catalog gained a write path that records no actor')
        # Positive control: the same scan does see a model that the staff routes write.
        self.assertIn(('sources/services.py', 'get_or_create'), write_call_sites('SourceClaim'))


@override_settings(DEBUG=True, SECRET_KEY='synthetic-test-secret-key')
class PublishedCatalogAttributionTests(TestCase):
    def test_a_projection_repair_changes_two_fields_and_creates_no_row_anywhere(self):
        presentation = ProductPresentation.objects.create(
            name_fa='محصول ساختگی', name_en='Synthetic', manufacturer='شرکت نمونه',
            strength='۵ میلی‌گرم', dosage_form='قرص', package_description='۱۰ عدد', irc='001',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True)
        fields = [field.name for field in ProductPresentation._meta.get_fields() if field.concrete]
        ProductPresentation.objects.filter(pk=presentation.pk).update(irc='002')
        before = ProductPresentation.objects.filter(pk=presentation.pk).values(*fields)[0]
        counts = {label: model.objects.count() for label, model in sorted(project_models().items())}

        token = preview_projection(presentation_id=presentation.pk)['token']
        out = io.StringIO()
        call_command('repair_catalog_projection', presentation_id=presentation.pk, commit=True,
                     confirm_synthetic=True, token=token, stdout=out)
        report = json.loads(out.getvalue())

        self.assertEqual(report['status'], 'repaired')
        self.assertEqual(set(report['fields']), {'irc_normalized', 'search_text'})
        after = ProductPresentation.objects.filter(pk=presentation.pk).values(*fields)[0]
        self.assertEqual({key: after[key] for key in fields if key not in report['fields']}, 
                         {key: before[key] for key in fields if key not in report['fields']},
                         'the repair touched a source, identity or publication field')
        self.assertEqual({label: model.objects.count() for label, model in sorted(project_models().items())},
                         counts, 'the only write to the published catalog left a row somewhere')


class CommandLineStagingAttributionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='محصول ساختگی', name_en='Synthetic', manufacturer='شرکت نمونه',
            strength='۵ میلی‌گرم', dosage_form='قرص', package_description='۱۰ عدد', irc='001234',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=True)
        user_model = get_user_model()
        cls.stager = user_model.objects.create_user('stager', password='test-only-strong-passphrase',
                                                    is_staff=True)
        cls.reviewer = user_model.objects.create_user('reviewer', password='test-only-strong-passphrase',
                                                      is_staff=True)
        for account, codenames in ((cls.stager, ('view_pricecandidate', 'add_pricecandidate')),
                                   (cls.reviewer, ('view_pricecandidate', 'review_pricecandidate'))):
            for codename in codenames:
                account.user_permissions.add(Permission.objects.get(
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
                source_record_id=record_id, irc='۰۰۱۲۳۴', manufacturer='شركت نمونه',
                strength='5 میلی گرم', dosage_form='قرص', package_description='10 عدد',
                amount='۱۲۳٫۵', currency='TOMAN', category='official_consumer', unit='package',
                effective_date='2026-01-02', source_published_date=''))
        return path

    def detail(self, candidate):
        self.client.force_login(self.reviewer)
        response = self.client.get(reverse('staff_price_detail', args=[candidate.pk]))
        self.assertEqual(response.status_code, 200)
        return response

    def test_command_line_staging_names_no_account_and_the_portal_cannot_review_it(self):
        path = self.write_csv('cli-1')
        call_command('stage_price_csv', str(path), source_name='Synthetic',
                     source_url='https://example.org/feed', commit=True, attest_authorized=True,
                     stdout=io.StringIO())
        unattributed = PriceCandidate.objects.get(source_record_id='cli-1')
        self.assertIsNone(unattributed.staged_by_id, 'a command-line staging recorded an account')

        response = self.detail(unattributed)
        self.assertIsNone(response.context['candidate'].display_stager)
        self.assertFalse(response.context['can_review'])
        self.assertIsNone(response.context['review_form'])

    def test_the_route_path_names_the_session_account_and_the_portal_can_review_it(self):
        with self.write_csv('route-1').open('rb') as handle:
            stage_csv(handle, 'منبع آزمایشی', 'https://example.org/feed', commit=True,
                      rights_attested=True, staged_by=self.stager)
        attributed = PriceCandidate.objects.get(source_record_id='route-1')
        self.assertEqual(attributed.staged_by_id, self.stager.pk)

        response = self.detail(attributed)
        self.assertEqual(response.context['candidate'].display_stager.pk, self.stager.pk)
        self.assertTrue(response.context['can_review'])
        self.assertIsNotNone(response.context['review_form'])

    def test_a_row_first_staged_from_the_command_line_never_acquires_an_actor(self):
        path = self.write_csv('replay-1')
        call_command('stage_price_csv', str(path), source_name='Synthetic',
                     source_url='https://example.org/feed', commit=True, attest_authorized=True,
                     stdout=io.StringIO())
        unattributed = PriceCandidate.objects.get(source_record_id='replay-1')
        self.assertIsNone(unattributed.staged_by_id)

        # The identical payload through the staff route reuses the row instead of writing a new one.
        with path.open('rb') as handle:
            stage_csv(handle, 'Synthetic', 'https://example.org/feed', commit=True,
                      rights_attested=True, staged_by=self.stager)
        unattributed.refresh_from_db()
        self.assertEqual(PriceCandidate.objects.filter(source_record_id='replay-1').count(), 1)
        self.assertIsNone(unattributed.staged_by_id,
                          're-staging an unattributed candidate through the route gave it an actor')
        self.assertFalse(self.detail(unattributed).context['can_review'])
