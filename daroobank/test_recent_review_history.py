"""Synthetic missing-reviewer and bounded history regressions across intake domains."""
import io
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .review_history import recent_reviews_with_reviewers

from catalog.intake import review_product, stage_products
from catalog.models import ProductCandidate, ProductCandidateReview, ProductPresentation
from catalog.test_intake import make_csv
from pricing.importer import stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import product_fingerprint, record_preliminary_review
from pricing.test_workflow import csv_bytes
from sources.models import SourceClaimReview
from sources.services import record_claim, review_claim


@override_settings(STAFF_PORTAL_ENABLED=True)
class RecentReviewHistoryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('history-author', is_staff=True)
        cls.reviewer = User.objects.create_user('history-reviewer', is_staff=True)
        cls.viewer = User.objects.create_user('history-viewer', is_staff=True)
        cls.no_access = User.objects.create_user('history-no-access', is_staff=True)
        for app, entity in [('sources', 'sourceclaim'), ('catalog', 'productcandidate'), ('pricing', 'pricecandidate')]:
            perms = Permission.objects.filter(content_type__app_label=app)
            cls.author.user_permissions.add(*perms.filter(codename__in=[f'view_{entity}', f'add_{entity}']))
            cls.reviewer.user_permissions.add(*perms.filter(codename__in=[f'view_{entity}', f'review_{entity}']))
            cls.viewer.user_permissions.add(perms.get(codename=f'view_{entity}'))
        cls.claim, _ = record_claim(actor=cls.author, data=dict(source_name='منبع ساختگی',
            source_url='https://example.org/source', owner='مالک ساختگی', evidence_url='https://example.org/proof',
            evidence_note='', claims_collection=True, claims_storage=False, claims_publication=False,
            starts_on=None, expires_on=date(2030, 1, 1)))
        row = {'source_record_id': 'synthetic-p', 'name_fa': 'فرآورده ساختگی', 'name_en': 'Synthetic',
               'manufacturer': 'سازنده فرضی', 'strength': '۵ میلی گرم', 'dosage_form': 'قرص',
               'package_description': '۱۰ عدد', 'irc': '۰۰۱۲۳۴'}
        stage_products(io.BytesIO(make_csv([row])), 'منبع ساختگی', 'https://example.org/product',
                       actor=cls.author, commit=True, rights_attested=True)
        cls.candidate = ProductCandidate.objects.get()
        cls.product = ProductPresentation.objects.create(name_fa='تصویر فرآورده ساختگی', manufacturer='سازنده فرضی',
            strength='۵ میلی گرم', dosage_form='قرص', package_description='۱۰ عدد', irc='001234',
            source_name='منبع فرضی', source_url='https://example.org/presentation')
        price = dict(source_record_id='synthetic-price', irc='۰۰۱۲۳۴', manufacturer='سازنده فرضی',
            strength='۵ میلی گرم', dosage_form='قرص', package_description='۱۰ عدد', amount='123', currency='RIAL',
            category='retail', unit='package', effective_date='2026-01-02', source_published_date='')
        stage_csv(io.BytesIO(csv_bytes([price])), 'منبع ساختگی', 'https://example.org/price',
                  commit=True, rights_attested=True, staged_by=cls.author)
        cls.price = PriceCandidate.objects.get()
        cls.reason = 'دلیل محرمانه ساختگی برای آزمون سابقه.'
        cls.source_event = review_claim(actor=cls.reviewer, claim_id=cls.claim.pk, decision='defer',
            reason=cls.reason, expected_review=0, expected_hash=cls.claim.payload_sha256)
        cls.product_event = review_product(actor=cls.reviewer, candidate_id=cls.candidate.pk, decision='defer',
            reason=cls.reason, expected_review=0, expected_hash=cls.candidate.payload_sha256)
        cls.price_event = record_preliminary_review(actor=cls.reviewer, candidate_id=cls.price.pk,
            decision='accept_suggestion', reason=cls.reason, expected_review=0, expected_product=cls.product.pk,
            expected_product_hash=product_fingerprint(cls.product))

    def cases(self):
        return [
            ('source', self.claim, self.source_event, SourceClaimReview, 'staff_source_detail', 'staff_source_review',
             {'decision': 'defer', 'reason': self.reason, 'expected_hash': self.claim.payload_sha256}),
            ('product', self.candidate, self.product_event, ProductCandidateReview, 'staff_product_detail', 'staff_product_review',
             {'decision': 'defer', 'reason': self.reason, 'expected_hash': self.candidate.payload_sha256}),
            ('price', self.price, self.price_event, PriceCandidateReview, 'staff_price_detail', 'staff_price_review',
             {'decision': 'defer', 'reason': self.reason, 'expected_product': 0, 'expected_product_hash': ''}),
        ]

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_missing_reviewer_keeps_latest_row_and_optimistic_version(self):
        for domain, item, event, model, detail, review, data in self.cases():
            with self.subTest(domain=domain):
                try:
                    # Synthetic corruption is restored before deferred FK enforcement.
                    model.objects.filter(pk=event.pk).update(reviewer_id=2_147_483_000)
                    self.client.force_login(self.reviewer)
                    response = self.client.get(reverse(detail, args=[item.pk]))
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(len(response.context['reviews']), 1)
                    self.assertEqual(response.context['review_form'].initial['expected_review'], event.pk)
                    self.assertContains(response, 'حساب بازبین در دسترس نیست')
                    self.assertNotContains(response, self.reason)
                    if domain == 'price':
                        self.assertNotContains(response, 'فرآورده هنگام بازبینی:')
                    self.assert_private(response)
                    stale = self.client.post(reverse(review, args=[item.pk]), {**data, 'expected_review': 0})
                    self.assertEqual(stale.status_code, 409)
                    self.assertEqual(model.objects.count(), 1)
                    self.assertContains(stale, 'حساب بازبین در دسترس نیست', status_code=409)
                    self.assert_private(stale)
                    success = self.client.post(reverse(review, args=[item.pk]), {**data, 'expected_review': event.pk})
                    self.assertEqual(success.status_code, 302)
                    self.assertEqual(model.objects.count(), 2)
                finally:
                    model.objects.filter(pk=event.pk).update(reviewer_id=self.reviewer.pk)

    def test_older_missing_reviewer_does_not_hide_newest_valid_history(self):
        for domain, item, event, model, detail, _, _ in self.cases():
            with self.subTest(domain=domain):
                values = {field.attname: getattr(event, field.attname) for field in model._meta.concrete_fields
                          if field.name not in ('id', 'created_at')}
                latest = model.objects.create(**{**values, 'reason': 'دلیل دوم ساختگی برای آزمایش.'})
                try:
                    model.objects.filter(pk=event.pk).update(reviewer_id=2_147_483_000)
                    self.client.force_login(self.reviewer)
                    response = self.client.get(reverse(detail, args=[item.pk]))
                    self.assertEqual([row.pk for row in response.context['reviews']], [latest.pk, event.pk])
                    self.assertEqual(response.context['review_form'].initial['expected_review'], latest.pk)
                    self.assertContains(response, 'دلیل دوم ساختگی برای آزمایش.')
                    self.assertNotContains(response, self.reason)
                    self.assertContains(response, 'حساب بازبین در دسترس نیست')
                finally:
                    model.objects.filter(pk=event.pk).update(reviewer_id=self.reviewer.pk)

    def test_helper_clears_reviewer_join_and_has_bounded_lookup(self):
        with CaptureQueriesContext(connection) as queries:
            rows = recent_reviews_with_reviewers(self.claim.reviews.select_related('reviewer'))
        self.assertEqual(len(queries), 2)
        self.assertNotIn(' JOIN ', queries[0]['sql'].upper())
        self.assertIn('LIMIT 25', queries[0]['sql'].upper())
        self.assertEqual(rows[0].pk, self.source_event.pk)
        self.assertEqual(rows[0].display_reviewer.pk, self.reviewer.pk)
        with CaptureQueriesContext(connection) as empty:
            self.assertEqual(recent_reviews_with_reviewers(self.claim.reviews.none()), [])
        self.assertEqual(len(empty), 0)

    def test_account_lookup_is_a_separate_non_snapshot_read(self):
        def update_between_reads():
            SourceClaimReview.objects.filter(pk=self.source_event.pk).update(reviewer_id=2_147_483_000)
            return get_user_model()
        try:
            with patch('daroobank.review_history.get_user_model', side_effect=update_between_reads):
                rows = recent_reviews_with_reviewers(self.claim.reviews.all())
            self.assertEqual(rows[0].display_reviewer.pk, self.reviewer.pk)
            self.assertEqual(SourceClaimReview.objects.get(pk=self.source_event.pk).reviewer_id, 2_147_483_000)
            self.assertIsNone(recent_reviews_with_reviewers(self.claim.reviews.all())[0].display_reviewer)
        finally:
            SourceClaimReview.objects.filter(pk=self.source_event.pk).update(reviewer_id=self.reviewer.pk)

    def test_existing_reviewer_detail_and_access_remain_unchanged(self):
        for domain, item, event, _, detail, _, _ in self.cases():
            with self.subTest(domain=domain):
                path = reverse(detail, args=[item.pk])
                self.client.logout()
                self.assertEqual(self.client.get(path).status_code, 302)
                self.client.force_login(self.no_access)
                denied = self.client.get(path)
                self.assertEqual(denied.status_code, 403)
                self.assert_private(denied)
                self.client.force_login(self.viewer)
                response = self.client.get(path)
                self.assertContains(response, self.reason)
                self.assertContains(response, self.reviewer.get_username())
                self.assertNotContains(response, 'حساب بازبین در دسترس نیست')
                self.assert_private(response)

    def test_capped_history_does_not_issue_per_reviewer_queries(self):
        for domain, item, event, model, detail, _, _ in self.cases():
            with self.subTest(domain=domain):
                self.client.force_login(self.viewer)
                path = reverse(detail, args=[item.pk])
                self.client.get(path)
                with CaptureQueriesContext(connection) as one:
                    self.client.get(path)
                values = {field.attname: getattr(event, field.attname) for field in model._meta.concrete_fields
                          if field.name not in ('id', 'created_at')}
                model.objects.bulk_create([model(**values) for _ in range(25)])
                with CaptureQueriesContext(connection) as many:
                    response = self.client.get(path)
                self.assertEqual(len(one), len(many))
                self.assertEqual(len(response.context['reviews']), 25)
                self.assertEqual([r.pk for r in response.context['reviews']],
                                 list(model.objects.order_by('-pk').values_list('pk', flat=True)[:25]))
                self.assertContains(response, 'حداکثر ۲۵ بازبینی اخیر نمایش داده می‌شود')
