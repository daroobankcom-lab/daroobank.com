"""Selected single-value staff inputs must not silently choose among duplicates."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils.datastructures import MultiValueDict

from catalog.identity import MAX_COMPONENTS
from catalog.identity_forms import ComponentForm, ComponentFormSet, IdentityReviewForm
from catalog.models import FormulationComponent, FormulationDraft, ProductCandidate
from catalog.staff_forms import ProductReviewForm, ProductUploadForm
from catalog.test_intake import make_csv
from clinical.forms import DraftForm, ReferenceForm, ReviewForm
from clinical.models import ClinicalDraft
from ingestion.models import ImportReceipt, ImportReceiptItem
from pricing.forms import PriceReviewForm, PriceUploadForm
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes
from sources.forms import SourceClaimForm, SourceReviewForm
from sources.models import SourceClaim, SourceClaimReview
from . import test_staff_raw_multiline_controls as fixtures
from .test_staff_raw_text_controls import COMPONENT, DRAFT, FORMULATION, REFERENCE, SOURCE


class DuplicateSingleValueFormsTests(SimpleTestCase):
    review = {'decision': 'defer', 'reason': 'دلیل ساختگی برای بررسی', 'expected_review': '0'}
    cases = (
        (SourceClaimForm, SOURCE, ('owner', 'source_url', 'starts_on')),
        (DraftForm, DRAFT, ('subject', 'statement', 'audience', 'reference_published_on')),
        (ReferenceForm, REFERENCE, ('reference_url', 'relation', 'expected_draft_hash')),
        (ComponentForm, COMPONENT, ('ingredient_id', 'numerator', 'numerator_unit')),
        (SourceReviewForm, {**review, 'expected_hash': 'a' * 64}, ('decision', 'reason', 'expected_hash')),
        (ReviewForm, {**review, 'expected_hash': 'a' * 64, 'expected_evidence_hash': 'b' * 64},
         ('decision', 'reason', 'expected_evidence_hash')),
        (ProductReviewForm, {**review, 'expected_hash': 'a' * 64}, ('decision', 'reason', 'expected_hash')),
        (PriceReviewForm, {**review, 'expected_product': '0', 'expected_product_hash': ''},
         ('decision', 'reason', 'expected_review', 'expected_product')),
        (IdentityReviewForm, {**review, 'expected_graph_hash': 'a' * 64}, ('decision', 'reason', 'expected_graph_hash')),
    )

    def test_duplicate_identical_and_conflicting_values_are_invalid_with_prefix(self):
        for cls, data, fields in self.cases:
            for field in fields:
                last = data.get(field, '')
                for first in (last, '\x1cprivate-first'):
                    with self.subTest(form=cls.__name__, field=field, first=ascii(first)):
                        values = QueryDict('', mutable=True)
                        values.update({f'p-{key}': value for key, value in data.items()})
                        values.setlist(f'p-{field}', [first, last])
                        form = cls(values, prefix='p')
                        self.assertFalse(form.is_valid())
                        self.assertIn(field, form.errors)
                        self.assertNotIn(field, form.cleaned_data)

    def test_formset_optional_row_with_duplicate_and_last_blank_is_not_ignored(self):
        data = QueryDict('', mutable=True)
        data.update({'parts-TOTAL_FORMS': str(MAX_COMPONENTS), 'parts-INITIAL_FORMS': '0',
                     **{f'parts-0-{key}': value for key, value in COMPONENT.items()}})
        data.setlist('parts-1-numerator', ['2', ''])
        formset = ComponentFormSet(data, prefix='parts')
        self.assertTrue(formset.forms[1].has_changed())
        self.assertFalse(formset.is_valid())
        self.assertIn('numerator', formset.forms[1].errors)

    def test_upload_action_and_source_must_not_be_duplicated(self):
        for cls in (ProductUploadForm, PriceUploadForm):
            for field, values in (('source_name', ['\tother', 'Synthetic']), ('action', ['preview', 'stage'])):
                with self.subTest(form=cls.__name__, field=field):
                    data = QueryDict('', mutable=True)
                    data.update({'p-source_name': 'Synthetic', 'p-source_url': 'https://example.org',
                                 'p-action': 'stage', 'p-rights_attested': 'on'})
                    data.setlist('p-' + field, values)
                    form = cls(data, {'p-csv_file': SimpleUploadedFile('synthetic.csv', b'synthetic')}, prefix='p')
                    self.assertFalse(form.is_valid())
                    self.assertIn(field, form.errors)

    def test_multiple_uploaded_files_are_not_silently_reduced_to_one(self):
        for cls in (ProductUploadForm, PriceUploadForm):
            with self.subTest(form=cls.__name__):
                data = {'p-source_name': 'Synthetic', 'p-source_url': 'https://example.org',
                        'p-action': 'stage', 'p-rights_attested': 'on'}
                files = MultiValueDict({'p-csv_file': [SimpleUploadedFile('first.csv', b'first'),
                                                        SimpleUploadedFile('second.csv', b'second')]})
                form = cls(data, files, prefix='p')
                self.assertFalse(form.is_valid())
                self.assertIn('csv_file', form.errors)


@override_settings(STAFF_PORTAL_ENABLED=True)
class DuplicateSingleValueHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.RawMultilineHttpTests.setUpTestData.__func__(cls)

    def post_encoded(self, client, url, data, field, first):
        query = QueryDict('', mutable=True)
        query.update(data)
        query.setlist(field, [first, data[field]])
        return client.post(url, query.urlencode(), content_type='application/x-www-form-urlencoded',
                           HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)

    def test_duplicate_fields_cannot_create_claim_or_clinical_draft(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        cases = ((reverse('staff_source_create'), SOURCE, 'owner', '\tادعای اول', SourceClaim),
                 (reverse('staff_clinical_create'), DRAFT, 'statement', '\x1cمتن اول', ClinicalDraft),
                 (reverse('staff_clinical_create'), DRAFT, 'audience', 'professional', ClinicalDraft))
        for url, data, field, first, model in cases:
            with self.subTest(url=url, field=field):
                before = model.objects.count()
                self.assertEqual(client.get(url).status_code, 200)
                response = self.post_encoded(client, url, data, field, first)
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context['form'].errors)
                self.assertEqual(model.objects.count(), before)
                self.assertContains(response, f'href="#id_{field}"')
                if field != 'audience':
                    self.assertNotContains(response, first[1:])
                self.assertIn('no-store', response['Cache-Control'])

    def test_duplicate_decision_cannot_create_source_review(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.reviewer)
        detail = reverse('staff_source_detail', args=[self.claim.pk])
        self.assertEqual(client.get(detail).status_code, 200)
        data = {**DuplicateSingleValueFormsTests.review, 'expected_hash': self.claim.payload_sha256}
        response = self.post_encoded(client, reverse('staff_source_review', args=[self.claim.pk]), data, 'decision', 'reject')
        self.assertEqual(response.status_code, 400)
        self.assertIn('decision', response.context['review_form'].errors)
        self.assertFalse(SourceClaimReview.objects.exists())
        self.assertIn('no-store', response['Cache-Control'])

    def test_duplicate_in_empty_optional_component_does_not_create_formulation(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        url = reverse('staff_identity_create', args=['formulation'])
        self.assertEqual(client.get(url).status_code, 200)
        part = {'ingredient_id': self.ingredient.pk, 'numerator': '2.5', 'numerator_unit': 'mg',
                'denominator': '1', 'denominator_unit': 'tablet'}
        values = {**FORMULATION, 'parts-TOTAL_FORMS': '5', 'parts-INITIAL_FORMS': '0',
                  **{f'parts-0-{key}': str(value) for key, value in part.items()},
                  'parts-1-numerator': ''}
        before = (FormulationDraft.objects.count(), FormulationComponent.objects.count())
        response = self.post_encoded(client, url, values, 'parts-1-numerator', '2')
        self.assertEqual(response.status_code, 200)
        self.assertIn('numerator', response.context['parts'].forms[1].errors)
        self.assertEqual((FormulationDraft.objects.count(), FormulationComponent.objects.count()), before)
        self.assertIn('no-store', response['Cache-Control'])

    def test_multiple_uploaded_files_prevent_candidate_and_receipt_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        product = dict(source_record_id='multi-product', name_fa='فرآورده ساختگی', name_en='',
                       manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        price = dict(source_record_id='multi-price', irc='001', manufacturer='سازنده فرضی', strength='1 mg',
                     dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
                     unit='package', effective_date='', source_published_date='')
        for route, model, content in (('staff_product_upload', ProductCandidate, make_csv([product])),
                                      ('staff_price_upload', PriceCandidate, csv_bytes([price]))):
            with self.subTest(route=route):
                url = reverse(route)
                self.assertEqual(client.get(url).status_code, 200)
                before = tuple(m.objects.count() for m in (model, ImportReceipt, ImportReceiptItem))
                response = client.post(url, {'source_name': 'منبع ساختگی', 'source_url': 'https://example.org/multi',
                    'action': 'stage', 'rights_attested': 'on', 'csv_file': [
                        SimpleUploadedFile('first.csv', content, content_type='text/csv'),
                        SimpleUploadedFile('second.csv', content, content_type='text/csv')]},
                    HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(response.status_code, 200)
                self.assertIn('csv_file', response.context['form'].errors)
                self.assertEqual(tuple(m.objects.count() for m in (model, ImportReceipt, ImportReceiptItem)), before)
                self.assertIn('no-store', response['Cache-Control'])

    def test_duplicate_upload_action_prevents_candidate_and_receipt_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        product = dict(source_record_id='duplicate-product', name_fa='فرآورده ساختگی', name_en='',
                       manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        price = dict(source_record_id='duplicate-price', irc='001', manufacturer='سازنده فرضی', strength='1 mg',
                     dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
                     unit='package', effective_date='', source_published_date='')
        for route, model, content in (('staff_product_upload', ProductCandidate, make_csv([product])),
                                      ('staff_price_upload', PriceCandidate, csv_bytes([price]))):
            with self.subTest(route=route):
                url = reverse(route)
                self.assertEqual(client.get(url).status_code, 200)
                before = tuple(model_cls.objects.count() for model_cls in (model, ImportReceipt, ImportReceiptItem))
                response = client.post(url, {'source_name': 'منبع ساختگی', 'source_url': 'https://example.org/duplicate',
                    'action': ['preview', 'stage'], 'rights_attested': 'on',
                    'csv_file': SimpleUploadedFile('synthetic.csv', content, content_type='text/csv')},
                    HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(response.status_code, 200)
                self.assertIn('action', response.context['form'].errors)
                self.assertEqual(tuple(model_cls.objects.count() for model_cls in (model, ImportReceipt, ImportReceiptItem)), before)
                self.assertIn('no-store', response['Cache-Control'])
