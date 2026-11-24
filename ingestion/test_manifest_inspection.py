"""Synthetic tests for private, bounded per-receipt consistency scans."""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from catalog.models import ProductCandidate
from catalog.test_intake import make_csv
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes
from .manifest_inspection import (BATCH_SIZE, MAX_ORDINAL, MAX_PK, InvalidManifestInspection,
                                  ReceiptNotFound, inspect_manifest)
from .models import ImportReceipt, ImportReceiptItem
from .receipts import manifest_item_safe, manifest_structure, stage_price_with_receipt, stage_product_with_receipt


@override_settings(STAFF_PORTAL_ENABLED=True)
class ManifestInspectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.product_user = User.objects.create_user('manifest-scan-product', is_staff=True)
        cls.price_user = User.objects.create_user('manifest-scan-price', is_staff=True)
        cls.both = User.objects.create_user('manifest-scan-both', is_staff=True)
        cls.other = User.objects.create_user('manifest-scan-other', is_staff=True)
        cls.nonstaff = User.objects.create_user('manifest-scan-nonstaff', is_staff=False)
        cls.inactive = User.objects.create_user('manifest-scan-inactive', is_staff=True, is_active=False)
        for user, app, codes in [(cls.product_user, 'catalog', ['view_productcandidate', 'add_productcandidate']),
                                 (cls.price_user, 'pricing', ['view_pricecandidate', 'add_pricecandidate']),
                                 (cls.both, 'catalog', ['view_productcandidate']),
                                 (cls.both, 'pricing', ['view_pricecandidate']),
                                 (cls.nonstaff, 'pricing', ['view_pricecandidate']),
                                 (cls.inactive, 'pricing', ['view_pricecandidate'])]:
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label=app, codename__in=codes))
        cls.product_row = dict(source_record_id='sensitive-product', name_fa='نام محرمانه ساختگی', name_en='Synthetic',
            manufacturer='سازنده ساختگی', strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        cls.price_row = dict(source_record_id='sensitive-price', irc='001', manufacturer='سازنده ساختگی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL', category='retail',
            unit='package', effective_date='', source_published_date='')
        cls.product_receipt = stage_product_with_receipt(io.BytesIO(make_csv([cls.product_row])), 'منبع محرمانه ساختگی',
            'https://example.org/private-product', actor=cls.product_user, rights_attested=True)[1]
        cls.price_receipt = stage_price_with_receipt(io.BytesIO(csv_bytes([cls.price_row])), 'منبع محرمانه ساختگی',
            'https://example.org/private-price', actor=cls.price_user, rights_attested=True)[1]

    def scan(self, receipt, actor=None, **kwargs):
        return inspect_manifest(actor=actor or self.both, receipt_id=receipt.pk, **kwargs)

    def url(self, receipt):
        return reverse('staff_import_manifest_inspection', args=[receipt.pk])

    def test_private_read_only_scope_and_no_content_disclosure(self):
        before_receipts = list(ImportReceipt.objects.order_by('pk').values())
        before_items = list(ImportReceiptItem.objects.order_by('pk').values())
        for receipt, user, wrong_user in [(self.product_receipt, self.product_user, self.price_user),
                                          (self.price_receipt, self.price_user, self.product_user)]:
            with self.subTest(kind=receipt.kind):
                report = self.scan(receipt, user)
                self.assertEqual(report['status'], 'available')
                self.assertEqual(report['rows'], [{'ordinal': 1, 'status': 'consistent'}])
                self.assertEqual(report['scanned'], 1)
                self.assertIsNone(report['next_after'])
                self.client.force_login(user)
                response = self.client.get(self.url(receipt))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'ردیف داده 1')
                self.assertContains(response, 'اصالت فایل')
                self.assertContains(self.client.get(reverse('staff_import_receipt_detail', args=[receipt.pk])), self.url(receipt))
                for secret in ('sensitive-product', 'sensitive-price', 'منبع محرمانه', 'نام محرمانه',
                               'private-product', 'private-price', receipt.items.first().payload_sha256):
                    self.assertNotContains(response, secret)
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                self.assertEqual(response['Referrer-Policy'], 'same-origin')
                self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                self.assertEqual(self.client.head(self.url(receipt)).status_code, 200)
                self.assertEqual(self.client.post(self.url(receipt)).status_code, 405)
                self.client.force_login(wrong_user)
                self.assertEqual(self.client.get(self.url(receipt)).status_code, 404)
                with self.assertRaises(ReceiptNotFound): self.scan(receipt, wrong_user)
        self.assertEqual(list(ImportReceipt.objects.order_by('pk').values()), before_receipts)
        self.assertEqual(list(ImportReceiptItem.objects.order_by('pk').values()), before_items)

    def test_bounded_scan_filter_after_batch_and_query_count(self):
        for kind, actor, model in [('product', self.product_user, ProductCandidate), ('price', self.price_user, PriceCandidate)]:
            with self.subTest(kind=kind):
                rows = [{**(self.product_row if kind == 'product' else self.price_row),
                         'source_record_id': f'synthetic-{kind}-{i}'} for i in range(BATCH_SIZE + 7)]
                if kind == 'product':
                    receipt = stage_product_with_receipt(io.BytesIO(make_csv(rows)), 'منبع آزمایشی',
                        'https://example.org/many-product', actor=actor, rights_attested=True)[1]
                    field = 'product_candidate_id'
                else:
                    receipt = stage_price_with_receipt(io.BytesIO(csv_bytes(rows)), 'منبع آزمایشی',
                        'https://example.org/many-price', actor=actor, rights_attested=True)[1]
                    field = 'price_candidate_id'
                last_id = getattr(receipt.items.get(ordinal=BATCH_SIZE + 1), field)
                model.objects.filter(pk=last_id).update(source_fields={'bad': 'private-canary'})
                self.assertTrue(actor.has_perm(f'{"catalog" if kind == "product" else "pricing"}.view_{kind}candidate'))
                with CaptureQueriesContext(connection) as queries:
                    first = self.scan(receipt, actor, category='inconsistent')
                self.assertEqual(len(queries), 3)  # receipt, structural aggregate, bounded left join
                self.assertEqual((first['scanned'], first['rows'], first['next_after']), (BATCH_SIZE, [], BATCH_SIZE))
                next_page = self.scan(receipt, actor, after=first['next_after'], category='inconsistent')
                self.assertEqual(next_page['scanned'], 7)
                self.assertEqual(next_page['rows'], [{'ordinal': BATCH_SIZE + 1, 'status': 'inconsistent'}])
                self.assertIsNone(next_page['next_after'])
                self.client.force_login(actor)
                first_http = self.client.get(self.url(receipt), {'category': 'inconsistent'})
                self.assertContains(first_http, 'در این بخش نتیجه‌ای مطابق فیلتر دیده نشد')
                self.assertContains(first_http, '?after=50&amp;category=inconsistent')
                next_http = self.client.get(self.url(receipt), {'after': '۵۰', 'category': 'inconsistent'})
                self.assertContains(next_http, 'ردیف داده 51')
                self.assertNotContains(next_http, 'private-canary')

    def test_structure_rejects_duplicate_ordinals_even_if_database_constraint_is_missing(self):
        # A duplicate 1 and missing 2 preserve count, minimum, maximum and all
        # status totals. The constraint is removed only inside a rolled-back
        # synthetic test transaction, not as a repair procedure.
        cases = [
            (stage_product_with_receipt, make_csv([self.product_row] * 3), self.product_user),
            (stage_price_with_receipt, csv_bytes([self.price_row] * 3), self.price_user),
        ]
        for service, payload, actor in cases:
            with self.subTest(service=service.__name__):
                receipt = service(io.BytesIO(payload), 'منبع آزمایشی',
                    'https://example.org/ordinal-canary', actor=actor, rights_attested=True)[1]
                self.assertEqual(manifest_structure(receipt), 'available')
                self.client.force_login(actor)
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                        cursor.execute('ALTER TABLE ingestion_importreceiptitem DROP CONSTRAINT receipt_item_unique_ordinal')
                    receipt.items.filter(ordinal=2).update(ordinal=1)
                    self.assertEqual(manifest_structure(receipt), 'invalid')
                    report = self.scan(receipt, actor)
                    self.assertEqual((report['status'], report['rows'], report['scanned']), ('invalid', [], 0))
                    scan = self.client.get(self.url(receipt))
                    detail = self.client.get(reverse('staff_import_receipt_detail', args=[receipt.pk]))
                    self.assertContains(scan, 'ساختار یا شمارش فهرست ناسازگار است')
                    self.assertContains(detail, 'تعداد یا ساختار فهرست ناسازگار است')
                    self.assertNotContains(scan, 'ردیف داده 1')
                    self.assertNotContains(detail, 'ردیف داده 1')
                    self.assertEqual(scan['Cache-Control'], 'private, no-store, max-age=0')
                    transaction.set_rollback(True)
                self.assertEqual(manifest_structure(receipt), 'available')

    def test_invalid_candidate_and_mismatched_item_are_fixed_status_only(self):
        for receipt, user, model, fk in [(self.product_receipt, self.product_user, ProductCandidate, 'product_candidate_id'),
                                         (self.price_receipt, self.price_user, PriceCandidate, 'price_candidate_id')]:
            with self.subTest(kind=receipt.kind):
                item = receipt.items.first()
                model.objects.filter(pk=getattr(item, fk)).update(source_fields={'bad': 'do-not-display'})
                self.assertEqual(self.scan(receipt, user)['rows'], [{'ordinal': 1, 'status': 'inconsistent'}])
                self.client.force_login(user)
                response = self.client.get(self.url(receipt))
                self.assertContains(response, 'ردیف یا نامزد ناسازگار')
                self.assertNotContains(response, 'do-not-display')
                self.assertNotContains(response, item.source_record_id)
                self.assertNotContains(response, item.payload_sha256)

    def test_item_mismatch_and_missing_reference_fail_closed(self):
        for receipt, user, fk in [(self.product_receipt, self.product_user, 'product_candidate_id'),
                                   (self.price_receipt, self.price_user, 'price_candidate_id')]:
            with self.subTest(kind=receipt.kind):
                item = receipt.items.first()
                ImportReceiptItem.objects.filter(pk=item.pk).update(payload_sha256='0' * 64)
                self.assertEqual(self.scan(receipt, user)['rows'], [{'ordinal': 1, 'status': 'inconsistent'}])
                # The FK normally prevents this in the database; exercise the
                # uncached missing-relation guard on an in-memory object.
                item = receipt.items.first()
                setattr(item, fk, 2147483647)
                self.assertFalse(manifest_item_safe(receipt, item))

    def test_legacy_and_structural_invalid_never_reconstruct_rows(self):
        legacy = ImportReceipt.objects.create(kind='product', source_name='legacy', source_url='https://example.org',
            actor=self.product_user, rows=1, created=1, duplicates=0)
        self.assertEqual(self.scan(legacy)['status'], 'legacy')
        self.assertEqual(self.scan(legacy)['rows'], [])
        ImportReceiptItem.objects.filter(receipt=self.price_receipt).delete()
        self.assertEqual(self.scan(self.price_receipt)['status'], 'invalid')
        self.assertEqual(self.scan(self.price_receipt)['rows'], [])
        self.client.force_login(self.both)
        self.assertContains(self.client.get(self.url(legacy)), 'حدس یا بازسازی نشده‌اند')
        self.assertContains(self.client.get(self.url(self.price_receipt)), 'بازرسی ردیف‌ها متوقف شد')

    def test_historical_price_match_is_not_recomputed_or_compared(self):
        item = self.price_receipt.items.first()
        self.assertEqual(item.match_status, 'unmatched')
        PriceCandidate.objects.filter(pk=item.price_candidate_id).update(match_status='ambiguous')
        with patch('pricing.importer.suggest_product', side_effect=AssertionError('unexpected rematch')):
            result = self.scan(self.price_receipt, self.price_user)
        self.assertEqual(result['rows'], [{'ordinal': 1, 'status': 'consistent'}])
        item.refresh_from_db()
        self.assertEqual(item.match_status, 'unmatched')

    def test_structure_and_row_reads_are_not_a_snapshot(self):
        from . import manifest_inspection
        original = manifest_inspection.manifest_structure
        def remove_after_aggregate(receipt):
            status = original(receipt)
            ImportReceiptItem.objects.filter(receipt=receipt).delete()
            return status
        with patch('ingestion.manifest_inspection.manifest_structure', side_effect=remove_after_aggregate):
            result = self.scan(self.price_receipt, self.price_user)
        self.assertEqual((result['status'], result['scanned'], result['rows']), ('available', 0, []))
        self.assertEqual(self.scan(self.price_receipt, self.price_user)['status'], 'invalid')

    def test_validation_permissions_and_unreflecting_errors(self):
        for actor in (None, self.other, self.nonstaff, self.inactive):
            with self.subTest(actor=actor), self.assertRaises(PermissionDenied):
                inspect_manifest(actor=actor, receipt_id=self.price_receipt.pk)
        self.assertEqual(self.client.get(self.url(self.price_receipt)).status_code, 302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.url(self.price_receipt)).status_code, 403)
        self.client.force_login(self.product_user)
        self.assertEqual(self.client.get(self.url(self.price_receipt), {'after': 'bad-secret'}).status_code, 404)
        self.client.force_login(self.price_user)
        for value in ['', '-1', '+1', ' 1', '१', '۱e2', '1'*100, '5001', 'bad-secret<script>']:
            for method in (self.client.get, self.client.head):
                response = method(self.url(self.price_receipt), {'after': value})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                self.assertNotIn(b'bad-secret', response.content)
                self.assertNotIn(b'&lt;script&gt;', response.content)
                if method == self.client.get:
                    self.assertContains(response, self.url(self.price_receipt), status_code=400)
                else:
                    self.assertEqual(response.content, b'')
        for raw, expected in [('٠', 0), ('۵۰۰۰', 5000), ('0001', 1), ('۱2٣', 123)]:
            self.assertEqual(self.client.get(self.url(self.price_receipt), {'after': raw}).context['report']['after'], expected)
        self.assertEqual(self.client.get(self.url(self.price_receipt), {'category': 'bad-secret'}).status_code, 400)
        for val in (None, True, -1, MAX_ORDINAL + 1, '1'):
            with self.subTest(val=val), self.assertRaises(InvalidManifestInspection):
                inspect_manifest(actor=self.price_user, receipt_id=self.price_receipt.pk, after=val)
        for val in (0, True, MAX_PK + 1, '1'):
            with self.subTest(val=val), self.assertRaises(ReceiptNotFound):
                inspect_manifest(actor=self.price_user, receipt_id=val)
        with self.assertRaises(InvalidManifestInspection):
            self.scan(self.price_receipt, category='bad')
        self.assertEqual(self.client.get(reverse('staff_import_manifest_inspection', args=[MAX_PK + 1])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('sitemap')), '/staff/')

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_debug_gate(self):
        self.client.force_login(self.price_user)
        response = self.client.get(self.url(self.price_receipt))
        self.assertEqual(response.status_code, 404)
        self.assertIn('no-store', response['Cache-Control'])

    def test_group_permission_is_domain_scoped(self):
        User = get_user_model()
        user = User.objects.create_user('group-manifest-scan', is_staff=True)
        group = Group.objects.create(name='manifest-scan-prices')
        group.permissions.add(Permission.objects.get(content_type__app_label='pricing', codename='view_pricecandidate'))
        user.groups.add(group)
        self.assertEqual(self.scan(self.price_receipt, user)['status'], 'available')
        with self.assertRaises(ReceiptNotFound): self.scan(self.product_receipt, user)
