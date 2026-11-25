"""Synthetic oversized identity review display; not an authenticity check."""
from unittest.mock import patch

from django.db import connection
from django.db.models import JSONField, TextField, Value
from django.db.models.functions import Cast, Length
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from daroobank.review_content_bounds import (MAX_REVIEW_JSON_TEXT_LENGTH, MAX_REVIEW_REASON_LENGTH,
                                              bounded_review_fields)
from . import test_identity_missing_reviewers as fixtures
from .identity import digest, package_snapshot
from .models import IdentityPackageReview
from .test_identity import PACKAGE


@override_settings(STAFF_PORTAL_ENABLED=True)
class IdentityReviewBoundedContentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.MissingIdentityReviewerTests.setUpTestData.__func__(cls)

    def detail(self):
        return reverse('staff_identity_detail', args=['package', self.package.pk])

    def revise(self):
        return reverse('staff_identity_revise', args=[self.package.pk])

    def test_oversized_review_is_bounded_in_detail_and_revision(self):
        IdentityPackageReview.objects.filter(pk=self.event.pk).update(
            graph_snapshot={'private-canary': 'آ' * 1_000_000},
            reason='ر' * 100_000 + 'private-reason-canary')
        self.client.force_login(self.reviewer)
        self.reviewer.has_perm('catalog.view_identityworkspace')
        with patch('catalog.identity_views.review_is_consistent', side_effect=AssertionError('partial graph classified')):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(self.detail())
            self.assertEqual(response.status_code, 200)
            review = response.context['reviews'][0]
            self.assertTrue(review.content_oversized)
            self.assertFalse(review.safe)
            self.assertIsNone(review.graph_snapshot)
            self.assertIsNone(review.reason)
            self.assertEqual(response.context['review_form'].initial['expected_review'], self.event.pk)
            self.assertContains(response, 'بازبینی بیش از حد نمایش')
            self.assertNotContains(response, 'private-canary')
            self.assertNotContains(response, 'private-reason-canary')
            query = next(q['sql'] for q in queries if 'FROM "catalog_identitypackagereview"' in q['sql'])
            selection = query.split(' FROM ', 1)[0].lower()
            self.assertIn('case', selection)
            self.assertIn('substring', selection)
            self.assertNotRegex(selection, r'(?:^select |, )"catalog_identitypackagereview"\."(?:reason|graph_snapshot)"(?:,|$)')
            self.assertIn('LIMIT 26', query)
            self.assertIn('no-store', response['Cache-Control'])
            self.client.force_login(self.editor)
            response = self.client.get(self.revise())
            self.assertContains(response, 'بازبینی بیش از حد نمایش')
            self.assertContains(response, 'تا بررسی وضعیت آن غیرفعال است')
            self.assertNotContains(response, 'private-canary')
            self.assertNotContains(response, 'private-reason-canary')
            self.assertEqual(response.context['form'].initial['expected_review'], self.event.pk)
            self.assertNotContains(response, 'name="change_reason"')
        self.event.refresh_from_db()
        self.assertEqual(len(self.event.graph_snapshot['private-canary']), 1_000_000)

    def test_thresholds_and_malformed_small_json(self):
        self.client.force_login(self.viewer)
        for length in (MAX_REVIEW_REASON_LENGTH, MAX_REVIEW_REASON_LENGTH + 1):
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reason='ر' * length)
            row = self.client.get(self.detail()).context['reviews'][0]
            self.assertEqual(row.content_oversized, length > MAX_REVIEW_REASON_LENGTH)
            self.assertEqual(row.safe, length <= MAX_REVIEW_REASON_LENGTH)
        for length in (MAX_REVIEW_JSON_TEXT_LENGTH, MAX_REVIEW_JSON_TEXT_LENGTH + 1):
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reason=self.event.reason,
                graph_snapshot={'x': 'آ' * (length - len('{"x": ""}'))})
            measured = IdentityPackageReview.objects.annotate(n=Length(Cast('graph_snapshot', TextField()))).get(pk=self.event.pk).n
            self.assertEqual(measured, length)
            row = self.client.get(self.detail()).context['reviews'][0]
            self.assertEqual(row.content_oversized, length > MAX_REVIEW_JSON_TEXT_LENGTH)
            self.assertFalse(row.safe)
        for value in (Value(None, output_field=JSONField()), [], {'bad': 'small-hidden-canary'}):
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(graph_snapshot=value)
            response = self.client.get(self.detail())
            self.assertFalse(response.context['reviews'][0].content_oversized)
            self.assertFalse(response.context['reviews'][0].safe)
            self.assertNotContains(response, 'small-hidden-canary')

    def test_large_sentinel_retains_cursor_and_is_displayed_on_next_page(self):
        values = {f.attname: getattr(self.event, f.attname) for f in IdentityPackageReview._meta.concrete_fields
                  if f.name not in ('id', 'created_at')}
        IdentityPackageReview.objects.bulk_create([IdentityPackageReview(**values) for _ in range(25)])
        # Oldest row is the lookahead when 26 reviews exist.
        IdentityPackageReview.objects.filter(pk=self.event.pk).update(graph_snapshot={'secret': 'آ' * 1_000_000})
        with CaptureQueriesContext(connection) as queries:
            batch = list(bounded_review_fields(self.package.reviews.order_by('-pk'), snapshot_field='graph_snapshot')[:26])
        self.assertEqual(len(queries), 1)
        self.assertEqual(batch[-1].pk, self.event.pk)
        self.assertIsNone(batch[-1]._bounded_json)
        self.assertEqual(batch[-1].get_deferred_fields(), {'reason', 'graph_snapshot'})
        self.client.force_login(self.viewer)
        response = self.client.get(self.detail())
        self.assertEqual(len(response.context['reviews']), 25)
        self.assertEqual(response.context['next_before'], response.context['reviews'][-1].pk)
        self.assertNotContains(response, 'بازبینی بیش از حد نمایش')
        page = self.client.get(self.detail(), {'before': response.context['next_before']})
        self.assertEqual([r.pk for r in page.context['reviews']], [self.event.pk])
        self.assertContains(page, 'بازبینی بیش از حد نمایش')
        self.assertNotContains(page, 'secret')
        self.assertIsNone(page.context['next_before'])

    def test_invalid_post_preserves_uninspected_state_without_writing(self):
        IdentityPackageReview.objects.filter(pk=self.event.pk).update(reason='private-canary' + 'ر' * 100_000)
        self.client.force_login(self.reviewer)
        response = self.client.post(reverse('staff_identity_review', args=[self.package.pk]), {})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'بازبینی بیش از حد نمایش', status_code=400)
        self.assertNotContains(response, 'private-canary', status_code=400)
        self.assertEqual(IdentityPackageReview.objects.count(), 1)
        self.client.force_login(self.editor)
        response = self.client.post(self.revise(), {**PACKAGE, 'synthetic_ack': 'on',
            'change_reason': 'تغییر ساختگی و معتبر برای آزمون', 'expected_review': self.event.pk,
            'expected_graph_hash': digest(package_snapshot(self.package))})
        # The writer independently re-checks and refuses the invalid oversized latest review.
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, 'private-canary', status_code=409)
        self.assertEqual(IdentityPackageReview.objects.count(), 1)

    def test_reason_only_and_missing_reviewer_have_fixed_oversized_state(self):
        original_reviewer = self.event.reviewer_id
        IdentityPackageReview.objects.filter(pk=self.event.pk).update(reason='private-canary' + 'ر' * 100_000,
                                                                       reviewer_id=fixtures.MISSING)
        try:
            self.client.force_login(self.reviewer)
            response = self.client.get(self.detail())
            self.assertContains(response, 'بازبینی بیش از حد نمایش')
            self.assertNotContains(response, 'private-canary')
            self.assertEqual(response.context['review_form'].initial['expected_review'], self.event.pk)
            self.client.force_login(self.editor)
            response = self.client.get(self.revise())
            self.assertContains(response, 'بازبینی بیش از حد نمایش')
            self.assertNotContains(response, 'private-canary')
            self.assertNotContains(response, 'name="change_reason"')
        finally:
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reviewer_id=original_reviewer)

    def test_scope_permissions_and_visible_valid_neighbour(self):
        values = {f.attname: getattr(self.event, f.attname) for f in IdentityPackageReview._meta.concrete_fields
                  if f.name not in ('id', 'created_at')}
        newer = IdentityPackageReview.objects.create(**values)
        IdentityPackageReview.objects.filter(pk=self.event.pk).update(graph_snapshot={'private-canary': 'آ' * 100_000})
        self.client.force_login(self.viewer)
        response = self.client.get(self.detail())
        self.assertEqual([review.pk for review in response.context['reviews']], [newer.pk, self.event.pk])
        self.assertTrue(response.context['reviews'][0].safe)
        self.assertTrue(response.context['reviews'][1].content_oversized)
        self.assertContains(response, fixtures.SECRET)
        self.assertNotContains(response, 'private-canary')
        self.client.force_login(self.no_access)
        self.assertEqual(self.client.get(self.detail()).status_code, 403)
