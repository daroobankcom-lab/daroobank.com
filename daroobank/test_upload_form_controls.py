"""Raw source metadata must not lose controls during upload form cleanup."""
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from catalog.staff_forms import ProductUploadForm
from pricing.forms import PriceUploadForm


class UploadSourceControlsTests(SimpleTestCase):
    def build_form(self, cls, *, name='منبع ساختگی', url='https://example.org', prefix='sample'):
        data = {f'{prefix}-source_name': name, f'{prefix}-source_url': url,
                f'{prefix}-action': 'stage', f'{prefix}-rights_attested': 'on'}
        files = {f'{prefix}-csv_file': SimpleUploadedFile('synthetic.csv', b'synthetic')}
        return cls(data=data, files=files, prefix=prefix)

    def test_source_controls_are_rejected_before_form_trim(self):
        for cls in (ProductUploadForm, PriceUploadForm):
            for name, url, field in (('\tمنبع', 'https://example.org', 'source_name'),
                                     ('منبع\n', 'https://example.org', 'source_name'),
                                     ('منبع', 'https://example.org\r', 'source_url')):
                with self.subTest(form=cls.__name__, field=field, value=repr(name + url)):
                    form = self.build_form(cls, name=name, url=url)
                    self.assertFalse(form.is_valid())
                    self.assertIn(field, form.errors)

    def test_ordinary_spaces_and_persian_joiner_are_preserved_as_intended(self):
        for cls in (ProductUploadForm, PriceUploadForm):
            with self.subTest(form=cls.__name__):
                form = self.build_form(cls, name='  نام\u200cمنبع  ', url='  https://example.org  ')
                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data['source_name'], 'نام\u200cمنبع')
                self.assertEqual(form.cleaned_data['source_url'], 'https://example.org')
