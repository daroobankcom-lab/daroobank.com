"""Selected acknowledgements and source-rights choices must be explicit."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catalog.identity_forms import IngredientForm
from catalog.models import IngredientDraft, ProductCandidate
from catalog.staff_forms import ProductUploadForm
from catalog.test_intake import make_csv
from clinical.forms import DraftForm, ReferenceForm
from clinical.models import ClinicalDraft
from pricing.forms import PriceUploadForm
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes
from ingestion.models import ImportReceipt, ImportReceiptItem
from sources.forms import SourceClaimForm
from sources.models import SourceClaim

from . import test_staff_raw_multiline_controls as fixtures
from .test_staff_raw_text_controls import DRAFT, INGREDIENT, REFERENCE, SOURCE


class ExplicitCheckboxFormsTests(SimpleTestCase):
    cases = ((IngredientForm, INGREDIENT, ('synthetic_ack',)),
             (DraftForm, DRAFT, ('synthetic_ack',)),
             (ReferenceForm, REFERENCE, ('synthetic_ack',)),
             (SourceClaimForm, SOURCE, ('attestation', 'claims_collection', 'claims_storage', 'claims_publication')))

    def test_unrecognized_values_and_duplicate_values_rejected_with_prefix(self):
        for cls, data, fields in self.cases:
            for field in fields:
                for value in ('false ', '0 ', 'off\t', 'garbage', 'yes', '\ud800'):
                    with self.subTest(form=cls.__name__, field=field, value=ascii(value)):
                        form = cls({f'p-{k}': v for k, v in {**data, field: value}.items()}, prefix='p')
                        self.assertFalse(form.is_valid(), form.errors)
                        self.assertIn(field, form.errors)
                        self.assertNotIn(field, form.cleaned_data)
                        self.assertIn(field, form.changed_data)
                        self.assertIn('id_p-' + field, str(form[field]))
                values = QueryDict('', mutable=True)
                values.update({f'p-{k}': v for k, v in data.items()})
                values.setlist(f'p-{field}', ['false', 'on'])
                form = cls(values, prefix='p')
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)

    def test_explicit_boolean_values_and_omission(self):
        for cls, data, fields in self.cases:
            for field in fields:
                if field.startswith('claims_'):
                    # Another scope stays selected when this one is unchecked.
                    data = {**data, ('claims_storage' if field != 'claims_storage' else 'claims_collection'): 'on'}
                for value in ('on', 'true', 'True', '1', True):
                    form = cls({**data, field: value})
                    self.assertTrue(form.is_valid(), (cls.__name__, field, value, form.errors))
                    self.assertIs(form.cleaned_data[field], True)
                if field.startswith('claims_'):
                    for value in ('', 'false', 'False', '0', 'off', False):
                        form = cls({**data, field: value})
                        self.assertTrue(form.is_valid(), (cls.__name__, field, value, form.errors))
                        self.assertIs(form.cleaned_data[field], False)
                    form = cls({k: v for k, v in data.items() if k != field})
                    self.assertTrue(form.is_valid(), form.errors)
                    self.assertIs(form.cleaned_data[field], False)
                else:
                    for value in ('', 'false', '0', 'off', False):
                        form = cls({**data, field: value})
                        self.assertFalse(form.is_valid())
                        self.assertIn(field, form.errors)

    def test_upload_rights_bad_or_false_cannot_stage(self):
        for cls in (ProductUploadForm, PriceUploadForm):
            for value in ('false ', '0', '0 ', 'off', 'anything'):
                files = {'csv_file': SimpleUploadedFile('synthetic.csv', b'synthetic')}
                form = cls({'source_name': 'Synthetic', 'source_url': 'https://example.org',
                            'action': 'stage', 'rights_attested': value}, files)
                self.assertFalse(form.is_valid(), (cls.__name__, value, form.errors))
                self.assertIn('rights_attested', form.errors)


@override_settings(STAFF_PORTAL_ENABLED=True)
class ExplicitCheckboxHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.RawMultilineHttpTests.setUpTestData.__func__(cls)

    def test_tampered_acknowledgement_cannot_write_with_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        cases = ((reverse('staff_source_create'), SOURCE, 'attestation', SourceClaim),
                 (reverse('staff_clinical_create'), DRAFT, 'synthetic_ack', ClinicalDraft),
                 (reverse('staff_identity_create', args=['ingredient']), INGREDIENT, 'synthetic_ack', IngredientDraft))
        for url, data, field, model in cases:
            with self.subTest(url=url):
                before = model.objects.count()
                self.assertEqual(client.get(url).status_code, 200)
                response = client.post(url, {**data, field: 'false '}, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(model.objects.count(), before)
                self.assertIn(field, response.context['form'].errors)
                self.assertIn('no-store', response['Cache-Control'])
                self.assertContains(response, f'href="#id_{field}"')

    def test_tampered_uploads_do_not_create_candidates_or_receipts(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        product = dict(source_record_id='checkbox-product', name_fa='فرآورده ساختگی', name_en='',
                       manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        price = dict(source_record_id='checkbox-price', irc='001', manufacturer='سازنده فرضی', strength='1 mg',
                     dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
                     unit='package', effective_date='', source_published_date='')
        for name, content, model in (('staff_product_upload', make_csv([product]), ProductCandidate),
                                     ('staff_price_upload', csv_bytes([price]), PriceCandidate)):
            url = reverse(name)
            self.assertEqual(client.get(url).status_code, 200)
            for value in ('false ', '0', 'garbage'):
                with self.subTest(name=name, value=value):
                    before = [m.objects.count() for m in (model, ImportReceipt, ImportReceiptItem)]
                    response = client.post(url, {'source_name': 'منبع ساختگی', 'source_url': 'https://example.org/checkbox',
                        'action': 'stage', 'rights_attested': value,
                        'csv_file': SimpleUploadedFile('synthetic.csv', content, content_type='text/csv')},
                        HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('rights_attested', response.context['form'].errors)
                    self.assertEqual([m.objects.count() for m in (model, ImportReceipt, ImportReceiptItem)], before)
                    self.assertIn('no-store', response['Cache-Control'])

    def test_explicit_zero_scope_is_not_recorded_as_true(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        url = reverse('staff_source_create')
        self.assertEqual(client.get(url).status_code, 200)
        response = client.post(url, {**SOURCE, 'claims_collection': '0', 'claims_storage': 'on'},
                               HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 302)
        claim = SourceClaim.objects.latest('pk')
        self.assertIs(claim.claims_collection, False)
        self.assertIs(claim.claims_storage, True)
