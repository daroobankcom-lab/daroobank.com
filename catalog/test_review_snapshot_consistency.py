"""Synthetic product review-history consistency clues, not a provenance audit."""
import copy
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from .intake import fingerprint, review_product, stage_products
from .models import ProductCandidate, ProductCandidateReview
from .test_intake import make_csv


@override_settings(STAFF_PORTAL_ENABLED=True)
class ProductReviewSnapshotConsistencyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('product-history-author', is_staff=True)
        cls.reviewer = User.objects.create_user('product-history-reviewer', is_staff=True)
        perms = Permission.objects.filter(content_type__app_label='catalog')
        cls.author.user_permissions.add(*perms.filter(codename__in=['view_productcandidate', 'add_productcandidate']))
        cls.reviewer.user_permissions.add(*perms.filter(codename__in=['view_productcandidate', 'review_productcandidate']))
        cls.row = dict(source_record_id='synthetic-history', name_fa='فرآورده ساختگی', name_en='',
                       manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص',
                       package_description='10 عدد', irc='001')
        stage_products(io.BytesIO(make_csv([cls.row])), 'منبع ساختگی', 'https://example.org/product-history',
                       actor=cls.author, commit=True, rights_attested=True)
        cls.candidate = ProductCandidate.objects.get()
        cls.review = review_product(actor=cls.reviewer, candidate_id=cls.candidate.pk, decision='defer',
                                    reason='دلیل ساختگی برای بازبینی اولیه', expected_review=0,
                                    expected_hash=cls.candidate.payload_sha256)

    def setUp(self):
        self.client.force_login(self.reviewer)
        self.url = reverse('staff_product_detail', args=[self.candidate.pk])

    def rows(self, response):
        return {r.pk: r for r in response.context['reviews']}

    def test_writer_event_is_consistent_same_and_read_only(self):
        from .review_inspection import classify_review
        with self.assertNumQueries(0):
            self.assertEqual(classify_review(self.review, self.candidate, True), ('consistent', 'same'))
            self.assertEqual(classify_review(self.review, self.candidate, False), ('consistent', 'unknown'))
        response = self.client.get(self.url)
        self.assertContains(response, 'دلیل ساختگی برای بازبینی اولیه')
        self.assertContains(response, 'تصویر نامزد با داده فعلی برابر است')
        self.assertContains(response, 'این مقایسه تأیید اصالت یا هویت نیست')
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')

    def test_all_writer_decisions_are_supported(self):
        from .review_inspection import classify_review
        latest = self.review.pk
        for decision in ('reject', 'further_review'):
            event = review_product(actor=self.reviewer, candidate_id=self.candidate.pk, decision=decision,
                reason='تصمیم ساختگی برای بررسی بیشتر', expected_review=latest,
                expected_hash=self.candidate.payload_sha256)
            self.assertEqual(classify_review(event, self.candidate, True), ('consistent', 'same'))
            latest = event.pk
        response = self.client.get(self.url)
        self.assertContains(response, 'رد نامزد')
        self.assertContains(response, 'قابل ارجاع برای بررسی بیشتر')

    def test_missing_stager_makes_comparison_unknown(self):
        from daroobank.account_checks import current_accounts
        def reviewers_only(ids, **kwargs):
            return {key: value for key, value in current_accounts(ids, **kwargs).items() if key != self.author.pk}
        with patch('catalog.staff_views.current_accounts', side_effect=reviewers_only):
            response = self.client.get(self.url)
        review = self.rows(response)[self.review.pk]
        self.assertEqual((review.technical_status, review.candidate_comparison), ('consistent', 'unknown'))
        self.assertContains(response, 'مقایسه نامزد نامشخص است')

    def test_malformed_history_is_hidden_on_get_and_error_posts(self):
        snapshot = copy.deepcopy(self.review.review_snapshot)
        snapshot['source_fields']['name_fa'] = 'snapshot-canary'
        ProductCandidateReview.objects.filter(pk=self.review.pk).update(
            review_snapshot=snapshot, reason='reason-canary داده ساختگی برای بررسی')
        post_url = reverse('staff_product_review', args=[self.candidate.pk])
        for response, status in ((self.client.get(self.url), 200),
                                 (self.client.post(post_url, {'decision': 'bad'}), 400),
                                 (self.client.post(post_url, {'decision': 'defer', 'reason': 'دلیل ساختگی بازبینی',
                                    'expected_review': 999, 'expected_hash': self.candidate.payload_sha256}), 409)):
            with self.subTest(status=status):
                self.assertEqual(response.status_code, status)
                self.assertContains(response, 'رکورد بازبینی یا تصویر آن ناسازگار است', status_code=status)
                self.assertNotContains(response, 'snapshot-canary', status_code=status)
                self.assertNotContains(response, 'reason-canary', status_code=status)
                self.assertEqual(self.rows(response)[self.review.pk].technical_status, 'invalid_record')
        self.assertEqual(ProductCandidateReview.objects.count(), 1)

    def test_invalid_shapes_metadata_and_actor_are_rejected(self):
        from .review_inspection import classify_review
        from types import SimpleNamespace
        original = self.review
        base = dict(candidate_id=original.candidate_id, reviewer_id=original.reviewer_id, decision=original.decision,
                    reason=original.reason, candidate_payload_sha256=original.candidate_payload_sha256,
                    review_snapshot=original.review_snapshot)
        snapshots = [None, [], {}, {**original.review_snapshot, 'extra': 'unexpected'},
                     {**original.review_snapshot, 'staged_by_id': True},
                     {**original.review_snapshot, 'staged_by_id': self.reviewer.pk},
                     {**original.review_snapshot, 'source_rights_attested': False},
                     {**original.review_snapshot, 'source_url': 'http://example.org/not-https'},
                     {**original.review_snapshot, 'source_fields': {'bad': 'shape'}},
                     {**original.review_snapshot, 'source_name': '\ud800'}]
        for snap in snapshots:
            with self.subTest(snapshot=ascii(snap)), self.assertNumQueries(0):
                self.assertEqual(classify_review(SimpleNamespace(**{**base, 'review_snapshot': snap}), self.candidate, True),
                                 ('invalid_record', 'unknown'))
        for key, value in (('candidate_id', True), ('reviewer_id', 0), ('decision', 'bad'), ('reason', 'bad'),
                           ('candidate_payload_sha256', '0' * 64)):
            with self.subTest(key=key):
                self.assertEqual(classify_review(SimpleNamespace(**{**base, key: value}), self.candidate, True),
                                 ('invalid_record', 'unknown'))

    def test_valid_current_change_is_different_invalid_is_unknown(self):
        new_row = {**self.row, 'name_fa': 'نام تغییر یافته ساختگی'}
        ProductCandidate.objects.filter(pk=self.candidate.pk).update(
            source_fields=new_row, payload_sha256=fingerprint(self.candidate.source_name, self.candidate.source_url, new_row))
        response = self.client.get(self.url)
        self.assertEqual(self.rows(response)[self.review.pk].candidate_comparison, 'different')
        self.assertContains(response, 'زمان و علت تفاوت مشخص نیست')
        ProductCandidate.objects.filter(pk=self.candidate.pk).update(payload_sha256='0' * 64)
        response = self.client.get(self.url)
        self.assertEqual(self.rows(response)[self.review.pk].candidate_comparison, 'unknown')
        self.assertContains(response, 'مقایسه نامزد نامشخص است')

    def test_coherently_rewritten_snapshot_can_pass_unkeyed_digest(self):
        snapshot = copy.deepcopy(self.review.review_snapshot)
        snapshot['source_fields']['name_fa'] = 'بازنویسی منسجم ساختگی'
        digest = fingerprint(snapshot['source_name'], snapshot['source_url'], snapshot['source_fields'])
        ProductCandidateReview.objects.filter(pk=self.review.pk).update(review_snapshot=snapshot, candidate_payload_sha256=digest)
        review = self.rows(self.client.get(self.url))[self.review.pk]
        self.assertEqual((review.technical_status, review.candidate_comparison), ('consistent', 'different'))

    def test_classification_is_limited_to_25_recent_reviews(self):
        for _ in range(25):
            ProductCandidateReview.objects.create(candidate=self.candidate, reviewer=self.reviewer, decision='defer',
                reason=self.review.reason, candidate_payload_sha256=self.review.candidate_payload_sha256,
                review_snapshot=self.review.review_snapshot)
        from .review_inspection import classify_review
        with patch('catalog.staff_views.classify_review', wraps=classify_review) as classifier:
            response = self.client.get(self.url)
        self.assertEqual(classifier.call_count, 25)
        self.assertNotIn(self.review.pk, self.rows(response))
        self.assertContains(response, 'حداکثر ۲۵ بازبینی اخیر نمایش داده می‌شود')
