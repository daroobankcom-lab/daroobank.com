"""Unknown persisted statuses must not be presented as valid decisions."""
import io
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.intake import review_product, stage_products
from catalog.models import ProductCandidate, ProductCandidateReview
from catalog.test_intake import make_csv
from pricing.importer import stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import record_preliminary_review
from pricing.test_workflow import csv_bytes


@override_settings(STAFF_PORTAL_ENABLED=True)
class UnknownQueueStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('status-author', is_staff=True)
        cls.reviewer = User.objects.create_user('status-reviewer', is_staff=True)
        for app, model in (('catalog', 'productcandidate'), ('pricing', 'pricecandidate')):
            perms = Permission.objects.filter(content_type__app_label=app)
            cls.author.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'add_{model}']))
            cls.reviewer.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'review_{model}']))
        product_row = dict(source_record_id='status-product', name_fa='نام ساختگی', name_en='',
                           manufacturer='سازنده', strength='1 mg', dosage_form='قرص',
                           package_description='10 عدد', irc='123')
        price_row = dict(source_record_id='status-price', irc='123', manufacturer='سازنده', strength='1 mg',
                         dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
                         category='retail', unit='package', effective_date='', source_published_date='')
        stage_products(io.BytesIO(make_csv([product_row])), 'منبع ساختگی', 'https://example.org/p',
                       actor=cls.author, commit=True, rights_attested=True)
        stage_csv(io.BytesIO(csv_bytes([price_row])), 'منبع ساختگی', 'https://example.org/r',
                  staged_by=cls.author, commit=True, rights_attested=True)
        cls.product = ProductCandidate.objects.get()
        cls.price = PriceCandidate.objects.get()
        cls.product_review = review_product(candidate_id=cls.product.pk, actor=cls.reviewer, decision='defer',
            reason='توضیح ساختگی برای بازبینی محصول', expected_review=0, expected_hash=cls.product.payload_sha256)
        cls.price_review = record_preliminary_review(candidate_id=cls.price.pk, actor=cls.reviewer, decision='defer',
            reason='توضیح ساختگی برای بازبینی قیمت', expected_review=0, expected_product=0, expected_product_hash='')

    def omit_selected_constraints(self):
        config = connection.settings_dict
        if (connection.vendor != 'postgresql' or config.get('ENGINE') != 'daroobank.isolated_postgresql'
                or not re.fullmatch(r'test_daroobank_synthetic_[0-9a-f]{32}', str(config.get('NAME', '')))
                or not connection.in_atomic_block):
            raise RuntimeError('Constraint mutation requires a transactional isolated synthetic test database.')
        with connection.cursor() as cursor:
            # Flush valid deferred foreign-key events before changing the table.
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('ALTER TABLE pricing_pricecandidate DROP CONSTRAINT candidate_suggestion_consistent')
            cursor.execute('ALTER TABLE pricing_pricecandidatereview DROP CONSTRAINT review_product_matches_decision')
            cursor.execute('ALTER TABLE catalog_productcandidatereview DROP CONSTRAINT product_review_valid_decision')

    def test_test_only_constraint_mutation_rolls_back_at_savepoint(self):
        names = (('pricing_pricecandidate', 'candidate_suggestion_consistent'),
                 ('pricing_pricecandidatereview', 'review_product_matches_decision'),
                 ('catalog_productcandidatereview', 'product_review_valid_decision'))
        def present(table, name):
            with connection.cursor() as cursor:
                return name in connection.introspection.get_constraints(cursor, table)
        self.assertTrue(all(present(table, name) for table, name in names))
        with transaction.atomic():
            self.omit_selected_constraints()
            self.assertTrue(all(not present(table, name) for table, name in names))
            transaction.set_rollback(True)
        self.assertTrue(all(present(table, name) for table, name in names))

    def test_unknown_values_are_not_mislabeled_as_unmatched_pending_or_deferred(self):
        self.omit_selected_constraints()
        PriceCandidate.objects.filter(pk=self.price.pk).update(match_status='bad-status')
        PriceCandidateReview.objects.filter(pk=self.price_review.pk).update(decision='bad-review')
        ProductCandidateReview.objects.filter(pk=self.product_review.pk).update(decision='bad-review')
        self.client.force_login(self.reviewer)
        for endpoint in ('staff_products', 'staff_prices'):
            response = self.client.get(reverse(endpoint))
            self.assertContains(response, 'وضعیت بازبینی نامعتبر')
            self.assertNotContains(response, 'بدون بازبینی</span>')
            self.assertNotContains(response, 'bad-review')
            self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        price_queue = self.client.get(reverse('staff_prices'))
        self.assertContains(price_queue, '<span class="staff-badge">وضعیت تطبیق نامعتبر</span>')
        self.assertNotContains(price_queue, 'bad-status')
        for endpoint, pk in (('staff_product_detail', self.product.pk), ('staff_price_detail', self.price.pk)):
            response = self.client.get(reverse(endpoint, args=[pk]))
            self.assertContains(response, 'وضعیت بازبینی نامعتبر')
            self.assertNotContains(response, 'bad-review')
