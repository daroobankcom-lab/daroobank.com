"""Synthetic missing receipt-actor tests; FK corruption is restored before commit."""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from daroobank.account_checks import current_accounts
from catalog.test_intake import make_csv
from pricing.test_workflow import csv_bytes
from .manifest_inspection import inspect_manifest
from .models import ImportReceipt
from .receipts import manifest_context, related_receipts, stage_price_with_receipt, stage_product_with_receipt

MISSING = 2_147_483_000
PRODUCT_ROW = {'source_record_id': 'receipt-actor-product', 'name_fa': 'فرآورده ساختگی', 'name_en': '',
               'manufacturer': 'سازنده فرضی', 'strength': '۵ میلی گرم', 'dosage_form': 'قرص',
               'package_description': '۱۰ عدد', 'irc': '۰۰۱۲۳۴'}
PRICE_ROW = dict(source_record_id='receipt-actor-price', irc='۰۰۱۲۳۴', manufacturer='سازنده فرضی',
                 strength='۵ میلی گرم', dosage_form='قرص', package_description='۱۰ عدد', amount='123',
                 currency='RIAL', category='retail', unit='package', effective_date='2026-01-02',
                 source_published_date='')


@override_settings(STAFF_PORTAL_ENABLED=True)
class MissingReceiptActorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('receipt-actor-author', is_staff=True)
        cls.both = User.objects.create_user('receipt-actor-viewer', is_staff=True)
        cls.product_viewer = User.objects.create_user('receipt-actor-product-viewer', is_staff=True)
        cls.price_viewer = User.objects.create_user('receipt-actor-price-viewer', is_staff=True)
        cls.no_access = User.objects.create_user('receipt-actor-none', is_staff=True)
        for app, entity, domain_viewer in [('catalog', 'productcandidate', cls.product_viewer),
                                            ('pricing', 'pricecandidate', cls.price_viewer)]:
            permissions = Permission.objects.filter(content_type__app_label=app)
            cls.author.user_permissions.add(*permissions.filter(codename__in=[f'view_{entity}', f'add_{entity}']))
            view = permissions.get(codename=f'view_{entity}')
            cls.both.user_permissions.add(view)
            domain_viewer.user_permissions.add(view)
        cls.product_receipt = stage_product_with_receipt(io.BytesIO(make_csv([PRODUCT_ROW])), 'منبع ساختگی',
            'https://example.org/product', actor=cls.author, rights_attested=True)[1]
        cls.price_receipt = stage_price_with_receipt(io.BytesIO(csv_bytes([PRICE_ROW])), 'منبع ساختگی',
            'https://example.org/price', actor=cls.author, rights_attested=True)[1]

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_orphan_receipt_is_visible_in_its_domain_with_missing_account_notice(self):
        try:
            ImportReceipt.objects.filter(pk__in=[self.product_receipt.pk, self.price_receipt.pk]).update(actor_id=MISSING)
            before = list(ImportReceipt.objects.order_by('pk').values())
            for receipt, authorized, wrong in [(self.product_receipt, self.product_viewer, self.price_viewer),
                                               (self.price_receipt, self.price_viewer, self.product_viewer)]:
                with self.subTest(kind=receipt.kind):
                    self.client.force_login(authorized)
                    listing = self.client.get(reverse('staff_import_receipts'))
                    self.assert_private(listing)
                    self.assertEqual(listing.context['page'].paginator.count, 1)
                    self.assertContains(listing, reverse('staff_import_receipt_detail', args=[receipt.pk]))
                    self.assertContains(listing, 'حساب ثبت‌کننده رسید در دسترس نیست')
                    detail = self.client.get(reverse('staff_import_receipt_detail', args=[receipt.pk]))
                    self.assert_private(detail)
                    self.assertContains(detail, 'حساب ثبت‌کننده رسید در دسترس نیست')
                    self.assertContains(detail, 'ردیف داده 1')
                    self.assertContains(detail, reverse('staff_import_manifest_inspection', args=[receipt.pk]))
                    self.client.force_login(wrong)
                    self.assertEqual(self.client.get(reverse('staff_import_receipt_detail', args=[receipt.pk])).status_code, 404)
                    self.assertEqual(self.client.get(reverse('staff_import_manifest_inspection', args=[receipt.pk])).status_code, 404)
            self.client.force_login(self.no_access)
            self.assertEqual(self.client.get(reverse('staff_import_receipts')).status_code, 403)
            self.assertEqual(list(ImportReceipt.objects.order_by('pk').values()), before)
        finally:
            ImportReceipt.objects.filter(pk__in=[self.product_receipt.pk, self.price_receipt.pk]).update(actor_id=self.author.pk)

    def test_inspection_and_candidate_receipt_links_do_not_validate_receipt_actor(self):
        try:
            ImportReceipt.objects.filter(pk__in=[self.product_receipt.pk, self.price_receipt.pk]).update(actor_id=MISSING)
            self.client.force_login(self.both)
            for receipt in (self.product_receipt, self.price_receipt):
                with self.subTest(kind=receipt.kind):
                    item = receipt.items.first()
                    candidate = item.product_candidate if receipt.kind == 'product' else item.price_candidate
                    report = inspect_manifest(actor=self.both, receipt_id=receipt.pk)
                    self.assertEqual(report['rows'], [{'ordinal': 1, 'status': 'consistent'}])
                    self.assertTrue(manifest_context(receipt, 1)['page'].object_list[0].safe)
                    self.assertEqual([x.pk for x in related_receipts(self.both, candidate, receipt.kind)['items']], [receipt.pk])
                    inspection = self.client.get(reverse('staff_import_manifest_inspection', args=[receipt.pk]))
                    self.assert_private(inspection)
                    self.assertContains(inspection, 'حساب ثبت‌کننده رسید در این بازرسی بررسی نمی‌شود')
                    view = 'staff_product_detail' if receipt.kind == 'product' else 'staff_price_detail'
                    detail = self.client.get(reverse(view, args=[candidate.pk]))
                    self.assertContains(detail, reverse('staff_import_receipt_detail', args=[receipt.pk]))
                    self.assertContains(detail, 'حساب ثبت‌کننده رسید در این فهرست بررسی نمی‌شود')
        finally:
            ImportReceipt.objects.filter(pk__in=[self.product_receipt.pk, self.price_receipt.pk]).update(actor_id=self.author.pk)

    def test_inactive_account_is_still_shown_and_is_not_qualification_proof(self):
        get_user_model().objects.filter(pk=self.author.pk).update(is_active=False, is_staff=False)
        self.client.force_login(self.both)
        for url in (reverse('staff_import_receipts'), reverse('staff_import_receipt_detail', args=[self.price_receipt.pk])):
            response = self.client.get(url)
            self.assertContains(response, self.author.username)
            self.assertNotContains(response, 'حساب ثبت‌کننده رسید در دسترس نیست')

    def test_queue_account_lookup_is_page_local_without_per_row_queries(self):
        self.client.force_login(self.both)
        path = reverse('staff_import_receipts')
        self.client.get(path)
        with CaptureQueriesContext(connection) as baseline:
            self.client.get(path)
        for number in range(23):
            ImportReceipt.objects.create(kind='product', actor=self.author, source_name=f'منبع {number}',
                source_url='https://example.org/legacy', rows=1, created=1, duplicates=0)
        with CaptureQueriesContext(connection) as many:
            first = self.client.get(path)
        self.assertEqual(len(many), len(baseline))
        self.assertEqual(len(first.context['page'].object_list), 20)
        self.assertEqual(first.context['page'].paginator.count, 25)
        with patch('ingestion.staff_views.current_accounts', wraps=current_accounts) as lookup:
            last = self.client.get(path, {'page': 2})
        self.assertEqual(len(last.context['page'].object_list), 5)
        self.assertEqual(len(lookup.call_args.args[0]), 5)

    def test_legacy_orphan_and_escaped_username(self):
        legacy = ImportReceipt.objects.create(kind='product', actor=self.author, source_name='legacy',
            source_url='https://example.org/legacy', rows=1, created=1, duplicates=0)
        try:
            ImportReceipt.objects.filter(pk=legacy.pk).update(actor_id=MISSING)
            get_user_model().objects.filter(pk=self.author.pk).update(username='<synthetic>')
            self.client.force_login(self.both)
            listing = self.client.get(reverse('staff_import_receipts'))
            self.assertContains(listing, '&lt;synthetic&gt;')
            self.assertNotContains(listing, '<synthetic>')
            self.assertContains(listing, 'حساب ثبت‌کننده رسید در دسترس نیست')
            detail = self.client.get(reverse('staff_import_receipt_detail', args=[legacy.pk]))
            self.assertContains(detail, 'حساب ثبت‌کننده رسید در دسترس نیست')
            self.assertContains(detail, 'حدس یا بازسازی نشده‌اند')
            scan = inspect_manifest(actor=self.both, receipt_id=legacy.pk)
            self.assertEqual((scan['status'], scan['rows']), ('legacy', []))
        finally:
            ImportReceipt.objects.filter(pk=legacy.pk).update(actor_id=self.author.pk)

    def test_separate_lookup_is_not_snapshot_or_identity_proof(self):
        def mutate_after_lookup(ids, *, using):
            found = current_accounts(ids, using=using)
            ImportReceipt.objects.filter(pk=self.product_receipt.pk).update(actor_id=MISSING)
            return found
        try:
            self.client.force_login(self.both)
            with patch('ingestion.staff_views.current_accounts', side_effect=mutate_after_lookup):
                response = self.client.get(reverse('staff_import_receipt_detail', args=[self.product_receipt.pk]))
            self.assertContains(response, self.author.username)
            self.assertEqual(ImportReceipt.objects.get(pk=self.product_receipt.pk).actor_id, MISSING)
        finally:
            ImportReceipt.objects.filter(pk=self.product_receipt.pk).update(actor_id=self.author.pk)
