"""Synthetic normalized IRC length boundaries for model saves."""
from django.core.exceptions import ValidationError
from django.test import TestCase

from .models import ProductPresentation


class PresentationProjectionLengthTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.fields = dict(name_fa='محصول ساختگی', manufacturer='سازنده', strength='5 mg',
                          dosage_form='قرص', package_description='10 عدد', source_name='منبع',
                          source_url='https://example.org/synthetic')

    def test_normalized_irc_at_column_limit_is_saved_without_truncation(self):
        product = ProductPresentation.objects.create(**self.fields, irc='ﬃ' * 26 + 'ab')
        self.assertEqual(product.irc_normalized, 'ffi' * 26 + 'ab')
        self.assertEqual(len(product.irc_normalized), 80)

    def test_normalized_irc_above_column_limit_raises_validation_error_on_create(self):
        with self.assertRaises(ValidationError) as error:
            ProductPresentation.objects.create(**self.fields, irc='ﬃ' * 27)
        self.assertIn('irc_normalized', error.exception.message_dict)
        self.assertEqual(ProductPresentation.objects.count(), 0)

    def test_normalized_irc_above_column_limit_rolls_back_partial_save(self):
        product = ProductPresentation.objects.create(**self.fields, irc='001')
        product.irc = 'ﬃ' * 27
        product.name_fa = 'تغییر نباید ثبت شود'
        with self.assertRaises(ValidationError) as error:
            product.save(update_fields=['irc', 'name_fa'])
        self.assertIn('irc_normalized', error.exception.message_dict)
        product.refresh_from_db()
        self.assertEqual((product.irc, product.irc_normalized, product.name_fa), ('001', '001', self.fields['name_fa']))

    def test_normalized_irc_above_column_limit_rejects_full_save(self):
        product = ProductPresentation.objects.create(**self.fields, irc='001')
        product.irc = 'ﬃ' * 27
        with self.assertRaises(ValidationError) as error:
            product.save()
        self.assertIn('irc_normalized', error.exception.message_dict)
        product.refresh_from_db()
        self.assertEqual((product.irc, product.irc_normalized), ('001', '001'))

    def test_oversized_stored_irc_projection_can_be_fixed_in_partial_save(self):
        product = ProductPresentation.objects.create(**self.fields, irc='001')
        ProductPresentation.objects.filter(pk=product.pk).update(irc='ﬃ' * 27)
        product.name_fa = 'تغییر نباید ثبت شود'
        with self.assertRaises(ValidationError):
            product.save(update_fields=['name_fa'])
        product.irc = '002'
        product.save(update_fields=['irc'])
        product.refresh_from_db()
        self.assertEqual((product.irc, product.irc_normalized, product.name_fa), ('002', '002', self.fields['name_fa']))
