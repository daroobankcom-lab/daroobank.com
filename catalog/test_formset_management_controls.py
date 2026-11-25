"""Selected synthetic formulation formset management values stay explicit."""
from django.http import QueryDict
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from catalog.identity import MAX_COMPONENTS, digest, formulation_snapshot
from catalog.identity_forms import ComponentFormSet, RevisionComponentFormSet
from catalog.models import FormulationComponent, FormulationDraft, FormulationRevision
from catalog import test_identity as fixtures
from daroobank.test_staff_raw_text_controls import COMPONENT, FORMULATION


class ManagementValueTests(SimpleTestCase):
    def formset(self, revision=False, changes=None, duplicate=None):
        initial_count = '1' if revision else '0'
        values = {'parts-TOTAL_FORMS': str(MAX_COMPONENTS), 'parts-INITIAL_FORMS': initial_count,
                  **{f'parts-0-{key}': value for key, value in COMPONENT.items()}}
        values.update(changes or {})
        if duplicate:
            query = QueryDict('', mutable=True)
            query.update(values)
            query.setlist(f'parts-{duplicate}', [values[f'parts-{duplicate}'], values[f'parts-{duplicate}']])
            values = query
        if revision:
            return RevisionComponentFormSet(values, prefix='parts', initial=[COMPONENT], expected_initial=1)
        return ComponentFormSet(values, prefix='parts')

    def test_reject_raw_controls_in_management_numbers(self):
        for revision in (False, True):
            for field, value in (('TOTAL_FORMS', '5'), ('INITIAL_FORMS', '1' if revision else '0')):
                for control in ('\t', '\n', '\r', '\x1c', '\x85', '\x00', '\ud800'):
                    for raw in (control + value, value + control):
                        with self.subTest(revision=revision, field=field, control=ascii(control)):
                            formset = self.formset(revision, {f'parts-{field}': raw})
                            self.assertFalse(formset.is_valid())
                            self.assertTrue(formset.non_form_errors())
                            self.assertLessEqual(len(formset.forms), MAX_COMPONENTS)

    def test_duplicate_management_values_are_rejected(self):
        for revision in (False, True):
            for field in ('TOTAL_FORMS', 'INITIAL_FORMS'):
                with self.subTest(revision=revision, field=field):
                    formset = self.formset(revision, duplicate=field)
                    self.assertFalse(formset.is_valid())
                    self.assertTrue(formset.non_form_errors())

    def test_missing_and_excessive_counts_remain_invalid_and_capped(self):
        for revision in (False, True):
            with self.subTest(revision=revision):
                missing = self.formset(revision, {'parts-TOTAL_FORMS': ''})
                self.assertFalse(missing.is_valid())
                self.assertTrue(missing.non_form_errors())
                excessive = self.formset(revision, {'parts-TOTAL_FORMS': '1000000'})
                self.assertFalse(excessive.is_valid())
                self.assertLessEqual(len(excessive.forms), MAX_COMPONENTS)
                self.assertTrue(excessive.non_form_errors())

    def test_valid_spaces_localized_digits_and_absent_optional_rows_still_work(self):
        for revision in (False, True):
            for total, initial in (('5', '1' if revision else '0'),
                                   (' 5 ', ' 1 ' if revision else ' 0 '),
                                   ('۵', '۱' if revision else '۰')):
                formset = self.formset(revision, {'parts-TOTAL_FORMS': total, 'parts-INITIAL_FORMS': initial})
                self.assertTrue(formset.is_valid(), formset.errors)
                self.assertEqual(len(formset.forms), MAX_COMPONENTS)
                self.assertFalse(formset.forms[1].has_changed())


@override_settings(STAFF_PORTAL_ENABLED=True)
class ManagementHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.IdentityTests.setUpTestData.__func__(cls)

    def test_create_and_revision_reject_bad_management_without_partial_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        part = {key: str(value) for key, value in self.part.items()}
        common = {'parts-TOTAL_FORMS': '5', 'parts-INITIAL_FORMS': '0',
                  **{f'parts-0-{key}': value for key, value in part.items()}}
        cases = (
            (reverse('staff_identity_create', args=['formulation']), {**FORMULATION, **common}),
            (reverse('staff_identity_revise_component', args=['formulation', self.formulation.pk]),
             {**FORMULATION, **common, 'parts-INITIAL_FORMS': '1', 'name': 'نسخه اصلاحی ساختگی',
              'expected_graph_hash': digest(formulation_snapshot(self.formulation)),
              'change_reason': 'توضیح ساختگی برای اصلاح'}),
        )
        for url, data in cases:
            self.assertEqual(client.get(url).status_code, 200)
            for field in ('parts-TOTAL_FORMS', 'parts-INITIAL_FORMS'):
                for mode in ('control', 'duplicate'):
                    with self.subTest(url=url, field=field, mode=mode):
                        before = tuple(m.objects.count() for m in (FormulationDraft, FormulationRevision, FormulationComponent))
                        values = QueryDict('', mutable=True)
                        values.update(data)
                        values.setlist(field, ['\t' + data[field]] if mode == 'control' else [data[field], data[field]])
                        # The test client's multipart encoder collapses a QueryDict
                        # via .items(); URL encoding preserves duplicate fields.
                        encoded = values.urlencode()
                        rejected = client.post(url, encoded, content_type='application/x-www-form-urlencoded')
                        self.assertEqual(rejected.status_code, 403)
                        self.assertEqual(tuple(m.objects.count() for m in (FormulationDraft, FormulationRevision, FormulationComponent)), before)
                        response = client.post(url, encoded, content_type='application/x-www-form-urlencoded',
                                               HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                        self.assertEqual(response.status_code, 200)
                        self.assertTrue(response.context['parts'].non_form_errors())
                        self.assertContains(response, 'ساختار فرم را بررسی کنید')
                        self.assertIn('no-store', response['Cache-Control'])
                        self.assertEqual(tuple(m.objects.count() for m in (FormulationDraft, FormulationRevision, FormulationComponent)), before)
