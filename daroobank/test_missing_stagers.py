"""Selected synthetic missing-stager scenarios for product and price triage."""
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from catalog.comparisons import valid_candidate as valid_product
from catalog.intake import ReviewConflict as ProductConflict, review_product, stage_products
from catalog.models import ProductCandidate, ProductCandidateReview, ProductPresentation
from catalog.test_intake import make_csv
from pricing.comparisons import valid_candidate as valid_price
from pricing.importer import stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import ReviewConflict as PriceConflict, product_fingerprint, record_preliminary_review
from pricing.test_workflow import csv_bytes
from ingestion.receipts import stage_price_with_receipt, stage_product_with_receipt, manifest_context
from ingestion.manifest_inspection import inspect_manifest


PRODUCT_ROW = {'source_record_id': 'missing-stager-product', 'name_fa': 'فرآورده ساختگی', 'name_en': '',
               'manufacturer': 'سازنده فرضی', 'strength': '۵ میلی گرم', 'dosage_form': 'قرص',
               'package_description': '۱۰ عدد', 'irc': '۰۰۱۲۳۴'}
PRICE_ROW = dict(source_record_id='missing-stager-price', irc='۰۰۱۲۳۴', manufacturer='سازنده فرضی',
                 strength='۵ میلی گرم', dosage_form='قرص', package_description='۱۰ عدد', amount='123', currency='RIAL',
                 category='retail', unit='package', effective_date='2026-01-02', source_published_date='')
REASON = 'این داده ساختگی برای آزمایش بازبینی است.'
MISSING = 2_147_483_000  # within the test auth_user integer PK column


def build_synthetic():
    User = get_user_model()
    author = User.objects.create_user('stager-author', is_staff=True)
    reviewer = User.objects.create_user('stager-reviewer', is_staff=True)
    viewer = User.objects.create_user('stager-viewer', is_staff=True)
    unauthorized = User.objects.create_user('stager-unauthorized', is_staff=True)
    for app, entity in [('catalog', 'productcandidate'), ('pricing', 'pricecandidate')]:
        perms = Permission.objects.filter(content_type__app_label=app)
        author.user_permissions.add(*perms.filter(codename__in=[f'view_{entity}', f'add_{entity}', f'review_{entity}']))
        reviewer.user_permissions.add(*perms.filter(codename__in=[f'view_{entity}', f'review_{entity}']))
        viewer.user_permissions.add(perms.get(codename=f'view_{entity}'))
    stage_products(io.BytesIO(make_csv([PRODUCT_ROW])), 'منبع ساختگی', 'https://example.org/product',
                   actor=author, commit=True, rights_attested=True)
    candidate = ProductCandidate.objects.get()
    product = ProductPresentation.objects.create(name_fa='فرآورده مرجع ساختگی', manufacturer='سازنده فرضی',
        strength='۵ میلی گرم', dosage_form='قرص', package_description='۱۰ عدد', irc='001234',
        source_name='منبع ساختگی', source_url='https://example.org/presentation')
    stage_csv(io.BytesIO(csv_bytes([PRICE_ROW])), 'منبع ساختگی', 'https://example.org/price',
              commit=True, rights_attested=True, staged_by=author)
    price = PriceCandidate.objects.get()
    return author, reviewer, viewer, unauthorized, candidate, product, price


