"""Invalid or explicit-false checkbox values must not render as checked."""
from django.http import QueryDict
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from sources.forms import SourceClaimForm
from sources.models import SourceClaim
from . import test_staff_raw_multiline_controls as fixtures
from .test_staff_raw_text_controls import SOURCE


class CheckboxRenderingTests(SimpleTestCase):
    def test_checked_state_matches_validation_even_on_other_errors(self):
        for token, checked in (('on', True), ('TRUE', True), ('1', True), ('false', False),
                               ('0', False), ('off', False), ('', False), ('false ', False),
                               ('private-canary', False)):
            with self.subTest(token=token):
                form = SourceClaimForm({**SOURCE, 'claims_storage': token, 'source_url': 'not-a-url'})
                self.assertFalse(form.is_valid())
                html = str(form['claims_storage'])
                self.assertEqual(' checked' in html, checked, html)
                self.assertNotIn('private-canary', html)
                self.assertNotIn('value=', html)

    def test_duplicate_checkbox_values_are_not_displayed_as_checked(self):
        values = QueryDict('', mutable=True)
        values.update(SOURCE)
        values.setlist('claims_storage', ['false', 'on'])
        form = SourceClaimForm(values)
        self.assertFalse(form.is_valid())
        self.assertIn('claims_storage', form.errors)
        self.assertNotIn(' checked', str(form['claims_storage']))

    def test_disabled_checkbox_keeps_initial_state(self):
        for initial in (False, 'false', '0'):
            form = SourceClaimForm({**SOURCE, 'claims_storage': 'on', 'source_url': 'invalid'},
                                   initial={'claims_storage': initial})
            form.fields['claims_storage'].disabled = True
            self.assertFalse(form.is_valid())
            self.assertNotIn(' checked', str(form['claims_storage']))
            self.assertIs(form.cleaned_data['claims_storage'], False)


@override_settings(STAFF_PORTAL_ENABLED=True)
class CheckboxRenderingHttpTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.RawMultilineHttpTests.setUpTestData.__func__(cls)

    def test_invalid_submission_renders_false_and_invalid_as_unchecked_without_write(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        url = reverse('staff_source_create')
        self.assertEqual(client.get(url).status_code, 200)
        before = SourceClaim.objects.count()
        for token in ('false', '0', 'off', 'false ', 'private-canary'):
            with self.subTest(token=token):
                response = client.post(url, {**SOURCE, 'source_url': 'invalid-url', 'claims_storage': token},
                                       HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(response.status_code, 200)
                html = str(response.context['form']['claims_storage'])
                self.assertNotIn(' checked', html)
                self.assertNotIn('value=', html)
                self.assertNotContains(response, 'private-canary')
                self.assertIn('no-store', response['Cache-Control'])
                self.assertEqual(SourceClaim.objects.count(), before)
