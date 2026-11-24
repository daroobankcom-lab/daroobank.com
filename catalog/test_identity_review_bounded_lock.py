"""Synthetic latest identity review write-lock transfer bounds."""
from decimal import Decimal
from unittest.mock import patch

from django.db import connection, transaction
from django.db.models import TextField
from django.db.models.functions import Cast, Length
from daroobank.review_content_bounds import MAX_REVIEW_JSON_TEXT_LENGTH, MAX_REVIEW_REASON_LENGTH
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext

from . import test_identity_missing_reviewers as fixtures
from .identity import (IdentityConflict, _lock_latest_package_review, digest, package_snapshot,
                       review_package, revise_package)
from .models import IdentityPackageDraft, IdentityPackageReview
from .test_identity import PACKAGE


@override_settings(STAFF_PORTAL_ENABLED=True)
class IdentityReviewBoundedLockTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.MissingIdentityReviewerTests.setUpTestData.__func__(cls)

    def test_lock_selects_bounded_values_and_preserves_row_lock(self):
        IdentityPackageReview.objects.filter(pk=self.event.pk).update(
            graph_snapshot={'private-canary': 'آ' * 1_000_000}, reason='ر' * 100_000)
        with transaction.atomic(), CaptureQueriesContext(connection) as queries:
            locked = _lock_latest_package_review(self.package)
        self.assertEqual(len(queries), 1)
        self.assertEqual(locked.pk, self.event.pk)
        self.assertTrue(locked.content_oversized)
        self.assertIsNone(locked.graph_snapshot)
        self.assertIsNone(locked.reason)
        self.assertEqual(locked.get_deferred_fields(), set())
        sql = queries[0]['sql']
        select = sql.split(' FROM ', 1)[0].lower()
        self.assertIn(' FOR UPDATE', sql.upper())
        self.assertIn('LIMIT 1', sql.upper())
        self.assertIn('substring', select)
        self.assertIn('case', select)
        self.assertNotRegex(select, r'(?:^select |, )"catalog_identitypackagereview"\."(?:reason|graph_snapshot)"(?:,|$)')

    def test_revision_rejects_oversized_without_classifying_partial_data_or_writing(self):
        IdentityPackageReview.objects.filter(pk=self.event.pk).update(graph_snapshot={'private': 'آ' * 1_000_000})
        with patch('catalog.identity.review_is_consistent', side_effect=AssertionError('oversized graph classified')):
            with self.assertRaises(IdentityConflict):
                revise_package(actor=self.editor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                    change_reason='تغییر ساختگی برای آزمون ایمن', expected_graph_hash=digest(package_snapshot(self.package)),
                    expected_review=self.event.pk)
        self.assertEqual(IdentityPackageDraft.objects.count(), 1)
        self.assertEqual(IdentityPackageReview.objects.count(), 1)

    def test_new_review_preserves_existing_policy_and_checks_latest_id(self):
        IdentityPackageReview.objects.filter(pk=self.event.pk).update(reason='ر' * 100_000)
        with self.assertRaises(IdentityConflict):
            review_package(actor=self.reviewer, package_id=self.package.pk, decision='defer',
                reason='دلیل ساختگی برای بررسی دوباره', expected_review=0,
                expected_graph_hash=digest(package_snapshot(self.package)))
        new = review_package(actor=self.reviewer, package_id=self.package.pk, decision='defer',
            reason='دلیل ساختگی برای بررسی دوباره', expected_review=self.event.pk,
            expected_graph_hash=digest(package_snapshot(self.package)))
        self.assertGreater(new.pk, self.event.pk)
        self.assertEqual(IdentityPackageReview.objects.count(), 2)

    def test_valid_latest_still_allows_revision(self):
        child = revise_package(actor=self.editor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
            change_reason='تغییر ساختگی برای آزمون ایمن', expected_graph_hash=digest(package_snapshot(self.package)),
            expected_review=self.event.pk)
        self.assertNotEqual(child.pk, self.package.pk)

    def test_postgresql_character_thresholds_fail_closed_only_above_limit(self):
        for size in (MAX_REVIEW_REASON_LENGTH, MAX_REVIEW_REASON_LENGTH + 1):
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reason='ر' * size,
                                                                         graph_snapshot=self.event.graph_snapshot)
            with transaction.atomic():
                locked = _lock_latest_package_review(self.package)
            self.assertEqual(locked.content_oversized, size > MAX_REVIEW_REASON_LENGTH)
            if size == MAX_REVIEW_REASON_LENGTH:
                self.assertEqual(len(locked.reason), size)
            else:
                self.assertIsNone(locked.reason)
        for size in (MAX_REVIEW_JSON_TEXT_LENGTH, MAX_REVIEW_JSON_TEXT_LENGTH + 1):
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reason=self.event.reason,
                graph_snapshot={'x': 'آ' * (size - len('{"x": ""}'))})
            actual = IdentityPackageReview.objects.annotate(n=Length(Cast('graph_snapshot', TextField()))).get(pk=self.event.pk).n
            self.assertEqual(actual, size)
            with transaction.atomic():
                locked = _lock_latest_package_review(self.package)
            self.assertEqual(locked.content_oversized, size > MAX_REVIEW_JSON_TEXT_LENGTH)
            self.assertEqual(locked.graph_snapshot is None, size > MAX_REVIEW_JSON_TEXT_LENGTH)