@override_settings(STAFF_PORTAL_ENABLED=True)
class MissingStagerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        (cls.author, cls.reviewer, cls.viewer, cls.unauthorized, cls.candidate,
         cls.product, cls.price) = build_synthetic()

    def cases(self):
        return [
            ('product', self.candidate, ProductCandidate, ProductCandidateReview, review_product, ProductConflict,
             'staff_product_detail', 'staff_product_review', 'staff_products',
             {'decision': 'defer', 'reason': REASON, 'expected_review': 0, 'expected_hash': self.candidate.payload_sha256}),
            ('price', self.price, PriceCandidate, PriceCandidateReview, record_preliminary_review, PriceConflict,
             'staff_price_detail', 'staff_price_review', 'staff_prices',
             {'decision': 'defer', 'reason': REASON, 'expected_review': 0, 'expected_product': 0, 'expected_product_hash': ''}),
        ]

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_missing_stager_visible_but_writers_conflict(self):
        for domain, item, model, events, service, conflict, detail, review, queue, data in self.cases():
            with self.subTest(domain=domain):
                try:
                    # PostgreSQL defers these FKs; restore before transaction end.
                    model.objects.filter(pk=item.pk).update(staged_by_id=MISSING)
                    with self.assertRaises(conflict):
                        service(actor=self.reviewer, candidate_id=item.pk, **data)
                    self.assertFalse(events.objects.exists())
                    self.client.force_login(self.reviewer)
                    response = self.client.get(reverse(detail, args=[item.pk]))
                    self.assertEqual(response.status_code, 200)
                    self.assertContains(response, 'حساب ثبت‌کننده در دسترس نیست')
                    self.assertNotContains(response, 'ثبت بازبینی اولیه')
                    self.assert_private(response)
                    self.assertContains(response, 'وجود حساب ثبت‌کننده نامزدها در این مقایسه بررسی نمی‌شود')
                    listing = self.client.get(reverse(queue))
                    self.assertEqual(listing.context['page'].paginator.count, 1)
                    self.assertContains(listing, reverse(detail, args=[item.pk]))
                    self.assertContains(listing, 'وجود حساب ثبت‌کننده در این فهرست بررسی نمی‌شود')
                    response = self.client.post(reverse(review, args=[item.pk]), data)
                    self.assertEqual(response.status_code, 409)
                    self.assertContains(response, 'حساب ثبت‌کننده در دسترس نیست', status_code=409)
                    self.assert_private(response)
                    self.assertFalse(events.objects.exists())
                    self.client.force_login(self.unauthorized)
                    self.assertEqual(self.client.get(reverse(detail, args=[item.pk])).status_code, 403)
                    with self.assertRaises(PermissionDenied):
                        service(actor=self.viewer, candidate_id=item.pk, **data)
                finally:
                    model.objects.filter(pk=item.pk).update(staged_by_id=self.author.pk)

    def test_null_price_stager_remains_a_conflict(self):
        PriceCandidate.objects.filter(pk=self.price.pk).update(staged_by=None)
        data = self.cases()[1][-1]
        with self.assertRaises(PriceConflict):
            record_preliminary_review(actor=self.reviewer, candidate_id=self.price.pk, **data)
        self.client.force_login(self.reviewer)
        detail = self.client.get(reverse('staff_price_detail', args=[self.price.pk]))
        self.assertContains(detail, 'ثبت‌کننده احرازشده ندارد')
        self.assertNotContains(detail, 'ثبت بازبینی اولیه')
        self.assertEqual(self.client.post(reverse('staff_price_review', args=[self.price.pk]), data).status_code, 409)
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_all_decisions_fail_for_missing_nonzero_account(self):
        try:
            ProductCandidate.objects.filter(pk=self.candidate.pk).update(staged_by_id=MISSING)
            PriceCandidate.objects.filter(pk=self.price.pk).update(staged_by_id=MISSING)
            for decision in ('defer', 'reject', 'further_review'):
                with self.subTest(domain='product', decision=decision), self.assertRaises(ProductConflict):
                    review_product(actor=self.reviewer, candidate_id=self.candidate.pk, decision=decision,
                        reason=REASON, expected_review=0, expected_hash=self.candidate.payload_sha256)
            for decision in ('defer', 'reject', 'accept_suggestion'):
                with self.subTest(domain='price', decision=decision), self.assertRaises(PriceConflict):
                    record_preliminary_review(actor=self.reviewer, candidate_id=self.price.pk, decision=decision,
                        reason=REASON, expected_review=0, expected_product=self.product.pk,
                        expected_product_hash=product_fingerprint(self.product))
            self.assertFalse(ProductCandidateReview.objects.exists())
            self.assertFalse(PriceCandidateReview.objects.exists())
        finally:
            ProductCandidate.objects.filter(pk=self.candidate.pk).update(staged_by_id=self.author.pk)
            PriceCandidate.objects.filter(pk=self.price.pk).update(staged_by_id=self.author.pk)

    def test_integrity_helpers_are_not_creator_identity_checks(self):
        try:
            ProductCandidate.objects.filter(pk=self.candidate.pk).update(staged_by_id=MISSING)
            PriceCandidate.objects.filter(pk=self.price.pk).update(staged_by_id=MISSING)
            self.candidate.refresh_from_db()
            self.price.refresh_from_db()
            self.assertTrue(valid_product(self.candidate))
            self.assertTrue(valid_price(self.price))
        finally:
            ProductCandidate.objects.filter(pk=self.candidate.pk).update(staged_by_id=self.author.pk)
            PriceCandidate.objects.filter(pk=self.price.pk).update(staged_by_id=self.author.pk)

    def test_receipt_checks_are_not_creator_identity_checks(self):
        product_receipt = stage_product_with_receipt(io.BytesIO(make_csv([PRODUCT_ROW])), 'منبع ساختگی',
            'https://example.org/product', actor=self.author, rights_attested=True)[1]
        price_receipt = stage_price_with_receipt(io.BytesIO(csv_bytes([PRICE_ROW])), 'منبع ساختگی',
            'https://example.org/price', actor=self.author, rights_attested=True)[1]
        try:
            ProductCandidate.objects.filter(pk=self.candidate.pk).update(staged_by_id=MISSING)
            PriceCandidate.objects.filter(pk=self.price.pk).update(staged_by_id=MISSING)
            self.client.force_login(self.viewer)
            for receipt in (product_receipt, price_receipt):
                with self.subTest(kind=receipt.kind):
                    manifest = manifest_context(receipt, 1)
                    self.assertTrue(manifest['page'].object_list[0].safe)
                    report = inspect_manifest(actor=self.viewer, receipt_id=receipt.pk)
                    self.assertEqual(report['rows'], [{'ordinal': 1, 'status': 'consistent'}])
                    for view in ('staff_import_receipt_detail', 'staff_import_manifest_inspection'):
                        response = self.client.get(reverse(view, args=[receipt.pk]))
                        self.assertContains(response, 'وجود حساب ثبت‌کننده نامزدها')
                        if view == 'staff_import_receipt_detail':
                            self.assertContains(response, 'در این بررسی سنجیده نمی‌شود')
                        else:
                            self.assertContains(response, 'حساب ثبت‌کننده رسید در این بازرسی بررسی نمی‌شود')
        finally:
            ProductCandidate.objects.filter(pk=self.candidate.pk).update(staged_by_id=self.author.pk)
            PriceCandidate.objects.filter(pk=self.price.pk).update(staged_by_id=self.author.pk)

    def test_existing_account_does_not_prove_activity_or_qualification(self):
        get_user_model().objects.filter(pk=self.author.pk).update(is_active=False, is_staff=False)
        for domain, item, _, events, service, _, detail, _, _, data in self.cases():
            with self.subTest(domain=domain):
                event = service(actor=self.reviewer, candidate_id=item.pk, **data)
                self.assertEqual(event.review_snapshot['staged_by_id'], self.author.pk)
                self.assertEqual(events.objects.count(), 1)
                self.client.force_login(self.viewer)
                self.assertNotContains(self.client.get(reverse(detail, args=[item.pk])), 'حساب ثبت‌کننده در دسترس نیست')

    def test_later_uncooperative_mutation_can_change_stager_after_check(self):
        from daroobank.account_checks import current_account_exists
        for domain, item, model, events, service, _, _, _, _, data in self.cases():
            module = 'catalog.intake' if domain == 'product' else 'pricing.reviews'
            def mutate(pk, *, using):
                exists = current_account_exists(pk, using=using)
                model.objects.filter(pk=item.pk).update(staged_by_id=MISSING)
                return exists
            try:
                with patch(f'{module}.current_account_exists', side_effect=mutate):
                    event = service(actor=self.reviewer, candidate_id=item.pk, **data)
                self.assertEqual(event.review_snapshot['staged_by_id'], self.author.pk)
                self.assertEqual(model.objects.get(pk=item.pk).staged_by_id, MISSING)
            finally:
                model.objects.filter(pk=item.pk).update(staged_by_id=self.author.pk)

    def test_normal_self_review_remains_forbidden(self):
        for domain, item, _, events, service, _, _, _, _, data in self.cases():
            with self.subTest(domain=domain), self.assertRaises(PermissionDenied):
                service(actor=self.author, candidate_id=item.pk, **data)
            self.assertFalse(events.objects.exists())


