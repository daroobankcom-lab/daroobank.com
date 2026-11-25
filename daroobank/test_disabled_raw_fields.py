"""Disabled single-value fields honor server initial values, not raw submissions."""
from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import QueryDict
from django.test import SimpleTestCase
from django.utils.datastructures import MultiValueDict

from .forms import RawControlsMixin, RawMultilineControlsMixin, SourceUploadRawControlsMixin


class DisabledForm(RawControlsMixin, RawMultilineControlsMixin, forms.Form):
    text = forms.CharField(disabled=True, initial='trusted')
    notes = forms.CharField(disabled=True, initial='trusted notes')
    raw_control_fields = ('text',)
    raw_multiline_control_fields = ('notes',)


class DisabledUpload(SourceUploadRawControlsMixin, forms.Form):
    source_name = forms.CharField(disabled=True, initial='trusted')
    source_url = forms.URLField(disabled=True, initial='https://example.org/')
    action = forms.CharField(disabled=True, initial='preview')
    csv_file = forms.FileField(disabled=True)


class DisabledRawFieldsTests(SimpleTestCase):
    def test_disabled_fields_ignore_controls_and_duplicates(self):
        for text, notes in ((['\tignored', 'ignored'], ['\x1cignored', 'ignored']),
                            (['\tignored'], ['\x1cignored'])):
            with self.subTest(text=text, notes=notes):
                data = QueryDict('', mutable=True)
                data.setlist('p-text', text)
                data.setlist('p-notes', notes)
                form = DisabledForm(data, prefix='p')
                self.assertFalse(form.has_changed())
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data, {'text': 'trusted', 'notes': 'trusted notes'})

    def test_enabling_one_field_still_rejects_its_duplicate(self):
        data = QueryDict('', mutable=True)
        data.setlist('p-text', ['first', 'second'])
        data.setlist('p-notes', ['\x1cignored', 'ignored'])
        form = DisabledForm(data, prefix='p')
        form.fields['text'].disabled = False
        self.assertTrue(form.has_changed())
        self.assertFalse(form.is_valid())
        self.assertIn('text', form.errors)
        self.assertNotIn('notes', form.errors)
        self.assertEqual(form.cleaned_data['notes'], 'trusted notes')

    def test_disabled_upload_ignores_multiple_submitted_files(self):
        initial = SimpleUploadedFile('trusted.csv', b'trusted')
        files = MultiValueDict({'csv_file': [SimpleUploadedFile('untrusted.csv', b'untrusted'),
                                               SimpleUploadedFile('untrusted2.csv', b'untrusted2')]})
        form = DisabledUpload({}, files, initial={'csv_file': initial})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertIs(form.cleaned_data['csv_file'], initial)
