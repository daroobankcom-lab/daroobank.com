"""Synthetic source-review snapshot checks; never legal or provenance validation."""
from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import SourceClaim, SourceClaimReview
from .review_inspection import (BATCH_SIZE, MAX_PK, InvalidReviewInspection,
                                ReviewInspectionNotFound, classify_review, inspect_reviews)
from .services import claim_data, fingerprint, record_claim, review_claim


@override_settings(STAFF_PORTAL_ENABLED=True)
class SourceReviewInspectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('source-inspect-author', is_staff=True)
        cls.reviewer = User.objects.create_user('source-inspect-reviewer', is_staff=True)
        cls.viewer = User.objects.create_user('source-inspect-viewer', is_staff=True)
        cls.no_view = User.objects.create_user('source-inspect-no-view', is_staff=True)
        cls.regular = User.objects.create_user('source-inspect-regular')
        cls.inactive = User.objects.create_user('source-inspect-inactive', is_staff=True, is_active=False)
        permissions = Permission.objects.filter(content_type__app_label='sources')
        view = permissions.get(codename='view_sourceclaim')
        cls.author.user_permissions.add(view, permissions.get(codename='add_sourceclaim'))
        cls.reviewer.user_permissions.add(view, permissions.get(codename='review_sourceclaim'))
        for actor in (cls.viewer, cls.regular, cls.inactive):
            actor.user_permissions.add(view)
        cls.data = {'source_name': 'منبع محرمانه ساختگی', 'source_url': 'https://example.org/private-source',
                    'owner': 'مالک ساختگی', 'evidence_url': 'https://example.org/private-evidence',
                    'evidence_note': 'یادداشت خصوصی ساختگی', 'claims_collection': True, 'claims_storage': False,
                    'claims_publication': False, 'starts_on': date(2025, 1, 2), 'expires_on': None}
        cls.reason = 'دلیل خصوصی ساختگی برای بررسی اولیه'

    def make(self):
        claim, created = record_claim(actor=self.author, data=self.data)
        self.assertTrue(created)
        event = review_claim(actor=self.reviewer, claim_id=claim.pk, decision='defer', reason=self.reason,
                             expected_review=0, expected_hash=claim.payload_sha256)
        return claim, event

    def inspect(self, claim, actor=None, **kwargs):
        return inspect_reviews(actor=actor or self.viewer, claim_id=claim.pk, **kwargs)

    def test_actual_review_classifies_without_writing_or_exposing_snapshot(self):
        claim, event = self.make()
        before = (SourceClaim.objects.count(), SourceClaimReview.objects.count())
        self.assertTrue(self.viewer.has_perm('sources.view_sourceclaim'))  # warm permission cache
        with CaptureQueriesContext(connection) as queries:
            report = self.inspect(claim)
        self.assertEqual(len(queries), 2)
        self.assertEqual(report['rows'], [{'id': event.pk, 'status': 'consistent', 'comparison': 'same'}])
        self.assertEqual((SourceClaim.objects.count(), SourceClaimReview.objects.count()), before)
        self.client.force_login(self.viewer)
        path = reverse('staff_source_review_inspection', args=[claim.pk])
        response = self.client.get(path)
        self.assertContains(response, 'بدون ناسازگاری شناسایی‌شده')
        for value in (self.data['source_name'], self.data['source_url'], self.data['evidence_url'],
                      self.data['evidence_note'], self.reason, event.claim_payload_sha256):
            self.assertNotContains(response, value)
        self.assertContains(self.client.get(reverse('staff_source_detail', args=[claim.pk])), path)

    def test_malformed_snapshot_and_review_metadata_fail_closed(self):
        claim, event = self.make()
        original = deepcopy(event.review_snapshot)
        for update in (dict(review_snapshot={'bad': 'private-canary'}),
                       dict(review_snapshot={**original, 'extra': 'private-canary'}),
                       dict(review_snapshot={**original, 'starts_on': '20250102'}),
                       dict(review_snapshot={**original, 'starts_on': True}),
                       dict(review_snapshot={**original, 'claims_collection': 1}),
                       dict(review_snapshot={**original, 'evidence_url': 'http://example.org'}),
                       dict(review_snapshot={**original, 'recorded_by_id': self.reviewer.pk}),
                       dict(claim_payload_sha256='0' * 64), dict(reason='short'),
                       dict(reason=' ' + self.reason)):
            with self.subTest(update=update):
                SourceClaimReview.objects.filter(pk=event.pk).update(**update)
                event.refresh_from_db()
                self.assertEqual(classify_review(event, claim, True), ('invalid_record', 'unknown'))
                SourceClaimReview.objects.filter(pk=event.pk).update(
                    review_snapshot=original, claim_payload_sha256=claim.payload_sha256, reason=self.reason)
        self.client.force_login(self.viewer)
        SourceClaimReview.objects.filter(pk=event.pk).update(review_snapshot={'bad': 'private-canary'})
        response = self.client.get(reverse('staff_source_review_inspection', args=[claim.pk]))
        self.assertContains(response, 'رکورد بازبینی ناسازگار')
        self.assertNotContains(response, 'private-canary')

    def test_current_comparison_and_invalid_current_are_distinct(self):
        claim, event = self.make()
        self.assertEqual(self.inspect(claim)['rows'][0]['comparison'], 'same')
        changed = {**claim_data(claim), 'owner': 'مالک متفاوت ساختگی'}
        SourceClaim.objects.filter(pk=claim.pk).update(owner=changed['owner'], payload_sha256=fingerprint(changed))
        self.assertEqual(self.inspect(claim)['rows'][0]['comparison'], 'different')
        SourceClaim.objects.filter(pk=claim.pk).update(owner='تغییر بدون اثر انگشت')
        self.assertEqual(self.inspect(claim)['rows'][0]['comparison'], 'unknown')
        self.assertEqual(self.inspect(claim)['rows'][0]['status'], 'consistent')

    def test_structural_checker_rejects_invalid_in_memory_metadata(self):
        claim, event = self.make()
        data = {'review_snapshot': event.review_snapshot, 'claim_id': claim.pk, 'reviewer_id': event.reviewer_id,
                'decision': event.decision, 'reason': event.reason, 'claim_payload_sha256': event.claim_payload_sha256}
        for update in (dict(claim_id=True), dict(reviewer_id=True), dict(reviewer_id=0),
                       dict(decision=[]), dict(decision='invalid'), dict(reason=None),
                       dict(claim_payload_sha256=None), dict(claim_payload_sha256='a' * 65)):
            with self.subTest(update=update):
                self.assertEqual(classify_review(SimpleNamespace(**{**data, **update}), claim, True),
                                 ('invalid_record', 'unknown'))

    def test_coherent_rewrite_can_still_pass_and_does_not_prove_authenticity(self):
        claim, event = self.make()
        altered = {**self.data, 'owner': 'مالک ساختگی بازنویسی‌شده'}
        from .services import snapshot
        historical = {**snapshot(altered), 'recorded_by_id': self.author.pk}
        digest = fingerprint(altered)
        SourceClaimReview.objects.filter(pk=event.pk).update(review_snapshot=historical, claim_payload_sha256=digest)
        SourceClaim.objects.filter(pk=claim.pk).update(owner=altered['owner'], payload_sha256=digest)
        row = self.inspect(claim)['rows'][0]
        self.assertEqual((row['status'], row['comparison']), ('consistent', 'same'))

    def test_change_after_claim_fetch_is_not_a_snapshot(self):
        claim, _ = self.make()
        from . import review_inspection
        from .services import valid_claim
        changed = {**claim_data(claim), 'owner': 'مالک تغییر یافته ساختگی'}
        def validate_then_change(obj):
            valid = valid_claim(obj)
            SourceClaim.objects.filter(pk=obj.pk).update(owner=changed['owner'], payload_sha256=fingerprint(changed))
            return valid
        with patch.object(review_inspection, 'valid_claim', side_effect=validate_then_change):
            self.assertEqual(self.inspect(claim)['rows'][0]['comparison'], 'same')
        self.assertEqual(self.inspect(claim)['rows'][0]['comparison'], 'different')

    def test_missing_reviewer_not_hidden_but_account_existence_is_not_checked(self):
        claim, event = self.make()
        try:
            SourceClaimReview.objects.filter(pk=event.pk).update(reviewer_id=2147483647)
            self.assertEqual(self.inspect(claim)['rows'][0]['status'], 'consistent')
        finally:
            SourceClaimReview.objects.filter(pk=event.pk).update(reviewer_id=self.reviewer.pk)

    def test_bounded_scan_filters_after_scanning_and_preserves_next_position(self):
        claim, event = self.make()
        for _ in range(BATCH_SIZE + 3):
            SourceClaimReview.objects.create(claim=claim, reviewer=self.reviewer, decision='defer', reason=self.reason,
                claim_payload_sha256=claim.payload_sha256, review_snapshot=event.review_snapshot)
        last = SourceClaimReview.objects.filter(claim=claim).order_by('pk')[BATCH_SIZE]
        SourceClaimReview.objects.filter(pk=last.pk).update(review_snapshot={'bad': 'private-canary'})
        first = self.inspect(claim, category='invalid_record')
        self.assertEqual((first['scanned'], first['rows']), (BATCH_SIZE, []))
        self.assertIsNotNone(first['next_after'])
        second = self.inspect(claim, after=first['next_after'], category='invalid_record')
        self.assertEqual(second['rows'], [{'id': last.pk, 'status': 'invalid_record', 'comparison': 'unknown'}])
        self.assertIsNone(second['next_after'])
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_source_review_inspection', args=[claim.pk]), {'category': 'invalid_record'})
        self.assertContains(response, f'?after={first["next_after"]}&amp;category=invalid_record')

    def test_empty_and_cross_claim_history_remain_separate(self):
        claim, event = self.make()
        other, created = record_claim(actor=self.author, data={**self.data, 'owner': 'مالک دیگر ساختگی'})
        self.assertTrue(created)
        empty = self.inspect(other)
        self.assertEqual((empty['scanned'], empty['rows'], empty['next_after']), (0, [], None))
        self.assertEqual(self.inspect(claim, after=MAX_PK)['rows'], [])
        response = self.client.get(reverse('staff_source_review_inspection', args=[other.pk]))
        self.assertEqual(response.status_code, 302)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_source_review_inspection', args=[other.pk]))
        self.assertContains(response, 'در این بخش نتیجه‌ای مطابق فیلتر دیده نشد')
        self.assertNotContains(response, f'شناسه بازبینی {event.pk}')

    def test_service_permissions_and_input(self):
        claim, _ = self.make()
        for actor in (None, self.no_view, self.regular, self.inactive):
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                inspect_reviews(actor=actor, claim_id=claim.pk)
        for bad in (True, -1, MAX_PK + 1, '1', None):
            with self.subTest(after=bad), self.assertRaises(InvalidReviewInspection):
                inspect_reviews(actor=self.viewer, claim_id=claim.pk, after=bad)
        for bad in (None, [], 'bad'):
            with self.subTest(category=bad), self.assertRaises(InvalidReviewInspection):
                inspect_reviews(actor=self.viewer, claim_id=claim.pk, category=bad)
        for bad in (0, True, -1, MAX_PK + 1, '1', 999999999):
            with self.subTest(claim_id=bad), self.assertRaises(ReviewInspectionNotFound):
                inspect_reviews(actor=self.viewer, claim_id=bad)

    def test_web_permissions_methods_private_headers_and_unreflecting_errors(self):
        claim, _ = self.make()
        path = reverse('staff_source_review_inspection', args=[claim.pk])
        self.assertEqual(self.client.get(path).status_code, 302)
        self.client.force_login(self.no_view)
        self.assertEqual(self.client.get(path, {'after': 'bad'}).status_code, 403)
        user = get_user_model().objects.create_user('source-inspect-group', is_staff=True)
        group = Group.objects.create(name='synthetic-source-inspection-viewers')
        group.permissions.add(Permission.objects.get(content_type__app_label='sources', codename='view_sourceclaim'))
        user.groups.add(group)
        self.client.force_login(user)
        for method, code in (('get', 200), ('head', 200), ('post', 405)):
            response = getattr(self.client, method)(path)
            self.assertEqual(response.status_code, code)
            self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
            self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
            self.assertEqual(response['Referrer-Policy'], 'same-origin')
        for params in ({'after': '1' * 100}, {'after': '9223372036854775808'}, {'category': 'secret-canary<script>'}):
            response = self.client.get(path, params)
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, 'secret-canary', status_code=400)
            self.assertContains(response, f'href="{path}"', status_code=400)
        self.assertEqual(self.client.get(path, {'after': '٠۰0'}).status_code, 200)
        self.assertEqual(self.client.get(reverse('staff_source_review_inspection', args=[99999999]), {'after': 'bad'}).status_code, 404)

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_disabled_portal(self):
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_source_review_inspection', args=[1]))
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
