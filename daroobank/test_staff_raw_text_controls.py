"""Raw single-line staff text is checked before Django strips boundary controls."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catalog.identity_forms import (
    ComponentForm, ComponentFormSet, FormulationForm, FormulationRevisionForm,
    IngredientForm, IngredientRevisionForm, PackageForm, PackageRevisionForm,
    ProductForm, ProductRevisionForm,
)
from catalog.identity import MAX_COMPONENTS
from catalog.models import IngredientDraft
from clinical.evidence import evidence_state
from clinical.forms import DraftForm, ReferenceForm, RevisionForm
from clinical.models import ClinicalDraft, ClinicalReferenceAssertion
from sources.forms import SourceClaimForm
from sources.models import SourceClaim


SOURCE = dict(source_name='منبع ساختگی', source_url='https://example.org/source', owner='مالک ساختگی',
              evidence_url='https://example.org/evidence', evidence_note='مدرک ساختگی',
              claims_collection='on', attestation='on')
DRAFT = dict(subject='موضوع ساختگی', audience='patient', title='عنوان ساختگی',
             statement='متن ساختگی\nخط دوم', reference_title='مرجع ساختگی',
             reference_url='https://example.org/reference', reference_location='محل ساختگی',
             reference_author='نویسنده', reference_version='نسخه', synthetic_ack='on')
INGREDIENT = dict(source_name='منبع ساختگی', source_url='https://example.org/source',
                  name_fa='ماده ساختگی', name_en='Synthetic', synthetic_ack='on')
COMPONENT = dict(ingredient_id='1', numerator='1', numerator_unit='mg', denominator='1', denominator_unit='tablet')
FORMULATION = dict(source_name='منبع ساختگی', source_url='https://example.org/source',
                   name='فرمول ساختگی', dosage_form='قرص', route='خوراکی', synthetic_ack='on')
PRODUCT = dict(source_name='منبع ساختگی', source_url='https://example.org/source',
               formulation_id='1', name='فرآورده ساختگی', brand='برند', manufacturer='سازنده', synthetic_ack='on')
PACKAGE = dict(source_name='منبع ساختگی', source_url='https://example.org/source', product_id='1',
               description='بسته ساختگی', quantity='1', quantity_unit='قرص', irc='123', synthetic_ack='on')
REVISION = dict(change_reason='توضیح ساختگی برای اصلاح', expected_graph_hash='a' * 64)
REFERENCE = {key: value for key, value in DRAFT.items() if key.startswith('reference_') or key == 'synthetic_ack'}
REFERENCE.update(relation='supports', expected_draft_hash='a' * 64, expected_evidence_hash='b' * 64)


class StaffRawTextFormTests(SimpleTestCase):
    cases = (
        (SourceClaimForm, SOURCE, ('source_name', 'source_url', 'owner', 'evidence_url', 'evidence_note')),
        (DraftForm, DRAFT, ('subject', 'title', 'reference_title', 'reference_url', 'reference_location', 'reference_author', 'reference_version')),
        (RevisionForm, {**DRAFT, 'change_reason': 'توضیح ساختگی برای اصلاح', 'expected_parent_hash': 'a' * 64},
         ('subject', 'title', 'reference_title', 'reference_url', 'reference_location', 'reference_author', 'reference_version')),
        (ReferenceForm, REFERENCE, ('reference_title', 'reference_url', 'reference_location', 'reference_author', 'reference_version')),
        (IngredientForm, INGREDIENT, ('source_name', 'source_url', 'name_fa', 'name_en')),
        (IngredientRevisionForm, {**INGREDIENT, 'change_reason': 'توضیح ساختگی برای اصلاح', 'expected_graph_hash': 'a' * 64},
         ('source_name', 'source_url', 'name_fa', 'name_en')),
        (ComponentForm, COMPONENT, ('numerator_unit', 'denominator_unit')),
        (FormulationForm, FORMULATION, ('source_name', 'source_url', 'name', 'dosage_form', 'route')),
        (FormulationRevisionForm, {**FORMULATION, **REVISION}, ('source_name', 'source_url', 'name', 'dosage_form', 'route')),
        (ProductForm, PRODUCT, ('source_name', 'source_url', 'name', 'brand', 'manufacturer')),
        (ProductRevisionForm, {**{k: v for k, v in PRODUCT.items() if k != 'formulation_id'}, **REVISION},
         ('source_name', 'source_url', 'name', 'brand', 'manufacturer')),
        (PackageForm, PACKAGE, ('source_name', 'source_url', 'description', 'quantity_unit', 'irc')),
        (PackageRevisionForm, {**{k: v for k, v in PACKAGE.items() if k != 'product_id'}, **REVISION, 'expected_review': '0'},
         ('source_name', 'source_url', 'description', 'quantity_unit', 'irc')),
    )

    def form(self, cls, data):
        return cls(data={f'pref-{key}': value for key, value in data.items()}, prefix='pref')

    def test_boundary_controls_rejected_on_each_selected_field_with_prefix(self):
        for cls, data, fields in self.cases:
            self.assertTrue(self.form(cls, data).is_valid(), cls.__name__)
            for field in fields:
                for control in ('\t', '\n', '\r', '\x85', '\x00', '\ud800'):
                    for left in (True, False):
                        value = control + data[field] if left else data[field] + control
                        with self.subTest(form=cls.__name__, field=field, control=ascii(control), left=left):
                            form = self.form(cls, {**data, field: value})
                            self.assertFalse(form.is_valid())
                            self.assertIn(field, form.errors)

    def test_populated_component_formset_rejects_raw_unit_controls(self):
        data = {'rows-TOTAL_FORMS': str(MAX_COMPONENTS), 'rows-INITIAL_FORMS': '0',
                'rows-MIN_NUM_FORMS': '1', 'rows-MAX_NUM_FORMS': str(MAX_COMPONENTS)}
        data.update({f'rows-0-{name}': value for name, value in COMPONENT.items()})
        self.assertTrue(ComponentFormSet(data, prefix='rows').is_valid())
        data['rows-0-numerator_unit'] = '\tmg'
        formset = ComponentFormSet(data, prefix='rows')
        self.assertFalse(formset.is_valid())
        self.assertIn('numerator_unit', formset.forms[0].errors)

    def test_control_only_on_unchanged_optional_component_is_ignored_not_saved(self):
        data = {'rows-TOTAL_FORMS': str(MAX_COMPONENTS), 'rows-INITIAL_FORMS': '0',
                'rows-MIN_NUM_FORMS': '1', 'rows-MAX_NUM_FORMS': str(MAX_COMPONENTS),
                'rows-1-numerator_unit': '\t'}
        data.update({f'rows-0-{name}': value for name, value in COMPONENT.items()})
        formset = ComponentFormSet(data, prefix='rows')
        self.assertTrue(formset.is_valid(), formset.errors)
        self.assertEqual(formset.forms[1].cleaned_data, {})

    def test_normal_spaces_zwnj_and_multiline_statement_remain_supported(self):
        for cls, data, fields in self.cases:
            form = self.form(cls, {**data, fields[0]: '  ' + data[fields[0]] + '  '})
            self.assertTrue(form.is_valid(), (cls.__name__, form.errors))
            self.assertEqual(form.cleaned_data[fields[0]], data[fields[0]])
        form = self.form(DraftForm, {**DRAFT, 'title': 'عنوان\u200cساختگی', 'statement': 'خط اول\nخط دوم\tادامه'})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['statement'], 'خط اول\nخط دوم\tادامه')
        self.assertEqual(form.cleaned_data['title'], 'عنوان\u200cساختگی')


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffRawTextHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user('synthetic-raw-author', is_staff=True)
        for app, model in (('sources', 'sourceclaim'), ('clinical', 'clinicaldraft'), ('catalog', 'identityworkspace')):
            cls.actor.user_permissions.add(*Permission.objects.filter(content_type__app_label=app,
                codename__in=[f'view_{model}', f'add_{model}']))

    def test_selected_creates_reject_hidden_boundary_controls_without_writes(self):
        self.client.force_login(self.actor)
        cases = ((reverse('staff_source_create'), SOURCE, 'source_url', SourceClaim),
                 (reverse('staff_clinical_create'), DRAFT, 'reference_url', ClinicalDraft),
                 (reverse('staff_identity_create', args=['ingredient']), INGREDIENT, 'name_fa', IngredientDraft))
        for url, data, field, model in cases:
            with self.subTest(url=url):
                response = self.client.post(url, {**data, field: '\t' + data[field]})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                self.assertIn(field, response.context['form'].errors)
                self.assertContains(response, 'id="staff-form-errors"')
                self.assertContains(response, f'href="#id_{field}"')
                self.assertContains(response, 'خطا در فرم |')
                self.assertEqual(model.objects.count(), 0)
                normal = self.client.post(url, data)
                self.assertEqual(normal.status_code, 302)
                self.assertEqual(model.objects.count(), 1)

    def test_component_field_and_management_errors_have_summary_without_value_echo(self):
        self.client.force_login(self.actor)
        url = reverse('staff_identity_create', args=['formulation'])
        get = self.client.get(url)
        self.assertNotContains(get, 'id="staff-form-errors"')
        payload = {**FORMULATION, 'parts-TOTAL_FORMS': str(MAX_COMPONENTS), 'parts-INITIAL_FORMS': '0',
                   'parts-MIN_NUM_FORMS': '1', 'parts-MAX_NUM_FORMS': str(MAX_COMPONENTS)}
        payload.update({f'parts-0-{name}': value for name, value in COMPONENT.items()})
        payload['parts-0-numerator_unit'] = '\tcanary-unit'
        response = self.client.post(url, payload)
        self.assertContains(response, 'id="staff-form-errors"')
        self.assertContains(response, 'href="#id_parts-0-numerator_unit"')
        summary = response.content.decode().split('id="staff-form-errors"', 1)[1].split('</section>', 1)[0]
        self.assertNotIn('canary-unit', summary)
        response = self.client.post(url, FORMULATION)
        self.assertContains(response, 'id="staff-form-errors"')
        self.assertContains(response, 'ساختار فرم را بررسی کنید')

    def test_non_field_error_appears_in_summary_without_fabricated_link(self):
        self.client.force_login(self.actor)
        response = self.client.post(reverse('staff_source_create'), {**SOURCE, 'source_url': 'http://example.org/source'})
        self.assertContains(response, 'id="staff-form-errors"')
        self.assertContains(response, 'پیام عمومی زیر را نیز بررسی کنید')
        summary = response.content.decode().split('id="staff-form-errors"', 1)[1].split('</section>', 1)[0]
        self.assertNotIn('<a ', summary)
        self.assertEqual(SourceClaim.objects.count(), 0)

    def test_revision_and_reference_reject_controls_without_creating_records(self):
        self.client.force_login(self.actor)
        self.assertEqual(self.client.post(reverse('staff_clinical_create'), DRAFT).status_code, 302)
        draft = ClinicalDraft.objects.get()
        revision = {**DRAFT, 'expected_parent_hash': draft.payload_sha256,
                    'change_reason': 'توضیح ساختگی برای اصلاح'}
        url = reverse('staff_clinical_revise', args=[draft.pk])
        response = self.client.post(url, {**revision, 'title': revision['title'] + '\n'})
        self.assertEqual(response.status_code, 200)
        self.assertIn('title', response.context['form'].errors)
        self.assertEqual(ClinicalDraft.objects.count(), 1)
        self.assertEqual(self.client.post(url, revision).status_code, 302)
        self.assertEqual(ClinicalDraft.objects.count(), 2)

        reference = {**REFERENCE, 'expected_draft_hash': draft.payload_sha256,
                     'expected_evidence_hash': evidence_state(draft)['fingerprint']}
        url = reverse('staff_clinical_reference_create', args=[draft.pk])
        hidden_error = self.client.post(url, {**reference, 'expected_draft_hash': 'invalid-token-canary'})
        self.assertContains(hidden_error, 'اطلاعات پنهان فرم معتبر نیست')
        summary = hidden_error.content.decode().split('id="staff-form-errors"', 1)[1].split('</section>', 1)[0]
        self.assertNotIn('invalid-token-canary', summary)
        self.assertNotIn('href="#id_expected_draft_hash"', summary)
        self.assertEqual(ClinicalReferenceAssertion.objects.count(), 0)
        response = self.client.post(url, {**reference, 'reference_location': '\t' + reference['reference_location']})
        self.assertEqual(response.status_code, 200)
        self.assertIn('reference_location', response.context['form'].errors)
        self.assertEqual(ClinicalReferenceAssertion.objects.count(), 0)
        self.assertEqual(self.client.post(url, reference).status_code, 302)
        self.assertEqual(ClinicalReferenceAssertion.objects.count(), 1)
