"""Selected multiline form inputs must not silently lose forbidden raw controls."""
import io

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catalog.identity import digest, ingredient_snapshot, package_snapshot
from catalog.identity_forms import (FormulationRevisionForm, IdentityReviewForm, IngredientRevisionForm,
                                    PackageRevisionForm, ProductRevisionForm)
from catalog.intake import stage_products
from catalog.models import IngredientDraft, IdentityPackageReview, ProductCandidate, ProductCandidateReview
from catalog.staff_forms import ProductReviewForm
from catalog.test_identity import build
from catalog.test_intake import make_csv
from clinical.evidence import evidence_state
from clinical.forms import DraftForm, ReviewForm, RevisionForm
from clinical.models import ClinicalDraft, ClinicalDraftReview
from clinical.services import create_draft
from pricing.forms import PriceReviewForm
from pricing.importer import stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.test_workflow import csv_bytes
from sources.forms import SourceReviewForm
from sources.models import SourceClaimReview
from sources.services import record_claim

from .test_staff_raw_text_controls import DRAFT, FORMULATION, INGREDIENT, PACKAGE, PRODUCT, REVISION

REASON = 'دلیل ساختگی برای بررسی'
HASH = 'a' * 64
REVIEW = {'decision': 'defer', 'reason': REASON, 'expected_review': '0'}


class RawMultilineFormTests(SimpleTestCase):
    cases = (
        (SourceReviewForm, {**REVIEW, 'expected_hash': HASH}, ('reason',)),
        (ReviewForm, {**REVIEW, 'expected_hash': HASH, 'expected_evidence_hash': HASH}, ('reason',)),
        (ProductReviewForm, {**REVIEW, 'expected_hash': HASH}, ('reason',)),
        (PriceReviewForm, {**REVIEW, 'expected_product': '0', 'expected_product_hash': ''}, ('reason',)),
        (IdentityReviewForm, {**REVIEW, 'expected_graph_hash': HASH}, ('reason',)),
        (DraftForm, DRAFT, ('statement',)),
        (RevisionForm, {**DRAFT, 'change_reason': REASON, 'expected_parent_hash': HASH}, ('statement', 'change_reason')),
        (IngredientRevisionForm, {**INGREDIENT, **REVISION}, ('change_reason',)),
        (FormulationRevisionForm, {**FORMULATION, **REVISION}, ('change_reason',)),
        (ProductRevisionForm, {**{k: v for k, v in PRODUCT.items() if k != 'formulation_id'}, **REVISION}, ('change_reason',)),
        (PackageRevisionForm, {**{k: v for k, v in PACKAGE.items() if k != 'product_id'}, **REVISION, 'expected_review': '0'}, ('change_reason',)),
    )

    def form(self, cls, data):
        return cls(data={f'pref-{key}': value for key, value in data.items()}, prefix='pref')

    def test_forbidden_controls_are_rejected_before_trimming(self):
        for cls, data, fields in self.cases:
            self.assertTrue(self.form(cls, data).is_valid(), cls.__name__)
            for field in fields:
                for control in ('\x00', '\x1c', '\x1d', '\x7f', '\x85', '\ud800'):
                    for position in ('start', 'middle', 'end'):
                        text = data[field]
                        value = control + text if position == 'start' else text + control if position == 'end' else text[:4] + control + text[4:]
                        with self.subTest(form=cls.__name__, field=field, control=ascii(control), position=position):
                            form = self.form(cls, {**data, field: value})
                            self.assertFalse(form.is_valid())
                            self.assertIn(field, form.errors)
                            self.assertNotIn(field, form.cleaned_data)

    def test_shared_multiline_policy_matches_service_validation_for_selected_characters(self):
        from clinical.services import DraftError, _validate_text
        from .validation import has_forbidden_multiline_control, valid_review_reason
        for char, forbidden in (('\x1c', True), ('\x00', True), ('\x85', True), ('\ud800', True),
                                ('\n', False), ('\r', False), ('\t', False), ('\u200c', False), (' ', False)):
            value = REASON[:5] + char + REASON[5:]
            with self.subTest(char=ascii(char)):
                self.assertEqual(has_forbidden_multiline_control(value), forbidden)
                self.assertEqual(valid_review_reason(value), not forbidden)
                if forbidden:
                    with self.assertRaises(DraftError):
                        _validate_text('statement', value)
                else:
                    _validate_text('statement', value)

    def test_allowed_multiline_spacing_and_persian_joiner(self):
        for cls, data, fields in self.cases:
            for field in fields:
                text = '  خط اول ساختگی\nخط\u200cدوم\tادامه\r\n  '
                with self.subTest(form=cls.__name__, field=field):
                    form = self.form(cls, {**data, field: text})
                    self.assertTrue(form.is_valid(), form.errors)
                    self.assertEqual(form.cleaned_data[field], text.strip())


