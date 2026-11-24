"""The synthetic repair must not fetch an unbounded stored search projection."""
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from . import projection_repair
from .models import ProductPresentation


@override_settings(DEBUG=True, SECRET_KEY='synthetic-bounded-projection-key')
class ProjectionRepairBoundedFetchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='نام ساختگی', manufacturer='سازنده فرضی', strength='5 mg', dosage_form='قرص',
            package_description='10 عدد', irc='123', source_name='منبع فرضی',
            source_url='https://example.org/synthetic')

    def update_projection(self, text):
        ProductPresentation.objects.filter(pk=self.product.pk).update(search_text=text)

    def preview(self):
        return projection_repair.preview_projection(presentation_id=self.product.pk)

    def apply(self, token):
        return projection_repair.apply_projection(presentation_id=self.product.pk, token=token,
                                                  synthetic_confirmed=True)

    def assert_bounded_select(self, queries):
        selects = [q['sql'].split(' FROM ', 1)[0].lower() for q in queries
                   if q['sql'].lstrip().upper().startswith('SELECT') and 'catalog_productpresentation' in q['sql']]
        self.assertEqual(len(selects), 1)
        self.assertIn('substring(', selects[0])
        self.assertNotRegex(selects[0], r'(?:^select |, )"catalog_productpresentation"\."search_text"(?:,|$)')

    def test_oversized_unicode_projection_is_unsafe_without_transferring_whole_column(self):
        self.update_projection('م' * 1_000_000)
        original = projection_repair._expected
        with patch('catalog.projection_repair._expected', wraps=original) as validate, CaptureQueriesContext(connection) as queries:
            result = self.preview()
        self.assertEqual(result, {'id': self.product.pk, 'status': 'unsafe', 'fields': []})
        self.assert_bounded_select(queries)
        self.assertEqual(len(validate.call_args.args[0]['search_text']), projection_repair.MAX_SEARCH_LENGTH + 1)
        self.assertEqual(ProductPresentation.objects.get(pk=self.product.pk).search_text, 'م' * 1_000_000)

    def test_bounded_fetch_preserves_complete_safe_state(self):
        for text in ('', 'private synthetic', 'آ' * projection_repair.MAX_SEARCH_LENGTH):
            with self.subTest(length=len(text)):
                self.update_projection(text)
                baseline = ProductPresentation.objects.values().get(pk=self.product.pk)
                fetched = projection_repair._fetch_row(self.product.pk)
                self.assertEqual(fetched, baseline)
                expected = projection_repair._expected(fetched)
                self.assertEqual(projection_repair._state_digest(fetched, expected),
                                 projection_repair._state_digest(baseline, expected))

    def test_exact_character_boundary_uses_full_state_and_next_character_is_unsafe(self):
        maximum = projection_repair.MAX_SEARCH_LENGTH
        self.update_projection('آ' * maximum)
        plan = self.preview()
        self.assertEqual(plan['status'], 'needs_repair')
        # A last-character change must invalidate the preview, not compare prefixes.
        self.update_projection('آ' * (maximum - 1) + 'ب')
        with self.assertRaises(projection_repair.ProjectionRepairError):
            self.apply(plan['token'])
        self.update_projection('آ' * (maximum + 1))
        self.assertEqual(self.preview()['status'], 'unsafe')

    def test_growth_after_preview_is_rejected_under_lock_without_update(self):
        self.update_projection('stale synthetic projection')
        token = self.preview()['token']
        self.update_projection('ز' * 1_000_000)
        with CaptureQueriesContext(connection) as queries, self.assertRaises(projection_repair.ProjectionRepairError):
            self.apply(token)
        self.assert_bounded_select(queries)
        self.assertTrue(any('FOR UPDATE' in q['sql'].upper() for q in queries))
        self.assertFalse(any(q['sql'].lstrip().upper().startswith('UPDATE') for q in queries))
        self.assertEqual(ProductPresentation.objects.get(pk=self.product.pk).search_text, 'ز' * 1_000_000)
