"""Bounded, permission-scoped synthetic candidate-review scans."""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog.intake import review_product, stage_products
from catalog.models import ProductCandidate, ProductCandidateReview
from catalog.test_intake import make_csv
from pricing.importer import stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import record_preliminary_review
from pricing.test_workflow import csv_bytes


@override_settings(STAFF_PORTAL_ENABLED=True)
class CandidateReviewInspectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('scan-synthetic-author', is_staff=True)
        cls.reviewer = User.objects.create_user('scan-synthetic-reviewer', is_staff=True)
        cls.viewer = User.objects.create_user('scan-synthetic-viewer', is_staff=True)
        cls.price_only = User.objects.create_user('scan-price-only', is_staff=True)
        cls.nonstaff = User.objects.create_user('scan-nonstaff', is_staff=False)
        for app, model in (('catalog', 'productcandidate'), ('pricing', 'pricecandidate')):
            perms = Permission.objects.filter(content_type__app_label=app)
            cls.author.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'add_{model}']))
            cls.reviewer.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'review_{model}']))
            cls.viewer.user_permissions.add(*perms.filter(codename=f'view_{model}'))
            cls.nonstaff.user_permissions.add(*perms.filter(codename=f'view_{model}'))
        cls.price_only.user_permissions.add(Permission.objects.get(content_type__app_label='pricing', codename='view_pricecandidate'))
        product = dict(source_record_id='scan-product', name_fa='فرآورده ساختگی', name_en='',
                       manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        price = dict(source_record_id='scan-price', irc='001', manufacturer='سازنده فرضی', strength='1 mg',
                     dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
                     unit='package', effective_date='', source_published_date='')
        stage_products(io.BytesIO(make_csv([product])), 'منبع ساختگی', 'https://example.org/scan-product',
                       actor=cls.author, commit=True, rights_attested=True)
        stage_csv(io.BytesIO(csv_bytes([price])), 'منبع ساختگی', 'https://example.org/scan-price',
                  staged_by=cls.author, commit=True, rights_attested=True)
        cls.product, cls.price = ProductCandidate.objects.get(), PriceCandidate.objects.get()
        cls.product_event = review_product(actor=cls.reviewer, candidate_id=cls.product.pk, decision='defer',
            reason='private-product-scan-canary دلیل ساختگی', expected_review=0, expected_hash=cls.product.payload_sha256)
        cls.price_event = record_preliminary_review(actor=cls.reviewer, candidate_id=cls.price.pk, decision='defer',
            reason='private-price-scan-canary دلیل ساختگی', expected_review=0, expected_product=0, expected_product_hash='')

    def cases(self):
        return (('product', self.product, self.product_event, ProductCandidateReview, 'staff_product_review_inspection', 'staff_product_detail'),
                ('price', self.price, self.price_event, PriceCandidateReview, 'staff_price_review_inspection', 'staff_price_detail'))

    def test_paginated_filter_is_applied_only_after_bounded_scan(self):
        from .candidate_review_scan import BATCH_SIZE, inspect_reviews
        self.assertEqual(BATCH_SIZE, 50)
        for domain, candidate, event, model, route, detail in self.cases():
            with self.subTest(domain=domain):
                # One inconsistent review, followed by 50 consistent rows.
                model.objects.filter(pk=event.pk).update(review_snapshot={'canary': 'private-snapshot-canary'})
                inserted = [model.objects.create(candidate=candidate, reviewer=self.reviewer, decision='defer',
                            reason=event.reason, candidate_payload_sha256=event.candidate_payload_sha256,
                            review_snapshot=event.review_snapshot) for _ in range(50)]
                self.client.force_login(self.viewer)
                path = reverse(route, args=[candidate.pk])
                response = self.client.get(path, {'category': 'consistent'})
                report = response.context['report']
                self.assertEqual(report['scanned'], 50)
                self.assertEqual(len(report['rows']), 49)
                self.assertEqual(report['next_after'], inserted[-2].pk)
                self.assertNotContains(response, 'private-snapshot-canary')
                self.assertNotContains(response, 'private-product-scan-canary')
                self.assertNotContains(response, 'private-price-scan-canary')
                self.assertNotContains(response, self.reviewer.username)
                self.assertContains(response, 'فیلتر فقط بر همان بخش اعمال می‌شود')
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                follow = self.client.get(path, {'after': report['next_after'], 'category': 'consistent'}).context['report']
                self.assertEqual(follow['scanned'], 1)
                self.assertEqual([row['id'] for row in follow['rows']], [inserted[-1].pk])
                self.assertIsNone(follow['next_after'])
                filtered = inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk, category='invalid_record')
                self.assertEqual([row['id'] for row in filtered['rows']], [event.pk])
                self.assertEqual(filtered['rows'][0]['comparison'], 'unknown')
                self.assertContains(self.client.get(reverse(detail, args=[candidate.pk])), f'href="{path}"')

    def test_empty_filtered_page_can_continue(self):
        from .candidate_review_scan import inspect_reviews
        for domain, candidate, event, model, route, detail in self.cases():
            with self.subTest(domain=domain):
                for _ in range(50):
                    model.objects.create(candidate=candidate, reviewer=self.reviewer, decision='defer', reason=event.reason,
                        candidate_payload_sha256=event.candidate_payload_sha256, review_snapshot=event.review_snapshot)
                other = inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk, category='invalid_record')
                self.assertEqual(other['rows'], [])
                self.assertEqual(other['scanned'], 50)
                self.assertIsNotNone(other['next_after'])
                last = inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk, after=other['next_after'])
                self.assertEqual(last['scanned'], 1)

    def test_cross_candidate_reviews_are_excluded_and_sql_fetch_is_bounded(self):
        from .candidate_review_scan import inspect_reviews
        other_product = dict(source_record_id='other-product', name_fa='داده ساختگی دیگر', name_en='',
            manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        other_price = dict(source_record_id='other-price', irc='001', manufacturer='سازنده فرضی', strength='1 mg',
            dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
            unit='package', effective_date='', source_published_date='')
        stage_products(io.BytesIO(make_csv([other_product])), 'منبع ساختگی', 'https://example.org/other-product',
                       actor=self.author, commit=True, rights_attested=True)
        stage_csv(io.BytesIO(csv_bytes([other_price])), 'منبع ساختگی', 'https://example.org/other-price',
                  staged_by=self.author, commit=True, rights_attested=True)
        other = {'product': ProductCandidate.objects.get(source_record_id='other-product'),
                 'price': PriceCandidate.objects.get(source_record_id='other-price')}
        for domain, candidate, event, model, route, detail in self.cases():
            with self.subTest(domain=domain):
                other_event = model.objects.create(candidate=other[domain], reviewer=self.reviewer, decision='defer',
                    reason=event.reason, candidate_payload_sha256=event.candidate_payload_sha256,
                    review_snapshot=event.review_snapshot)
                with CaptureQueriesContext(connection) as captured:
                    result = inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)
                self.assertEqual([item['id'] for item in result['rows']], [event.pk])
                self.assertNotIn(other_event.pk, [item['id'] for item in result['rows']])
                review_sql = [q['sql'] for q in captured.captured_queries
                              if f'FROM "{model._meta.db_table}"' in q['sql']]
                self.assertEqual(len(review_sql), 1)
                self.assertIn('LIMIT 51', review_sql[0])
                self.assertNotIn(' JOIN ', review_sql[0].upper())

    def test_separate_reads_can_compare_against_stale_parent(self):
        from . import candidate_review_scan as scan
        for domain, candidate, event, model, route, detail in self.cases():
            with self.subTest(domain=domain):
                parent_model, review_model, validate, classify, permission = scan._DOMAINS[domain]
                def validate_then_update(stale):
                    valid = validate(stale)
                    parent_model.objects.filter(pk=stale.pk).update(payload_sha256='0' * 64)
                    return valid
                with patch.dict(scan._DOMAINS, {domain: (parent_model, review_model, validate_then_update, classify, permission)}):
                    result = scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)
                self.assertEqual(result['rows'][0]['comparison'], 'same')
                self.assertEqual(scan.inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)['rows'][0]['comparison'], 'unknown')
                parent_model.objects.filter(pk=candidate.pk).update(payload_sha256=candidate.payload_sha256)

    def test_current_candidate_invalid_or_stager_missing_gives_unknown_comparison(self):
        from .candidate_review_scan import inspect_reviews
        for domain, candidate, event, model, route, detail in self.cases():
            with self.subTest(domain=domain):
                first = inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)
                self.assertEqual(first['rows'][0]['comparison'], 'same')
                candidate.__class__.objects.filter(pk=candidate.pk).update(payload_sha256='0' * 64)
                changed = inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)
                self.assertEqual(changed['rows'][0]['comparison'], 'unknown')
                candidate.__class__.objects.filter(pk=candidate.pk).update(payload_sha256=candidate.payload_sha256)
                with patch('daroobank.candidate_review_scan.current_account_ids', return_value=set()):
                    absent = inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk)
                self.assertEqual(absent['rows'][0]['comparison'], 'unknown')
                self.assertEqual(absent['rows'][0]['status'], 'consistent')

    def test_scoped_permissions_and_read_only_methods(self):
        from .candidate_review_scan import inspect_reviews
        for domain, candidate, event, model, route, detail in self.cases():
            with self.subTest(domain=domain):
                path = reverse(route, args=[candidate.pk])
                self.client.logout()
                self.assertEqual(self.client.get(path).status_code, 302)
                self.client.force_login(self.nonstaff)
                self.assertEqual(self.client.get(path).status_code, 403)
                for actor in (None, self.nonstaff):
                    with self.assertRaises(PermissionDenied):
                        inspect_reviews(actor=actor, domain=domain, candidate_id=candidate.pk)
                self.client.force_login(self.price_only)
                self.assertEqual(self.client.get(path).status_code, 403 if domain == 'product' else 200)
                self.client.force_login(self.viewer)
                self.assertEqual(self.client.head(path).status_code, 200)
                self.assertEqual(self.client.post(path).status_code, 405)
                with self.settings(STAFF_PORTAL_ENABLED=False):
                    self.assertEqual(self.client.get(path).status_code, 404)
                self.assertEqual(model.objects.count(), 1)

    def test_group_view_permission_and_invalid_input_are_private_and_not_echoed(self):
        group = Group.objects.create(name='synthetic-review-scan-viewers')
        group.permissions.add(*Permission.objects.filter(content_type__app_label__in=['catalog', 'pricing'],
                              codename__in=['view_productcandidate', 'view_pricecandidate']))
        actor = get_user_model().objects.create_user('scan-group', is_staff=True)
        actor.groups.add(group)
        self.client.force_login(actor)
        for domain, candidate, event, model, route, detail in self.cases():
            with self.subTest(domain=domain):
                path = reverse(route, args=[candidate.pk])
                self.assertEqual(self.client.get(path, {'after': '٠۰0'}).status_code, 200)
                for params in ({'after': 'secret-canary'}, {'after': '9223372036854775808'},
                               {'after': '-1'}, {'after': '1.0'}, {'category': 'secret-canary'}):
                    response = self.client.get(path, params)
                    self.assertEqual(response.status_code, 400)
                    self.assertNotContains(response, 'secret-canary', status_code=400)
                    self.assertContains(response, f'href="{path}"', status_code=400)
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                self.assertEqual(self.client.get(reverse(route, args=[999999999]), {'after': 'bad'}).status_code, 404)

    def test_service_input_validation_and_no_queries_before_bad_input(self):
        from .candidate_review_scan import InvalidCandidateReviewScan, ReviewScanNotFound, inspect_reviews
        # Warm Django's per-user permission cache so the query assertion measures scan inputs.
        self.viewer.has_perm('catalog.view_productcandidate')
        for domain, candidate, event, model, route, detail in self.cases():
            self.viewer.has_perm(f'{"catalog" if domain == "product" else "pricing"}.view_{"productcandidate" if domain == "product" else "pricecandidate"}')
            for after in (True, -1, '1', 2**63):
                with self.subTest(domain=domain, after=after), self.assertNumQueries(0), self.assertRaises(InvalidCandidateReviewScan):
                    inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk, after=after)
            for category in (None, [], 'secret'):
                with self.subTest(domain=domain, category=category), self.assertNumQueries(0), self.assertRaises(InvalidCandidateReviewScan):
                    inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate.pk, category=category)
            for candidate_id in (True, 0, 2**63):
                with self.subTest(domain=domain, candidate_id=candidate_id), self.assertNumQueries(0), self.assertRaises(ReviewScanNotFound):
                    inspect_reviews(actor=self.viewer, domain=domain, candidate_id=candidate_id)