@override_settings(STAFF_PORTAL_ENABLED=True)
class RawMultilineHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('multiline-author', is_staff=True)
        cls.reviewer = User.objects.create_user('multiline-reviewer', is_staff=True)
        for app, model in (('catalog', 'productcandidate'), ('pricing', 'pricecandidate'),
                           ('sources', 'sourceclaim'), ('clinical', 'clinicaldraft'), ('catalog', 'identityworkspace')):
            perms = Permission.objects.filter(content_type__app_label=app)
            cls.author.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'add_{model}']))
            cls.reviewer.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'review_{model}']))
        product = dict(source_record_id='multiline-product', name_fa='فرآورده ساختگی', name_en='',
                       manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        price = dict(source_record_id='multiline-price', irc='001', manufacturer='سازنده فرضی', strength='1 mg',
                     dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
                     unit='package', effective_date='', source_published_date='')
        stage_products(io.BytesIO(make_csv([product])), 'منبع ساختگی', 'https://example.org/multiline-product',
                       actor=cls.author, commit=True, rights_attested=True)
        stage_csv(io.BytesIO(csv_bytes([price])), 'منبع ساختگی', 'https://example.org/multiline-price',
                  staged_by=cls.author, commit=True, rights_attested=True)
        cls.product, cls.price = ProductCandidate.objects.get(), PriceCandidate.objects.get()
        cls.claim, _ = record_claim(actor=cls.author, data=dict(source_name='منبع ساختگی',
            source_url='https://example.org/multiline-source', owner='مالک فرضی', evidence_url='https://example.org/evidence',
            evidence_note='', claims_collection=True, claims_storage=False, claims_publication=False, starts_on=None, expires_on=None))
        cls.draft = create_draft(actor=cls.author, data={**{key: value for key, value in DRAFT.items() if key != 'synthetic_ack'},
                                  'reference_published_on': None, 'reference_accessed_on': None})
        cls.ingredient, _, _, _, cls.package = build(cls.author)

    def test_selected_review_posts_reject_raw_control_without_writes_then_accept_multiline(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        cases = (
            ('staff_product_detail', [self.product.pk], 'staff_product_review', [self.product.pk], ProductCandidateReview,
             {**REVIEW, 'expected_hash': self.product.payload_sha256}),
            ('staff_price_detail', [self.price.pk], 'staff_price_review', [self.price.pk], PriceCandidateReview,
             {**REVIEW, 'expected_product': '0', 'expected_product_hash': ''}),
            ('staff_source_detail', [self.claim.pk], 'staff_source_review', [self.claim.pk], SourceClaimReview,
             {**REVIEW, 'expected_hash': self.claim.payload_sha256}),
            ('staff_clinical_detail', [self.draft.pk], 'staff_clinical_review', [self.draft.pk], ClinicalDraftReview,
             {**REVIEW, 'expected_hash': self.draft.payload_sha256, 'expected_evidence_hash': evidence_state(self.draft)['fingerprint']}),
            ('staff_identity_detail', ['package', self.package.pk], 'staff_identity_review', [self.package.pk], IdentityPackageReview,
             {**REVIEW, 'expected_graph_hash': digest(package_snapshot(self.package))}),
        )
        for detail, detail_args, review, review_args, model, data in cases:
            with self.subTest(domain=detail):
                self.assertEqual(client.get(reverse(detail, args=detail_args)).status_code, 200)
                token = client.cookies['csrftoken'].value
                response = client.post(reverse(review, args=review_args), {**data, 'reason': '\x1c' + REASON}, HTTP_X_CSRFTOKEN=token)
                self.assertEqual(response.status_code, 400)
                self.assertIn('reason', response.context['review_form'].errors)
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                self.assertEqual(model.objects.count(), 0)
                accepted = client.post(reverse(review, args=review_args), {**data, 'reason': 'خط اول ساختگی\nخط دوم ساختگی'}, HTTP_X_CSRFTOKEN=token)
                self.assertEqual(accepted.status_code, 302)
                self.assertEqual(model.objects.count(), 1)

    def test_selected_draft_and_revision_posts_do_not_write_for_raw_control(self):
        self.client.force_login(self.author)
        create_url = reverse('staff_clinical_create')
        before = ClinicalDraft.objects.count()
        response = self.client.post(create_url, {**DRAFT, 'statement': '\x1c' + DRAFT['statement']})
        self.assertEqual(response.status_code, 200)
        self.assertIn('statement', response.context['form'].errors)
        self.assertEqual(ClinicalDraft.objects.count(), before)
        revision = {**DRAFT, 'expected_parent_hash': self.draft.payload_sha256, 'change_reason': '\x1c' + REASON}
        response = self.client.post(reverse('staff_clinical_revise', args=[self.draft.pk]), revision)
        self.assertEqual(response.status_code, 200)
        self.assertIn('change_reason', response.context['form'].errors)
        self.assertEqual(ClinicalDraft.objects.count(), before)
        good = self.client.post(reverse('staff_clinical_revise', args=[self.draft.pk]), {**revision, 'change_reason': REASON})
        self.assertEqual(good.status_code, 302)
        self.assertEqual(ClinicalDraft.objects.count(), before + 1)

        identity_url = reverse('staff_identity_revise_component', args=['ingredient', self.ingredient.pk])
        revision = {**INGREDIENT, 'expected_graph_hash': digest(ingredient_snapshot(self.ingredient)),
                    'change_reason': '\x1c' + REASON}
        before = IngredientDraft.objects.count()
        response = self.client.post(identity_url, revision)
        self.assertEqual(response.status_code, 200)
        self.assertIn('change_reason', response.context['form'].errors)
        self.assertEqual(IngredientDraft.objects.count(), before)
        response = self.client.post(identity_url, {**revision, 'change_reason': REASON})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(IngredientDraft.objects.count(), before + 1)
