"""Raw controls in selected concurrency-token fields must not be trimmed away."""
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catalog.identity import digest, ingredient_snapshot, package_snapshot
from catalog.models import IngredientDraft, IdentityPackageReview, ProductCandidateReview
from clinical.evidence import evidence_state
from clinical.models import ClinicalDraft, ClinicalDraftReview, ClinicalReferenceAssertion
from pricing.models import PriceCandidateReview
from sources.models import SourceClaimReview

from catalog.identity_forms import (FormulationRevisionForm, IdentityReviewForm, IngredientRevisionForm,
                                    PackageRevisionForm, ProductRevisionForm)
from catalog.staff_forms import ProductReviewForm
from clinical.forms import ReferenceForm, ReviewForm, RevisionForm
from pricing.forms import PriceReviewForm
from sources.forms import SourceReviewForm

from .test_staff_raw_text_controls import DRAFT, FORMULATION, INGREDIENT, PACKAGE, PRODUCT, REFERENCE, REVISION
from . import test_staff_raw_multiline_controls as multiline_fixtures

HASH = 'a' * 64
REVIEW = {'decision': 'defer', 'reason': 'دلیل ساختگی برای بررسی', 'expected_review': '0'}


class RawTokenFormTests(SimpleTestCase):
    cases = (
        (ProductReviewForm, {**REVIEW, 'expected_hash': HASH}, ('expected_review', 'expected_hash')),
        (PriceReviewForm, {**REVIEW, 'expected_product': '0', 'expected_product_hash': ''},
         ('expected_review', 'expected_product', 'expected_product_hash')),
        (SourceReviewForm, {**REVIEW, 'expected_hash': HASH}, ('expected_review', 'expected_hash')),
        (ReviewForm, {**REVIEW, 'expected_hash': HASH, 'expected_evidence_hash': HASH},
         ('expected_review', 'expected_hash', 'expected_evidence_hash')),
        (IdentityReviewForm, {**REVIEW, 'expected_graph_hash': HASH}, ('expected_review', 'expected_graph_hash')),
        (RevisionForm, {**DRAFT, 'expected_parent_hash': HASH, 'change_reason': 'توضیح ساختگی برای اصلاح'},
         ('expected_parent_hash',)),
        (ReferenceForm, {**REFERENCE, 'expected_draft_hash': HASH, 'expected_evidence_hash': HASH},
         ('expected_draft_hash', 'expected_evidence_hash')),
        (IngredientRevisionForm, {**INGREDIENT, **REVISION}, ('expected_graph_hash',)),
        (FormulationRevisionForm, {**FORMULATION, **REVISION}, ('expected_graph_hash',)),
        (ProductRevisionForm, {**{k: v for k, v in PRODUCT.items() if k != 'formulation_id'}, **REVISION}, ('expected_graph_hash',)),
        (PackageRevisionForm, {**{k: v for k, v in PACKAGE.items() if k != 'product_id'}, **REVISION, 'expected_review': '0'},
         ('expected_review', 'expected_graph_hash')),
    )

    def form(self, cls, data):
        return cls({f'p-{key}': value for key, value in data.items()}, prefix='p')

    def test_selected_raw_token_controls_are_invalid_before_trim(self):
        for cls, data, fields in self.cases:
            self.assertTrue(self.form(cls, data).is_valid(), cls.__name__)
            for field in fields:
                for control in ('\x00', '\t', '\n', '\r', '\x1c', '\x7f', '\x85', '\ud800'):
                    for value in (control + data[field], data[field] + control):
                        with self.subTest(form=cls.__name__, field=field, value=ascii(value)):
                            form = self.form(cls, {**data, field: value})
                            self.assertFalse(form.is_valid())
                            self.assertIn(field, form.errors)
                            self.assertNotIn(field, form.cleaned_data)

    def test_ordinary_spaces_and_optional_empty_hash_remain_accepted(self):
        for cls, data, fields in self.cases:
            for field in fields:
                with self.subTest(form=cls.__name__, field=field):
                    form = self.form(cls, {**data, field: ' ' + data[field] + ' '})
                    if field == 'expected_graph_hash':
                        # Identity uses RegexField's existing strict no-strip policy.
                        self.assertFalse(form.is_valid())
                        self.assertIn(field, form.errors)
                    else:
                        self.assertTrue(form.is_valid(), form.errors)


