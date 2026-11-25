"""Synthetic evidence note bounds on claim replay and review lock reads."""
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import tests as fixtures
from .models import SourceClaim, SourceClaimReview
from .services import ClaimConflict, ReviewConflict, record_claim, review_claim


def assert_bounded_claim_selects(test, queries, *, lookups=1):
    sqls = [q['sql'] for q in queries if q['sql'].startswith('SELECT') and 'FROM "sources_sourceclaim"' in q['sql']]
    test.assertGreaterEqual(len(sqls), lookups)
    locked = 0
    for sql in sqls:
        selection = sql.split(' FROM ', 1)[0].lower()
        test.assertNotRegex(selection, r'(?:^select |, )"sources_sourceclaim"\."evidence_note"(?:,|$)')
        if 'FOR UPDATE' in sql:
            locked += 1
            test.assertIn('substring', selection)
    test.assertEqual(locked, 1)


@override_settings(STAFF_PORTAL_ENABLED=True)
class BoundedClaimWriteTests(TestCase):
    claim = fixtures.SourceClaimTests.claim
    post_data = fixtures.SourceClaimTests.post_data

    @classmethod
    def setUpTestData(cls):
        fixtures.SourceClaimTests.setUpTestData.__func__(cls)

    def oversized_claim(self):
        claim = self.claim()
        SourceClaim.objects.filter(pk=claim.pk).update(evidence_note='ر' * 1_000_000 + 'writer-canary')
        return claim

    def test_replay_prelookup_and_lock_are_bounded_and_atomic(self):
        claim = self.oversized_claim()
        self.author.has_perm('sources.add_sourceclaim')
        with patch('sources.services.valid_claim', side_effect=AssertionError('partial note must not be validated')):
            with CaptureQueriesContext(connection) as queries:
                with self.assertRaises(ClaimConflict):
                    record_claim(actor=self.author, data=self.data)
        assert_bounded_claim_selects(self, queries, lookups=2)
        self.assertEqual(SourceClaim.objects.count(), 1)
        self.assertEqual(len(SourceClaim.objects.get(pk=claim.pk).evidence_note), 1_000_000 + len('writer-canary'))
        self.client.force_login(self.author)
        response = self.client.post(reverse('staff_source_create'), self.post_data())
        self.assertEqual(response.status_code, 409)
        self.assertNotContains(response, 'writer-canary', status_code=409)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(SourceClaim.objects.count(), 1)

    def test_review_lock_is_bounded_rejects_without_validator_and_keeps_self_permission(self):
        claim = self.oversized_claim()
        args = dict(claim_id=claim.pk, decision='defer', reason='توضیح ساختگی برای بررسی بیشتر',
                    expected_review=0, expected_hash=claim.payload_sha256)
        self.reviewer.has_perm('sources.review_sourceclaim')
        with patch('sources.services.valid_claim', side_effect=AssertionError('partial note must not be validated')):
            with CaptureQueriesContext(connection) as queries:
                with self.assertRaises(ReviewConflict):
                    review_claim(actor=self.reviewer, **args)
        assert_bounded_claim_selects(self, queries)
        self.assertFalse(SourceClaimReview.objects.exists())
        with self.assertRaises(PermissionDenied):
            review_claim(actor=self.author, **args)
        self.client.force_login(self.reviewer)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(reverse('staff_source_review', args=[claim.pk]), {
                'decision': args['decision'], 'reason': args['reason'], 'expected_review': 0, 'expected_hash': args['expected_hash']})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'شرح مدرک بیش از حد مجاز است؛ نمایش داده نمی‌شود', status_code=409)
        self.assertNotContains(response, 'writer-canary', status_code=409)
        assert_bounded_claim_selects(self, queries, lookups=3)
        self.assertFalse(SourceClaimReview.objects.exists())
