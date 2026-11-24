"""Synthetic partial-save validation against the locked persisted presentation."""
from datetime import datetime, timezone
from itertools import product

from django.core.exceptions import ValidationError
from django.db.models.signals import pre_save
from django.test import TestCase

from .models import ProductPresentation


class PresentationPartialValidationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='محصول ساختگی', name_en='Synthetic', manufacturer='سازنده',
            strength='5 mg', dosage_form='قرص', package_description='10 عدد',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic',
            verified_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published=False)

    def copies(self):
        return (ProductPresentation.objects.get(pk=self.product.pk), ProductPresentation.objects.get(pk=self.product.pk))

    def test_publication_date_prospective_truth_table(self):
        date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for current_published, current_dated, local_published, local_dated, field in product(
                (False, True), (False, True), (False, True), (False, True), ('published', 'verified_at')):
            with self.subTest(current_published=current_published, current_dated=current_dated,
                              local_published=local_published, local_dated=local_dated, field=field):
                ProductPresentation.objects.filter(pk=self.product.pk).update(
                    published=current_published, verified_at=date if current_dated else None)
                instance = ProductPresentation.objects.get(pk=self.product.pk)
                instance.published = local_published
                instance.verified_at = date if local_dated else None
                next_published = local_published if field == 'published' else current_published
                next_dated = local_dated if field == 'verified_at' else current_dated
                if next_published and not next_dated:
                    with self.assertRaises(ValidationError):
                        instance.save(update_fields=[field])
                    expected = (current_published, date if current_dated else None)
                else:
                    instance.save(update_fields=[field])
                    expected = (next_published, date if next_dated else None)
                current = ProductPresentation.objects.get(pk=self.product.pk)
                self.assertEqual((current.published, current.verified_at), expected)

    def test_stale_publish_does_not_bypass_current_missing_verification(self):
        stale, fresh = self.copies()
        fresh.verified_at = None
        fresh.save(update_fields=['verified_at'])
        stale.published = True
        with self.assertRaises(ValidationError):
            stale.save(update_fields=['published'])
        current = ProductPresentation.objects.get(pk=self.product.pk)
        self.assertEqual((current.published, current.verified_at), (False, None))

    def test_stale_verification_removal_does_not_bypass_current_published_flag(self):
        stale, fresh = self.copies()
        fresh.published = True
        fresh.save(update_fields=['published'])
        stale.verified_at = None
        with self.assertRaises(ValidationError):
            stale.save(update_fields=['verified_at'])
        current = ProductPresentation.objects.get(pk=self.product.pk)
        self.assertTrue(current.published)
        self.assertIsNotNone(current.verified_at)

    def test_unwritten_invalid_stale_field_does_not_reject_valid_partial_write(self):
        stale, fresh = self.copies()
        stale.source_url = 'not-an-https-url'
        stale.name_fa = 'نام تازه'
        stale.save(update_fields=['name_fa'])
        current = ProductPresentation.objects.get(pk=self.product.pk)
        self.assertEqual(current.name_fa, 'نام تازه')
        self.assertEqual(current.source_url, fresh.source_url)

    def test_invalid_current_unwritten_field_rejects_unrelated_partial_write(self):
        stale = ProductPresentation.objects.get(pk=self.product.pk)
        ProductPresentation.objects.filter(pk=stale.pk).update(source_url='not-an-https-url')
        stale.name_fa = 'نام نباید ثبت شود'
        with self.assertRaises(ValidationError):
            stale.save(update_fields=['name_fa'])
        current = ProductPresentation.objects.get(pk=stale.pk)
        self.assertEqual(current.name_fa, self.product.name_fa)
        self.assertEqual(current.source_url, 'not-an-https-url')

    def test_explicitly_fixing_invalid_stored_field_can_succeed(self):
        stale = ProductPresentation.objects.get(pk=self.product.pk)
        ProductPresentation.objects.filter(pk=stale.pk).update(source_url='not-an-https-url')
        stale.source_url = 'https://example.org/corrected'
        stale.save(update_fields=['source_url'])
        self.assertEqual(ProductPresentation.objects.get(pk=stale.pk).source_url, stale.source_url)

    def test_signal_sees_original_instance_not_refreshed_omitted_fields(self):
        stale, fresh = self.copies()
        fresh.source_name = 'منبع تازه'
        fresh.save(update_fields=['source_name'])
        stale.name_fa = 'نام تازه'
        observed = []

        def capture(sender, instance, **kwargs):
            observed.append((instance is stale, instance.source_name))

        pre_save.connect(capture, sender=ProductPresentation, weak=False)
        try:
            stale.save(update_fields=['name_fa'])
        finally:
            pre_save.disconnect(capture, sender=ProductPresentation)
        self.assertEqual(observed, [(True, 'منبع ساختگی')])
        current = ProductPresentation.objects.get(pk=stale.pk)
        self.assertEqual(current.source_name, 'منبع تازه')
        self.assertEqual(stale.source_name, 'منبع ساختگی')

    def test_full_clean_coercion_is_applied_to_written_fields(self):
        product = ProductPresentation.objects.get(pk=self.product.pk)
        product.verified_at = '2026-03-01T00:00:00Z'
        product.save(update_fields=['verified_at'])
        expected = datetime(2026, 3, 1, tzinfo=timezone.utc)
        self.assertEqual(product.verified_at, expected)
        self.assertEqual(ProductPresentation.objects.get(pk=product.pk).verified_at, expected)

    def test_updating_both_dependent_fields_together_remains_valid(self):
        product = ProductPresentation.objects.get(pk=self.product.pk)
        product.verified_at = None
        product.save(update_fields=['verified_at'])
        product.published = True
        product.verified_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
        product.save(update_fields=['published', 'verified_at'])
        current = ProductPresentation.objects.get(pk=product.pk)
        self.assertTrue(current.published)
        self.assertEqual(current.verified_at, product.verified_at)
