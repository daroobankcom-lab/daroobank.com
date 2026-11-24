"""Synthetic price review history is advisory and must not display malformed snapshots."""
import copy
import hashlib
import io
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.models import ProductPresentation
from .importer import stage_csv
from .models import PriceCandidate, PriceCandidateReview
from .reviews import product_fingerprint, record_preliminary_review
from .test_workflow import csv_bytes


@override_settings(STAFF_PORTAL_ENABLED=True)
class PriceReviewSnapshotConsistencyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.stager = User.objects.create_user('snapshot-price-stager', is_staff=True)
        cls.reviewer = User.objects.create_user('snapshot-price-reviewer', is_staff=True)
        cls.viewer = User.objects.create_user('snapshot-price-viewer', is_staff=True)
        perms = Permission.objects.filter(content_type__app_label='pricing')
        cls.stager.user_permissions.add(*perms.filter(codename__in=['view_pricecandidate', 'add_pricecandidate']))
        cls.reviewer.user_permissions.add(*perms.filter(codename__in=['view_pricecandidate', 'review_pricecandidate']))
        cls.viewer.user_permissions.add(perms.get(codename='view_pricecandidate'))
        cls.product = ProductPresentation.objects.create(name_fa='فرآورده ساختگی تاریخچه', manufacturer='سازنده فرضی',
            strength='1 mg', dosage_form='قرص', package_description='10 عدد', irc='001',
            source_name='منبع فرضی', source_url='https://example.org/product')
        row = dict(source_record_id='history-test', irc='001', manufacturer='سازنده فرضی', strength='1 mg',
                   dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
                   unit='package', effective_date='', source_published_date='')
        stage_csv(io.BytesIO(csv_bytes([row])), 'منبع ساختگی', 'https://example.org/price',
                  commit=True, rights_attested=True, staged_by=cls.stager)
        cls.candidate = PriceCandidate.objects.get()
        cls.accepted = record_preliminary_review(actor=cls.reviewer, candidate_id=cls.candidate.pk,
            decision='accept_suggestion', reason='بازبینی ساختگی قیمت برای بررسی', expected_review=0,
            expected_product=cls.product.pk, expected_product_hash=product_fingerprint(cls.product))
        cls.deferred = record_preliminary_review(actor=cls.reviewer, candidate_id=cls.candidate.pk,
            decision='defer', reason='بازبینی ساختگی برای پیگیری', expected_review=cls.accepted.pk,
            expected_product=0, expected_product_hash='')

    def setUp(self):
        self.client.force_login(self.viewer)
        self.url = reverse('staff_price_detail', args=[self.candidate.pk])

    def by_id(self, response):
        return {review.pk: review for review in response.context['reviews']}

    def test_real_writer_snapshots_are_consistent_and_compare_to_current_candidate(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        for review in self.by_id(response).values():
            self.assertEqual(review.technical_status, 'consistent')
            self.assertEqual(review.candidate_comparison, 'same')
        self.assertContains(response, 'فرآورده ساختگی تاریخچه')
        self.assertContains(response, 'این مقایسه تأیید اصالت یا قیمت نیست')
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    def test_classifier_is_pure_and_reject_writer_snapshot_is_supported(self):
        from .review_inspection import classify_review
        rejected = record_preliminary_review(actor=self.reviewer, candidate_id=self.candidate.pk,
            decision='reject', reason='رد ساختگی برای بررسی بیشتر', expected_review=self.deferred.pk,
            expected_product=0, expected_product_hash='')
        with self.assertNumQueries(0):
            self.assertEqual(classify_review(rejected, self.candidate, True), ('consistent', 'same'))
            self.assertEqual(classify_review(rejected, self.candidate, False), ('consistent', 'unknown'))
        response = self.client.get(self.url)
        self.assertContains(response, 'رد نامزد')
        self.assertContains(response, 'رد ساختگی برای بررسی بیشتر')

    def test_coherent_rewrite_can_pass_unkeyed_checks(self):
        snapshot = copy.deepcopy(self.deferred.review_snapshot)
        snapshot['source_fields']['amount'] = '101'
        snapshot['amount_rial'] = 101
        payload = {'source_name': snapshot['source_name'], 'fields': snapshot['source_fields']}
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                           separators=(',', ':')).encode('utf-8')).hexdigest()
        PriceCandidateReview.objects.filter(pk=self.deferred.pk).update(review_snapshot=snapshot,
                                                                         candidate_payload_sha256=digest)
        review = self.by_id(self.client.get(self.url))[self.deferred.pk]
        self.assertEqual(review.technical_status, 'consistent')
        self.assertEqual(review.candidate_comparison, 'different')

    def test_corrupt_snapshot_is_suppressed_but_other_history_remains(self):
        snapshot = copy.deepcopy(self.accepted.review_snapshot)
        snapshot['product']['name_fa'] = 'price-history-canary'
        PriceCandidateReview.objects.filter(pk=self.accepted.pk).update(review_snapshot=snapshot,
            reason='price-reason-canary برای آزمایش')
        response = self.client.get(self.url)
        self.assertEqual(self.by_id(response)[self.accepted.pk].technical_status, 'invalid_record')
        self.assertEqual(self.by_id(response)[self.deferred.pk].technical_status, 'consistent')
        self.assertContains(response, 'رکورد بازبینی یا تصویر آن ناسازگار است')
        self.assertNotContains(response, 'price-history-canary')
        self.assertNotContains(response, 'price-reason-canary')
        self.assertContains(response, 'بازبینی ساختگی برای پیگیری')

    def test_malformed_nested_values_return_fixed_invalid_status_without_queries(self):
        from types import SimpleNamespace
        from .review_inspection import classify_review
        values = (None, False, True, 0, [], {}, 'unexpected', '\ud800')
        original = self.accepted
        base = dict(candidate_id=original.candidate_id, reviewer_id=original.reviewer_id,
                    decision=original.decision, reason=original.reason,
                    candidate_payload_sha256=original.candidate_payload_sha256,
                    product_identity_sha256=original.product_identity_sha256,
                    reviewed_product_id=original.reviewed_product_id,
                    review_snapshot=copy.deepcopy(original.review_snapshot))
        with self.assertNumQueries(0):
            for key in ('source_name', 'source_url', 'source_record_id', 'source_fields', 'amount_rial',
                        'source_rights_attested', 'staged_by_id', 'product'):
                for value in values:
                    if key == 'source_rights_attested' and value is True:
                        continue
                    mutated = copy.deepcopy(base)
                    mutated['review_snapshot'][key] = value
                    with self.subTest(key=key, value=ascii(value)):
                        self.assertEqual(classify_review(SimpleNamespace(**mutated), self.candidate, True),
                                         ('invalid_record', 'unknown'))
            for key in original.review_snapshot['product']:
                for value in values:
                    mutated = copy.deepcopy(base)
                    mutated['review_snapshot']['product'][key] = value
                    with self.subTest(product_key=key, value=ascii(value)):
                        self.assertEqual(classify_review(SimpleNamespace(**mutated), self.candidate, True),
                                         ('invalid_record', 'unknown'))

    def test_candidate_change_is_different_not_proof_of_tampering_and_invalid_is_unknown(self):
        # Price candidate hashes do not include source_url; comparing snapshots does.
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(source_url='https://example.org/other')
        response = self.client.get(self.url)
        self.assertEqual(self.by_id(response)[self.accepted.pk].technical_status, 'consistent')
        self.assertEqual(self.by_id(response)[self.accepted.pk].candidate_comparison, 'different')
        self.assertContains(response, 'تصویر نامزد با وضعیت فعلی متفاوت است')
        PriceCandidate.objects.filter(pk=self.candidate.pk).update(amount_rial=999)
        response = self.client.get(self.url)
        self.assertEqual(self.by_id(response)[self.accepted.pk].candidate_comparison, 'unknown')
        self.assertContains(response, 'مقایسه نامزد نامشخص است')

    def test_snapshot_shape_and_amount_actor_and_product_hash_are_checked(self):
        original = copy.deepcopy(self.accepted.review_snapshot)
        mutations = [
            {**original, 'extra': 'unexpected'},
            {**original, 'amount_rial': 101},
            {**original, 'amount_rial': True},
            {**original, 'source_rights_attested': False},
            {**original, 'staged_by_id': self.reviewer.pk},
            {**original, 'source_url': 'http://example.org/not-https'},
            {**original, 'source_fields': {**original['source_fields'], 'amount': 'invalid'}},
            {**original, 'product': {**original['product'], 'id': self.product.pk + 100}},
            {**original, 'product': {**original['product'], 'strength': 'different'}},
            {**original, 'product': None},
        ]
        for snapshot in mutations:
            with self.subTest(snapshot=snapshot):
                PriceCandidateReview.objects.filter(pk=self.accepted.pk).update(review_snapshot=snapshot)
                response = self.client.get(self.url)
                review = self.by_id(response)[self.accepted.pk]
                self.assertEqual(review.technical_status, 'invalid_record')
                self.assertEqual(review.candidate_comparison, 'unknown')
        PriceCandidateReview.objects.filter(pk=self.accepted.pk).update(review_snapshot=original,
                                                                         product_identity_sha256='0' * 64)
        self.assertEqual(self.by_id(self.client.get(self.url))[self.accepted.pk].technical_status, 'invalid_record')

    def test_matching_product_fields_are_checked_even_if_product_hash_is_recomputed(self):
        snapshot = copy.deepcopy(self.accepted.review_snapshot)
        snapshot['product']['strength'] = '2 mg'
        product_hash = hashlib.sha256(json.dumps(snapshot['product'], sort_keys=True, ensure_ascii=False,
                                                  separators=(',', ':')).encode('utf-8')).hexdigest()
        PriceCandidateReview.objects.filter(pk=self.accepted.pk).update(review_snapshot=snapshot,
                                                                         product_identity_sha256=product_hash)
        self.assertEqual(self.by_id(self.client.get(self.url))[self.accepted.pk].technical_status, 'invalid_record')

    def test_missing_current_stager_makes_candidate_comparison_unknown(self):
        from daroobank.account_checks import current_accounts
        def reviewers_only(ids, **kwargs):
            return {key: value for key, value in current_accounts(ids, **kwargs).items() if key != self.stager.pk}
        with patch('pricing.staff_views.current_accounts', side_effect=reviewers_only):
            response = self.client.get(self.url)
        self.assertEqual(self.by_id(response)[self.accepted.pk].technical_status, 'consistent')
        self.assertEqual(self.by_id(response)[self.accepted.pk].candidate_comparison, 'unknown')
        self.assertContains(response, 'مقایسه نامزد نامشخص است')

    def test_invalid_history_hidden_on_bad_and_stale_review_responses(self):
        snapshot = {**self.deferred.review_snapshot, 'unexpected': 'private-history-canary'}
        PriceCandidateReview.objects.filter(pk=self.deferred.pk).update(review_snapshot=snapshot,
                                                                       reason='private-reason-canary این داده نامعتبر است')
        self.client.force_login(self.reviewer)
        url = reverse('staff_price_review', args=[self.candidate.pk])
        for data, status in (({'decision': 'invalid'}, 400),
                             ({'decision': 'defer', 'reason': 'توضیح ساختگی برای بازبینی', 'expected_review': 0,
                               'expected_product': 0, 'expected_product_hash': ''}, 409)):
            with self.subTest(status=status):
                response = self.client.post(url, data)
                self.assertEqual(response.status_code, status)
                self.assertNotContains(response, 'private-history-canary', status_code=status)
                self.assertNotContains(response, 'private-reason-canary', status_code=status)
                self.assertContains(response, 'رکورد بازبینی یا تصویر آن ناسازگار است', status_code=status)
                self.assertEqual(PriceCandidateReview.objects.count(), 2)

    def test_only_the_recent_bounded_history_is_classified(self):
        for _ in range(27):
            PriceCandidateReview.objects.create(candidate=self.candidate, reviewer=self.reviewer,
                decision='defer', reason=self.deferred.reason, candidate_payload_sha256=self.deferred.candidate_payload_sha256,
                product_identity_sha256='', review_snapshot=self.deferred.review_snapshot)
        from .review_inspection import classify_review
        with patch('pricing.staff_views.classify_review', wraps=classify_review) as classify:
            response = self.client.get(self.url)
        self.assertEqual(len(response.context['reviews']), 25)
        self.assertEqual(classify.call_count, 25)
        self.assertContains(response, 'حداکثر ۲۵ بازبینی اخیر')