class StagerAccountConcurrencyTests(TransactionTestCase):
    def setUp(self):
        (self.author, self.reviewer, self.viewer, self.unauthorized, self.candidate,
         self.product, self.price) = build_synthetic()

    def worker(self, operation):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '2s'")
                cursor.execute("SET statement_timeout = '12s'")
            return operation()
        finally:
            connection.close()

    def test_review_does_not_lock_stager_account(self):
        from daroobank.account_checks import current_account_exists
        for domain in ('catalog', 'pricing'):
            with self.subTest(domain=domain):
                get_user_model().objects.filter(pk=self.author.pk).update(is_active=True)
                ready, resume = Event(), Event()
                def pause(pk, *, using):
                    present = current_account_exists(pk, using=using)
                    ready.set()
                    if not resume.wait(8):
                        raise TimeoutError('Synthetic review did not resume')
                    return present
                def review():
                    actor = get_user_model().objects.get(pk=self.reviewer.pk)
                    if domain == 'catalog':
                        return review_product(actor=actor, candidate_id=self.candidate.pk, decision='defer',
                            reason=REASON, expected_review=0, expected_hash=self.candidate.payload_sha256)
                    return record_preliminary_review(actor=actor, candidate_id=self.price.pk, decision='defer',
                        reason=REASON, expected_review=0, expected_product=0, expected_product_hash='')
                module = 'catalog.intake' if domain == 'catalog' else 'pricing.reviews'
                with patch(f'{module}.current_account_exists', side_effect=pause):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(self.worker, review)
                        try:
                            self.assertTrue(ready.wait(8))
                            self.assertEqual(get_user_model().objects.filter(pk=self.author.pk).update(is_active=False), 1)
                        finally:
                            resume.set()
                        self.assertIsNotNone(future.result(timeout=10))
                self.assertFalse(get_user_model().objects.get(pk=self.author.pk).is_active)
