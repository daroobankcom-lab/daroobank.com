"""Selected staff date controls must not be silently stripped before parsing."""
from datetime import date

from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from clinical.evidence import evidence_state
from clinical.forms import DraftForm, ReferenceForm, RevisionForm
from clinical.models import ClinicalDraft, ClinicalReferenceAssertion
from sources.forms import SourceClaimForm
from sources.models import SourceClaim

from . import test_staff_raw_multiline_controls as fixtures
from .test_staff_raw_text_controls import DRAFT, REFERENCE, SOURCE


class RawDateFormTests(SimpleTestCase):
    cases = (
        (SourceClaimForm, SOURCE, ('starts_on', 'expires_on')),
        (DraftForm, DRAFT, ('reference_published_on', 'reference_accessed_on')),
        (RevisionForm, {**DRAFT, 'change_reason': 'دلیل ساختگی برای اصلاح', 'expected_parent_hash': 'a' * 64},
         ('reference_published_on', 'reference_accessed_on')),
        (ReferenceForm, REFERENCE, ('reference_published_on', 'reference_accessed_on')),
    )

    def test_reject_raw_control_even_if_date_parser_would_strip_it(self):
        for cls, data, fields in self.cases:
            for field in fields:
                for control in ('\t', '\n', '\r', '\x1c', '\x85', '\x00', '\ud800'):
                    for value in (control + '2026-01-02', '2026-01-02' + control, control):
                        with self.subTest(form=cls.__name__, field=field, control=ascii(control), value=ascii(value)):
                            form = cls({f'p-{k}': v for k, v in {**data, field: value}.items()}, prefix='p')
                            self.assertFalse(form.is_valid())
                            self.assertIn(field, form.errors)
                            self.assertNotIn(field, form.cleaned_data)

    def test_valid_optional_empty_and_outer_spaces_unchanged(self):
        for cls, data, fields in self.cases:
            form = cls(data)
            self.assertTrue(form.is_valid(), form.errors)
            for field in fields:
                self.assertIsNone(form.cleaned_data[field])
                form = cls({**data, field: '  2026-01-02  '})
                self.assertTrue(form.is_valid(), (cls.__name__, field, form.errors))
                self.assertEqual(form.cleaned_data[field], date(2026, 1, 2))
                bad = cls({**data, field: '2026-02-30'})
                self.assertFalse(bad.is_valid())
                self.assertIn(field, bad.errors)


@override_settings(STAFF_PORTAL_ENABLED=True)
class RawDateHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.RawMultilineHttpTests.setUpTestData.__func__(cls)

    def test_invalid_raw_dates_reject_before_writes_with_private_error_links(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        draft_values = {**DRAFT, 'reference_published_on': '', 'reference_accessed_on': ''}
        cases = (
            (reverse('staff_source_create'), SOURCE, 'starts_on', SourceClaim),
            (reverse('staff_clinical_create'), draft_values, 'reference_published_on', ClinicalDraft),
            (reverse('staff_clinical_revise', args=[self.draft.pk]),
             {**draft_values, 'change_reason': 'دلیل ساختگی برای اصلاح', 'expected_parent_hash': self.draft.payload_sha256},
             'reference_accessed_on', ClinicalDraft),
            (reverse('staff_clinical_reference_create', args=[self.draft.pk]),
             {**REFERENCE, 'expected_draft_hash': self.draft.payload_sha256,
              'expected_evidence_hash': evidence_state(self.draft)['fingerprint']},
             'reference_published_on', ClinicalReferenceAssertion),
        )
        for url, data, field, model in cases:
            with self.subTest(url=url):
                before = model.objects.count()
                self.assertEqual(client.get(url).status_code, 200)
                tampered = {**data, field: '\t2026-01-02'}
                self.assertEqual(client.post(url, tampered).status_code, 403)
                response = client.post(url, tampered, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(model.objects.count(), before)
                self.assertIn(field, response.context['form'].errors)
                self.assertIn('no-store', response['Cache-Control'])
                self.assertContains(response, f'href="#id_{field}"')
                self.assertContains(response, 'نویسه کنترلی نامعتبر است')
