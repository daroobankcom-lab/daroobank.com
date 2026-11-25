"""Raw controls in identity numeric fields must not be silently trimmed."""
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catalog.identity import MAX_COMPONENTS, digest, formulation_snapshot, package_snapshot
from catalog.identity_forms import ComponentForm, ComponentFormSet, PackageForm, PackageRevisionForm, ProductForm
from catalog.models import FormulationDraft, FormulationRevision, IdentityPackageDraft, IdentityPackageRevision, IdentityProductDraft
from catalog.test_identity import IdentityTests
from .test_staff_raw_text_controls import COMPONENT, FORMULATION, PACKAGE, PRODUCT, REVISION


class RawNumericIdentityFormTests(SimpleTestCase):
    cases = (
        (ComponentForm, COMPONENT, ('ingredient_id', 'numerator', 'denominator')),
        (ProductForm, PRODUCT, ('formulation_id',)),
        (PackageForm, PACKAGE, ('product_id', 'quantity')),
        (PackageRevisionForm, {**{k: v for k, v in PACKAGE.items() if k != 'product_id'},
                               **REVISION, 'expected_review': '0'}, ('quantity',)),
    )

    def test_controls_cannot_disappear_during_numeric_conversion(self):
        for cls, data, fields in self.cases:
            for field in fields:
                for control in ('\t', '\n', '\r', '\x1c', '\x85', '\x00', '\ud800'):
                    for value in (control + data[field], data[field] + control):
                        with self.subTest(form=cls.__name__, field=field, control=ascii(control)):
                            form = cls({f'p-{k}': v for k, v in {**data, field: value}.items()}, prefix='p')
                            self.assertFalse(form.is_valid())
                            self.assertIn(field, form.errors)
                            self.assertNotIn(field, form.cleaned_data)

    def test_ordinary_outer_spaces_and_localized_digits_remain_accepted(self):
        for cls, data, fields in self.cases:
            for field in fields:
                with self.subTest(form=cls.__name__, field=field):
                    form = cls({**data, field: '  ' + data[field] + '  '})
                    self.assertTrue(form.is_valid(), form.errors)
        for field in ('ingredient_id', 'numerator', 'denominator'):
            form = ComponentForm({**COMPONENT, field: '۱'})
            self.assertTrue(form.is_valid(), form.errors)

    def test_active_formset_row_checked_and_empty_optional_row_remains_ignored(self):
        data = {'parts-TOTAL_FORMS': str(MAX_COMPONENTS), 'parts-INITIAL_FORMS': '0',
                **{f'parts-0-{k}': v for k, v in COMPONENT.items()}}
        self.assertTrue(ComponentFormSet(data, prefix='parts').is_valid())
        for field in ('ingredient_id', 'numerator', 'denominator'):
            formset = ComponentFormSet({**data, f'parts-0-{field}': '\t' + COMPONENT[field]}, prefix='parts')
            self.assertFalse(formset.is_valid())
            self.assertIn(field, formset.forms[0].errors)
        # An entirely absent optional row stays empty; numeric control-only
        # input is treated as a changed invalid row, never silently persisted.
        self.assertEqual(ComponentFormSet(data, prefix='parts').forms[1].has_changed(), False)
        formset = ComponentFormSet({**data, 'parts-1-numerator': '\t'}, prefix='parts')
        self.assertFalse(formset.is_valid())
        self.assertIn('numerator', formset.forms[1].errors)


@override_settings(STAFF_PORTAL_ENABLED=True)
class RawNumericIdentityHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        IdentityTests.setUpTestData.__func__(cls)

    def test_create_and_revision_reject_boundary_controls_without_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        component = {k: str(v) for k, v in self.part.items()}
        management = {'parts-TOTAL_FORMS': '5', 'parts-INITIAL_FORMS': '0',
                      **{f'parts-0-{k}': v for k, v in component.items()}}
        common = {'synthetic_ack': 'on', 'change_reason': 'توضیح ساختگی برای اصلاح'}
        cases = (
            (reverse('staff_identity_create', args=['formulation']),
             {**FORMULATION, **management}, 'parts-0-numerator', FormulationDraft, False),
            (reverse('staff_identity_create', args=['product']),
             {**PRODUCT, 'formulation_id': str(self.formulation.pk)}, 'formulation_id', IdentityProductDraft, False),
            (reverse('staff_identity_create', args=['package']),
             {**PACKAGE, 'product_id': str(self.product.pk)}, 'quantity', IdentityPackageDraft, False),
            (reverse('staff_identity_revise_component', args=['formulation', self.formulation.pk]),
             {**FORMULATION, **common, **management, 'parts-INITIAL_FORMS': '1',
              'expected_graph_hash': digest(formulation_snapshot(self.formulation))},
             'parts-0-denominator', FormulationRevision, True),
            (reverse('staff_identity_revise', args=[self.package.pk]),
             {**PACKAGE, **common, 'expected_graph_hash': digest(package_snapshot(self.package)), 'expected_review': '0'},
             'quantity', IdentityPackageRevision, True),
        )
        for url, data, field, model, revision in cases:
            with self.subTest(url=url):
                before = model.objects.count()
                get = client.get(url)
                self.assertEqual(get.status_code, 200)
                tampered = {**data, field: '\t' + data[field]}
                self.assertEqual(client.post(url, tampered).status_code, 403)
                response = client.post(url, tampered, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(model.objects.count(), before)
                self.assertIn('no-store', response['Cache-Control'])
                self.assertContains(response, f'href="#id_{field}"')
                self.assertContains(response, 'نویسه کنترلی نامعتبر است')
                self.assertIn('parts' if field.startswith('parts-') else 'form', response.context)
                if revision:
                    self.assertFalse(response.context['conflict'])
