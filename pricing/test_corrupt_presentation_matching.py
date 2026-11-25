"""Synthetic matching with invalid candidate presentation text."""
import io
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import ProductPresentation
from ingestion.receipts import stage_price_with_receipt
from .importer import _load_irc_index, stage_csv, suggest_product
from .models import PriceCandidate, PriceCandidateReview
from .reviews import ReviewConflict, product_fingerprint, record_preliminary_review
from .test_workflow import csv_bytes


@override_settings(STAFF_PORTAL_ENABLED=True)
class CorruptPresentationMatchingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.stager = User.objects.create_user('corrupt-price-stager', is_staff=True)
        cls.reviewer = User.objects.create_user('corrupt-price-reviewer', is_staff=True)
        cls.stager.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
            codename__in=['view_pricecandidate', 'add_pricecandidate']))
        cls.reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
            codename__in=['view_pricecandidate', 'review_pricecandidate']))
        cls.product_data = dict(name_fa='فرآورده ساختگی', manufacturer='سازنده فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', irc='001',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic')
        cls.product = ProductPresentation.objects.create(**cls.product_data)
        cls.row = dict(source_record_id='test', irc='001', manufacturer='سازنده فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
            unit='package', effective_date='', source_published_date='')

    def stage(self):
        return stage_csv(io.BytesIO(csv_bytes([self.row])), 'منبع ساختگی', 'https://example.org/feed',
                         commit=True, rights_attested=True, staged_by=self.stager)

    def test_control_in_matching_identity_or_display_name_blocks_suggestion(self):
        for changes in (dict(manufacturer='سازنده\nفرضی'), dict(strength='5\tmg'),
                        dict(dosage_form='قرص\t'), dict(package_description='10\nعدد'),
                        dict(irc='\t001'), dict(name_fa='bad-name\x1bcanary'), dict(name_fa='\u200c')):
            with self.subTest(changes=changes):
                ProductPresentation.objects.filter(pk=self.product.pk).update(**changes)
                self.assertEqual(suggest_product(self.row), ('ambiguous', None))
                counts = self.stage()
                self.assertEqual(counts['ambiguous'], 1)
                self.assertEqual(PriceCandidate.objects.get().match_status, 'ambiguous')
                self.client.force_login(self.reviewer)
                response = self.client.get(reverse('staff_price_detail', args=[PriceCandidate.objects.get().pk]))
                self.assertNotContains(response, 'bad-name')
                self.assertNotContains(response, 'canary')
                PriceCandidate.objects.all().delete()
                ProductPresentation.objects.filter(pk=self.product.pk).update(**self.product_data)

    def test_invalid_duplicate_cannot_be_ignored_to_claim_unique_match(self):
        duplicate = ProductPresentation.objects.create(**self.product_data)
        ProductPresentation.objects.filter(pk=duplicate.pk).update(name_fa='bad-name\x1bcanary')
        self.assertEqual(suggest_product(self.row), ('ambiguous', None))
        # A different identity on the same IRC does not poison this matching key.
        ProductPresentation.objects.filter(pk=duplicate.pk).update(strength='10 mg')
        self.assertEqual(suggest_product(self.row)[1].pk, self.product.pk)

    def test_invalid_first_match_stays_ambiguous_after_later_valid_match(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(name_fa='invalid\x1bname')
        ProductPresentation.objects.create(**self.product_data)
        self.assertEqual(suggest_product(self.row), ('ambiguous', None))

    def test_non_string_identity_makes_group_ambiguous_without_guessing(self):
        # PostgreSQL text columns normally return strings; simulate a malformed
        # materialized value to exercise the defensive, group-wide fallback.
        bad = SimpleNamespace(irc='001', manufacturer=None, strength='5 mg',
                              dosage_form='قرص', package_description='10 عدد', name_fa='نام ساختگی')
        with patch('pricing.importer.ProductPresentation.objects.filter') as query:
            query.return_value.defer.return_value.order_by.return_value.__getitem__.return_value = [bad]
            self.assertIsNone(_load_irc_index('001'))

    def test_stale_irc_projection_is_still_skipped_not_repaired(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(irc='other')
        self.assertEqual(suggest_product(self.row), ('unmatched', None))
        self.assertEqual(ProductPresentation.objects.get(pk=self.product.pk).irc_normalized, '001')

    def test_persian_joiner_and_unpublished_rows_remain_allowed(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(manufacturer='سازنده\u200cفرضی')
        status, product = suggest_product(self.row)
        self.assertEqual((status, product.pk), ('suggested', self.product.pk))
        self.assertFalse(product.published)

    def test_receipt_and_cached_duplicate_rows_record_ambiguous_observation(self):
        ProductPresentation.objects.filter(pk=self.product.pk).update(name_fa='invalid\x1bname')
        rows = [self.row, {**self.row, 'source_record_id': 'second'}]
        counts, receipt = stage_price_with_receipt(io.BytesIO(csv_bytes(rows)), 'منبع ساختگی',
            'https://example.org/feed', actor=self.stager, rights_attested=True)
        self.assertEqual((counts['rows'], counts['ambiguous']), (2, 2))
        self.assertEqual(list(receipt.items.order_by('ordinal').values_list('match_status', flat=True)),
                         ['ambiguous', 'ambiguous'])
        ProductPresentation.objects.filter(pk=self.product.pk).update(name_fa=self.product_data['name_fa'])
        self.assertEqual(suggest_product(self.row)[0], 'suggested')
        self.assertEqual(list(receipt.items.order_by('ordinal').values_list('match_status', flat=True)),
                         ['ambiguous', 'ambiguous'])

    def test_review_rechecks_invalidated_candidate_and_records_nothing(self):
        self.stage()
        candidate = PriceCandidate.objects.get()
        ProductPresentation.objects.filter(pk=self.product.pk).update(manufacturer='سازنده\nفرضی')
        self.product.refresh_from_db()
        # Even a freshly observed fingerprint must not turn unsafe text into a match.
        expected_hash = product_fingerprint(self.product)
        with self.assertRaises(ReviewConflict):
            record_preliminary_review(candidate_id=candidate.pk, actor=self.reviewer, decision='accept_suggestion',
                reason='دلیل ساختگی برای بازبینی اولیه', expected_review=0,
                expected_product=self.product.pk, expected_product_hash=expected_hash)
        self.assertFalse(PriceCandidateReview.objects.exists())
