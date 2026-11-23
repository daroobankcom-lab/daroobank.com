from copy import deepcopy
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .evidence import add_reference, digest, evidence_state
from .models import ClinicalDraft, ClinicalDraftReview
from .review_inspection import InvalidReviewInspection, ReviewInspectionNotFound, classify_review, inspect_reviews
from .services import create_draft, draft_data, fingerprint, review_draft, valid_draft


@override_settings(STAFF_PORTAL_ENABLED=True)
class ClinicalReviewInspectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('review-inspect-author', is_staff=True)
        cls.reviewer = User.objects.create_user('review-inspect-reviewer', is_staff=True)
        cls.viewer = User.objects.create_user('review-inspect-viewer', is_staff=True)
        cls.no_view = User.objects.create_user('review-inspect-no-view', is_staff=True)
        cls.regular = User.objects.create_user('review-inspect-regular')
        cls.inactive = User.objects.create_user('review-inspect-inactive', is_staff=True, is_active=False)
        perms = Permission.objects.filter(content_type__app_label='clinical')
        view = perms.get(codename='view_clinicaldraft')
        cls.author.user_permissions.add(view, perms.get(codename='add_clinicaldraft'))
        cls.reviewer.user_permissions.add(view, perms.get(codename='review_clinicaldraft'))
        for actor in [cls.viewer, cls.regular, cls.inactive]: actor.user_permissions.add(view)
        cls.data = {'subject': 'موضوع خصوصی ساختگی', 'audience': 'patient', 'title': 'عنوان خصوصی ساختگی',
                    'statement': 'متن خصوصی ساختگی برای بازرسی', 'reference_title': 'مرجع ساختگی',
                    'reference_url': 'https://example.org/review-inspection', 'reference_location': 'بخش ساختگی',
                    'reference_author': '', 'reference_version': '', 'reference_published_on': date(2025, 1, 2),
                    'reference_accessed_on': None}
        cls.reason = 'دلیل خصوصی ساختگی برای بازبینی'

    def make(self, with_reference=False):
        draft = create_draft(actor=self.author, data=self.data)
        if with_reference:
            data = {k: self.data[k] for k in ('reference_title', 'reference_url', 'reference_location',
                    'reference_author', 'reference_version', 'reference_published_on', 'reference_accessed_on')}
            data.update(reference_title='ارجاع تکمیلی ساختگی', relation='context')
            add_reference(actor=self.author, draft_id=draft.pk, data=data, expected_draft_hash=draft.payload_sha256,
                          expected_evidence_hash=evidence_state(draft)['fingerprint'])
        event = review_draft(actor=self.reviewer, draft_id=draft.pk, decision='defer', reason=self.reason,
                             expected_review=0, expected_hash=draft.payload_sha256,
                             expected_evidence_hash=evidence_state(draft)['fingerprint'])
        return draft, event

    def inspect(self, draft, **kwargs):
        return inspect_reviews(actor=self.viewer, draft_id=draft.pk, **kwargs)

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_statuses_and_historical_legacy_are_independent_of_current_evidence(self):
        draft, event = self.make(with_reference=True)
        self.assertEqual(classify_review(event, draft, True), ('consistent', 'same'))
        legacy = {k: v for k, v in event.review_snapshot.items() if not k.startswith('evidence_')}
        ClinicalDraftReview.objects.filter(pk=event.pk).update(review_snapshot=legacy)
        event.refresh_from_db()
        self.assertEqual(classify_review(event, draft, True), ('legacy', 'same'))
        legacy['evidence_fingerprint'] = 'x'
        ClinicalDraftReview.objects.filter(pk=event.pk).update(review_snapshot=legacy)
        event.refresh_from_db()
        self.assertEqual(classify_review(event, draft, True), ('invalid_record', 'unknown'))

    def test_tampered_record_and_snapshot_fail_closed(self):
        draft, event = self.make()
        original = deepcopy(event.review_snapshot)
        event.review_snapshot = None
        self.assertEqual(classify_review(event, draft, True), ('invalid_record', 'unknown'))
        variants = [[], {}, {**original, 'extra': 'private-canary'},
                    {**original, 'author_id': True}, {**original, 'author_id': self.reviewer.pk},
                    {**original, 'parent_id': True}, {**original, 'title': 'متن خصوصی تغییر یافته'},
                    {**original, 'reference_published_on': '20250102'},
                    {**original, 'reference_published_on': '2025-02-30'},
                    {**original, 'reference_url': 'http://example.org'},
                    {**original, 'change_reason': 'اضافه ناسازگار'}]
        for snap in variants:
            with self.subTest(snapshot=repr(snap)[:100]):
                ClinicalDraftReview.objects.filter(pk=event.pk).update(review_snapshot=snap)
                event.refresh_from_db()
                self.assertEqual(classify_review(event, draft, True), ('invalid_record', 'unknown'))
        ClinicalDraftReview.objects.filter(pk=event.pk).update(review_snapshot=original, reason='short')
        event.refresh_from_db()
        self.assertEqual(classify_review(event, draft, True), ('invalid_record', 'unknown'))
        ClinicalDraftReview.objects.filter(pk=event.pk).update(reason=' ' + self.reason)
        event.refresh_from_db()
        self.assertEqual(classify_review(event, draft, True), ('invalid_record', 'unknown'))
        ClinicalDraftReview.objects.filter(pk=event.pk).update(reason=self.reason, draft_payload_sha256='0' * 64)
        event.refresh_from_db()
        self.assertEqual(classify_review(event, draft, True), ('invalid_record', 'unknown'))

    def test_invalid_historical_evidence_and_reviewer_contributor(self):
        draft, event = self.make(with_reference=True)
        original = deepcopy(event.review_snapshot)
        for change in [{'evidence_version': True}, {'evidence_fingerprint': '0' * 64},
                       {'evidence_snapshot': [{'bad': 'shape'}]}, {'evidence_snapshot': original['evidence_snapshot'] * 11}]:
            with self.subTest(change=repr(change)[:100]):
                ClinicalDraftReview.objects.filter(pk=event.pk).update(review_snapshot={**original, **change})
                event.refresh_from_db()
                self.assertEqual(classify_review(event, draft, True), ('invalid_evidence', 'same'))
        changed = deepcopy(original)
        changed['evidence_snapshot'][0]['recorded_by_id'] = self.reviewer.pk
        item = changed['evidence_snapshot'][0]
        changed['evidence_fingerprint'] = digest([{key: item[key] for key in ('id', 'payload_sha256', 'recorded_by_id')}])
        ClinicalDraftReview.objects.filter(pk=event.pk).update(review_snapshot=changed)
        event.refresh_from_db()
        self.assertEqual(classify_review(event, draft, True), ('invalid_evidence', 'same'))

    def test_current_comparison_and_unknown_do_not_compare_current_evidence(self):
        draft, event = self.make()
        data = {k: self.data[k] for k in ('reference_title', 'reference_url', 'reference_location', 'reference_author',
                'reference_version', 'reference_published_on', 'reference_accessed_on')}
        data.update(relation='context')
        add_reference(actor=self.author, draft_id=draft.pk, data=data, expected_draft_hash=draft.payload_sha256,
                      expected_evidence_hash=evidence_state(draft)['fingerprint'])
        self.assertEqual(self.inspect(draft)['rows'][0]['comparison'], 'same')
        altered = {**draft_data(draft), 'title': 'نسخه تازه ساختگی'}
        new_hash = fingerprint(altered, None, '', '')
        ClinicalDraft.objects.filter(pk=draft.pk).update(title=altered['title'], payload_sha256=new_hash)
        draft.refresh_from_db()
        self.assertTrue(valid_draft(draft))
        self.assertEqual(self.inspect(draft)['rows'][0]['comparison'], 'different')
        ClinicalDraft.objects.filter(pk=draft.pk).update(statement='داده تغییر یافته')
        self.assertEqual(self.inspect(draft)['rows'][0]['comparison'], 'unknown')

    def test_paging_filter_and_select_query_bounds(self):
        draft, event = self.make()
        others = [ClinicalDraftReview(draft=draft, reviewer=self.reviewer, decision=event.decision, reason=event.reason,
                  draft_payload_sha256=event.draft_payload_sha256, review_snapshot=deepcopy(event.review_snapshot)) for _ in range(50)]
        ClinicalDraftReview.objects.bulk_create(others)
        last = ClinicalDraftReview.objects.filter(draft=draft).order_by('-pk').first()
        ClinicalDraftReview.objects.filter(pk=last.pk).update(reason='short')
        self.assertTrue(self.viewer.has_perm('clinical.view_clinicaldraft'))
        with CaptureQueriesContext(connection) as captured, patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            first = self.inspect(draft, category='invalid_record')
        self.assertEqual(len(captured), 2)
        self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in captured))
        self.assertIn('LIMIT 51', captured[1]['sql'].upper())
        self.assertEqual(first['scanned'], 50)
        self.assertEqual(first['rows'], [])
        self.assertIsNotNone(first['next_after'])
        second = self.inspect(draft, after=first['next_after'], category='invalid_record')
        self.assertEqual(second['rows'], [{'id': last.pk, 'status': 'invalid_record', 'comparison': 'unknown'}])
        self.assertIsNone(second['next_after'])
        other_draft, other_event = self.make()
        self.assertNotIn(other_event.pk, [r['id'] for r in self.inspect(draft)['rows']])
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_clinical_review_inspection', args=[draft.pk]), {'category': 'invalid_record', 'after': '۰'})
        self.assertContains(response, f'?after={first["next_after"]}&amp;category=invalid_record')
        self.assertContains(response, 'در این بخش نتیجه‌ای مطابق فیلتر دیده نشد')

    def test_missing_reviewer_does_not_hide_history_but_existence_is_not_checked(self):
        draft, event = self.make()
        # Foreign key checks are deferred in this synthetic PostgreSQL transaction.
        try:
            ClinicalDraftReview.objects.filter(pk=event.pk).update(reviewer_id=2147483647)
            report = self.inspect(draft)
            self.assertEqual(report['rows'], [{'id': event.pk, 'status': 'consistent', 'comparison': 'same'}])
        finally:
            ClinicalDraftReview.objects.filter(pk=event.pk).update(reviewer_id=self.reviewer.pk)

    def test_no_reviews_and_empty_filter_are_bounded(self):
        draft = create_draft(actor=self.author, data=self.data)
        report = self.inspect(draft)
        self.assertEqual(report['rows'], [])
        self.assertEqual(report['scanned'], 0)
        self.assertIsNone(report['next_after'])
        self.assertEqual(self.inspect(draft, after=9223372036854775807)['rows'], [])
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_clinical_review_inspection', args=[draft.pk]))
        self.assertContains(response, 'در این بخش نتیجه‌ای مطابق فیلتر دیده نشد')

    def test_service_input_and_access(self):
        draft, _ = self.make()
        for actor in [None, self.no_view, self.regular, self.inactive]:
            with self.assertRaises(PermissionDenied): inspect_reviews(actor=actor, draft_id=draft.pk)
        for value in [True, -1, 2**63, '0', None]:
            with self.subTest(after=value), self.assertRaises(InvalidReviewInspection): self.inspect(draft, after=value)
        for value in [None, [], 'bad']:
            with self.subTest(category=value), self.assertRaises(InvalidReviewInspection): self.inspect(draft, category=value)
        for value in [0, True, -1, 2**63, '1', 99999999]:
            with self.subTest(draft_id=value), self.assertRaises(ReviewInspectionNotFound):
                inspect_reviews(actor=self.viewer, draft_id=value)

    def test_web_access_privacy_navigation_and_errors(self):
        draft, event = self.make(with_reference=True)
        path = reverse('staff_clinical_review_inspection', args=[draft.pk])
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        self.assert_private(response)
        self.client.force_login(self.no_view)
        response = self.client.get(path, {'after': 'canary'})
        self.assertEqual(response.status_code, 403)
        self.assert_private(response)
        user = get_user_model().objects.create_user('review-inspection-group', is_staff=True)
        group = Group.objects.create(name='review-inspection-viewers')
        group.permissions.add(Permission.objects.get(content_type__app_label='clinical', codename='view_clinicaldraft'))
        user.groups.add(group)
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse('staff_clinical_detail', args=[draft.pk])), path)
        for method, status in [('get', 200), ('head', 200), ('post', 405)]:
            response = getattr(self.client, method)(path)
            self.assertEqual(response.status_code, status)
            self.assert_private(response)
        response = self.client.get(path)
        for hidden in [self.data['subject'], self.data['title'], self.data['reference_url'], self.reason, event.draft_payload_sha256]:
            self.assertNotContains(response, hidden)
        self.assertContains(response, 'بدون ناسازگاری شناسایی‌شده')
        for params in [{'after': '-1'}, {'after': '9223372036854775808'}, {'after': '1' * 100}, {'category': 'canary<script>'}]:
            response = self.client.get(path, params)
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, 'canary', status_code=400)
            self.assertContains(response, f'href="{path}"', status_code=400)
            self.assert_private(response)
        self.assertEqual(self.client.get(path, {'after': '٠۰0'}).status_code, 200)
        self.assertEqual(self.client.get(reverse('staff_clinical_review_inspection', args=[99999999]), {'after': 'bad'}).status_code, 404)
        self.assertNotContains(self.client.get(reverse('sitemap')), path)

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_disabled_portal(self):
        self.client.force_login(self.viewer)
        for method in [self.client.get, self.client.post]:
            response = method(reverse('staff_clinical_review_inspection', args=[1]))
            self.assertEqual(response.status_code, 404)
            self.assert_private(response)