@override_settings(STAFF_PORTAL_ENABLED=True)
class RawTokenHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        # Reuse the same wholly synthetic fixtures; no production DB or data.
        multiline_fixtures.RawMultilineHttpTests.setUpTestData.__func__(cls)

    def test_csrf_authorized_review_tokens_with_controls_do_not_write(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        cases = (
            ('staff_product_detail', [self.product.pk], 'staff_product_review', [self.product.pk], ProductCandidateReview,
             {**REVIEW, 'expected_hash': self.product.payload_sha256}, 'expected_hash'),
            ('staff_price_detail', [self.price.pk], 'staff_price_review', [self.price.pk], PriceCandidateReview,
             {**REVIEW, 'expected_product': '0', 'expected_product_hash': ''}, 'expected_product_hash'),
            ('staff_source_detail', [self.claim.pk], 'staff_source_review', [self.claim.pk], SourceClaimReview,
             {**REVIEW, 'expected_hash': self.claim.payload_sha256}, 'expected_review'),
            ('staff_clinical_detail', [self.draft.pk], 'staff_clinical_review', [self.draft.pk], ClinicalDraftReview,
             {**REVIEW, 'expected_hash': self.draft.payload_sha256, 'expected_evidence_hash': evidence_state(self.draft)['fingerprint']}, 'expected_evidence_hash'),
            ('staff_identity_detail', ['package', self.package.pk], 'staff_identity_review', [self.package.pk], IdentityPackageReview,
             {**REVIEW, 'expected_graph_hash': digest(package_snapshot(self.package))}, 'expected_graph_hash'),
        )
        for detail, detail_args, review, args, model, data, field in cases:
            with self.subTest(detail=detail):
                client.get(reverse(detail, args=detail_args))
                url = reverse(review, args=args)
                tampered = {**data, field: '\x1c' + data[field]}
                self.assertEqual(client.post(url, tampered).status_code, 403)
                response = client.post(url, tampered, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.context['review_form'].errors)
                self.assertEqual(model.objects.count(), 0)
                self.assertIn('no-store', response['Cache-Control'])
                accepted = client.post(url, data, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(accepted.status_code, 302)
                self.assertEqual(model.objects.count(), 1)

    def test_revision_tokens_reject_controls_before_write(self):
        self.client.force_login(self.author)
        clinical = {**DRAFT, 'expected_parent_hash': self.draft.payload_sha256, 'change_reason': 'دلیل اصلاح ساختگی'}
        path = reverse('staff_clinical_revise', args=[self.draft.pk])
        response = self.client.post(path, {**clinical, 'expected_parent_hash': '\x1c' + clinical['expected_parent_hash']})
        self.assertEqual(response.status_code, 200)
        self.assertIn('expected_parent_hash', response.context['form'].errors)
        self.assertEqual(ClinicalDraft.objects.count(), 1)
        identity = {**INGREDIENT, 'expected_graph_hash': digest(ingredient_snapshot(self.ingredient)), 'change_reason': 'دلیل اصلاح ساختگی'}
        path = reverse('staff_identity_revise_component', args=['ingredient', self.ingredient.pk])
        response = self.client.post(path, {**identity, 'expected_graph_hash': '\x1c' + identity['expected_graph_hash']})
        self.assertEqual(response.status_code, 200)
        self.assertIn('expected_graph_hash', response.context['form'].errors)
        self.assertEqual(IngredientDraft.objects.count(), 1)

    def test_reference_and_package_revision_tokens_reject_controls_then_accept_clean_input(self):
        self.client.force_login(self.author)
        reference = {**REFERENCE, 'expected_draft_hash': self.draft.payload_sha256,
                     'expected_evidence_hash': evidence_state(self.draft)['fingerprint']}
        path = reverse('staff_clinical_reference_create', args=[self.draft.pk])
        bad = self.client.post(path, {**reference, 'expected_draft_hash': '\t' + reference['expected_draft_hash']})
        self.assertEqual(bad.status_code, 200)
        self.assertIn('expected_draft_hash', bad.context['form'].errors)
        self.assertContains(bad, 'اطلاعات پنهان فرم معتبر نیست')
        self.assertEqual(ClinicalReferenceAssertion.objects.count(), 0)
        self.assertEqual(self.client.post(path, reference).status_code, 302)
        self.assertEqual(ClinicalReferenceAssertion.objects.count(), 1)

        package = {**PACKAGE, 'quantity': '20', 'change_reason': 'دلیل اصلاح ساختگی برای بسته',
                   'expected_review': '0', 'expected_graph_hash': digest(package_snapshot(self.package))}
        path = reverse('staff_identity_revise', args=[self.package.pk])
        bad = self.client.post(path, {**package, 'expected_review': '\t0'})
        self.assertEqual(bad.status_code, 200)
        self.assertIn('expected_review', bad.context['form'].errors)
        self.assertContains(bad, 'اطلاعات پنهان فرم معتبر نیست')
        self.assertEqual(type(self.package).objects.count(), 1)
        self.assertEqual(self.client.post(path, package).status_code, 302)
        self.assertEqual(type(self.package).objects.count(), 2)
