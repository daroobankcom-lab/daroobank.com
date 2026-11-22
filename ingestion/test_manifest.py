import io
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from catalog.intake import IntakeError, stage_products
from catalog.models import ProductCandidate
from catalog.test_intake import make_csv
from pricing.importer import ImportValidationError, stage_csv
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes
from .models import ImportReceipt, ImportReceiptItem
from .receipts import related_receipts, stage_price_with_receipt, stage_product_with_receipt

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = (ROOT / 'examples/product_candidates.synthetic.csv').read_bytes()
PRICE = (ROOT / 'examples/price_candidates.synthetic.csv').read_bytes()


class ManifestTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.product_author = U.objects.create_user('manifest-product', is_staff=True)
        cls.price_author = U.objects.create_user('manifest-price', is_staff=True)
        cls.both = U.objects.create_user('manifest-both', is_staff=True)
        cls.source = U.objects.create_user('manifest-source', is_staff=True)
        for user, app, names in [
            (cls.product_author, 'catalog', ['view_productcandidate', 'add_productcandidate']),
            (cls.price_author, 'pricing', ['view_pricecandidate', 'add_pricecandidate']),
            (cls.both, 'catalog', ['view_productcandidate']), (cls.both, 'pricing', ['view_pricecandidate']),
            (cls.source, 'sources', ['view_sourceclaim'])]:
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label=app, codename__in=names))
        cls.product_row = {'source_record_id': 'sample-1', 'name_fa': 'نمونه ساختگی', 'name_en': 'Synthetic',
            'manufacturer': 'سازنده فرضی', 'strength': '5 mg', 'dosage_form': 'قرص', 'package_description': '10 عدد', 'irc': '1234'}
        cls.price_row = {'source_record_id': 'price-1', 'irc': '1234', 'manufacturer': 'سازنده فرضی', 'strength': '5 mg',
            'dosage_form': 'قرص', 'package_description': '10 عدد', 'amount': '100', 'currency': 'RIAL',
            'category': 'retail', 'unit': 'package', 'effective_date': '', 'source_published_date': ''}

    def product(self, content=PRODUCT):
        return stage_product_with_receipt(io.BytesIO(content), 'ساختگی محصول', 'https://example.org/product',
                                          actor=self.product_author, rights_attested=True)[1]

    def price(self, content=PRICE):
        return stage_price_with_receipt(io.BytesIO(content), 'ساختگی قیمت', 'https://example.org/price',
                                        actor=self.price_author, rights_attested=True)[1]

    def detail(self, receipt):
        return self.client.get(reverse('staff_import_receipt_detail', args=[receipt.pk]))

    def test_new_replay_and_internal_duplicates_are_per_row(self):
        for kind, content, create, field in [
            ('product', make_csv([self.product_row, self.product_row, {**self.product_row, 'strength': '6 mg'}]), self.product, 'product_candidate_id'),
            ('price', csv_bytes([self.price_row, self.price_row, {**self.price_row, 'amount': '110'}]), self.price, 'price_candidate_id')]:
            with self.subTest(kind=kind):
                receipt = create(content); items = list(receipt.items.all())
                self.assertEqual(receipt.manifest_version, 1)
                self.assertEqual((receipt.rows, receipt.created, receipt.duplicates), (3, 2, 1))
                self.assertEqual([x.ordinal for x in items], [1, 2, 3])
                self.assertEqual([x.was_created for x in items], [True, False, True])
                self.assertEqual(getattr(items[0], field), getattr(items[1], field))
                self.assertNotEqual(getattr(items[0], field), getattr(items[2], field))
                self.assertEqual(items[0].payload_sha256, items[1].payload_sha256)
                self.assertNotEqual(items[0].payload_sha256, items[2].payload_sha256)
                self.assertEqual(items[0].source_record_id, items[2].source_record_id)
                if kind == 'price': self.assertEqual([x.match_status for x in items], ['unmatched'] * 3)
                else: self.assertEqual([x.match_status for x in items], [''] * 3)
                replay = create(content)
                self.assertEqual((replay.created, replay.duplicates), (0, 3))
                self.assertEqual([x.was_created for x in replay.items.all()], [False] * 3)
                self.assertEqual([getattr(x, field) for x in replay.items.all()], [getattr(x, field) for x in items])
        self.assertEqual(ProductCandidate.objects.count(), 2); self.assertEqual(PriceCandidate.objects.count(), 2)

    def test_scoped_links_and_no_cross_domain_leak(self):
        product, price = self.product(), self.price()
        self.client.force_login(self.product_author)
        response = self.detail(product)
        self.assertEqual(response.context['manifest']['status'], 'available')
        for item in product.items.all(): self.assertContains(response, reverse('staff_product_detail', args=[item.product_candidate_id]))
        self.assertNotContains(response, 'مشاهده نامزد قیمت')
        self.assertEqual(self.detail(price).status_code, 404)
        self.client.force_login(self.price_author)
        response = self.detail(price)
        for item in price.items.all(): self.assertContains(response, reverse('staff_price_detail', args=[item.price_candidate_id]))
        self.assertNotContains(response, 'مشاهده نامزد فرآورده')
        self.assertEqual(self.detail(product).status_code, 404)
        self.client.force_login(self.source)
        self.assertEqual(self.detail(price).status_code, 403)
        self.assertNotContains(self.client.get(reverse('sitemap')), '/staff/')

    def test_candidate_detail_recent_receipts_are_bounded_unique_and_permission_scoped(self):
        for kind, create, author, route, model in [('product', self.product, self.product_author, 'staff_product_detail', ProductCandidate),
                                                    ('price', self.price, self.price_author, 'staff_price_detail', PriceCandidate)]:
            first = create(); candidate = model.objects.first()
            for _ in range(6): create()
            refs = related_receipts(author, candidate, kind)
            self.assertEqual(len(refs['items']), 5); self.assertTrue(refs['limited'])
            self.assertNotIn(first.pk, [r.pk for r in refs['items']])
            self.client.force_login(author)
            response = self.client.get(reverse(route, args=[candidate.pk]))
            for receipt in refs['items']:
                self.assertContains(response, reverse('staff_import_receipt_detail', args=[receipt.pk]))
            self.assertContains(response, 'فقط پنج رسید اخیر')
            with self.assertRaises(PermissionDenied): related_receipts(self.source, candidate, kind)
        receipt = self.product(make_csv([self.product_row, self.product_row]))
        candidate = ProductCandidate.objects.get(source_record_id=self.product_row['source_record_id'])
        refs = related_receipts(self.product_author, candidate, 'product')
        self.assertEqual([r.pk for r in refs['items']], [receipt.pk])

    def test_legacy_receipt_is_unknown_not_empty_manifest(self):
        receipt = ImportReceipt.objects.create(kind='product', source_name='قدیمی', source_url='https://example.org',
                                                actor=self.product_author, rows=2, created=2, duplicates=0)
        self.client.force_login(self.product_author)
        response = self.detail(receipt)
        self.assertEqual(response.context['manifest']['status'], 'legacy')
        self.assertContains(response, 'حدس یا بازسازی نشده‌اند')
        self.assertFalse(receipt.items.exists())

    def test_candidate_or_item_mismatch_suppresses_row_details(self):
        product, price = self.product(), self.price()
        self.client.force_login(self.both)
        product_item = product.items.first(); price_item = price.items.first()
        ProductCandidate.objects.filter(pk=product_item.product_candidate_id).update(source_fields={'bad': 'structure'})
        PriceCandidate.objects.filter(pk=price_item.price_candidate_id).update(amount_rial=999999)
        for receipt, item, route, pk in [(product, product_item, 'staff_product_detail', product_item.product_candidate_id),
                                         (price, price_item, 'staff_price_detail', price_item.price_candidate_id)]:
            response = self.detail(receipt)
            self.assertEqual(response.context['manifest']['status'], 'available')
            self.assertContains(response, 'اطلاعات ردیف یا نامزد ناسازگار است')
            self.assertNotContains(response, reverse(route, args=[pk]))
            self.assertNotContains(response, item.payload_sha256)
            self.assertNotContains(response, item.source_record_id)
        price_item = price.items.last()
        ImportReceiptItem.objects.filter(pk=price_item.pk).update(payload_sha256='0' * 64)
        response = self.detail(price)
        self.assertNotContains(response, reverse('staff_price_detail', args=[price_item.price_candidate_id]))
        self.assertEqual(response.content.decode().count('اطلاعات ردیف یا نامزد ناسازگار است'), 2)

    def test_structural_mismatch_or_wrong_domain_hides_entire_manifest(self):
        product, price = self.product(), self.price()
        item = product.items.first(); candidate = price.items.first().price_candidate
        ImportReceiptItem.objects.filter(pk=item.pk).update(product_candidate=None, price_candidate=candidate, match_status='unmatched')
        self.client.force_login(self.product_author)
        response = self.detail(product)
        self.assertEqual(response.context['manifest']['status'], 'invalid')
        self.assertNotContains(response, candidate.source_record_id)
        self.assertNotContains(response, reverse('staff_price_detail', args=[candidate.pk]))
        ImportReceiptItem.objects.filter(receipt=price).delete()  # ordinary model guards do not apply to bulk ORM
        self.client.force_login(self.price_author)
        response = self.detail(price)
        self.assertEqual(response.context['manifest']['status'], 'invalid')
        self.assertContains(response, 'نمایش ردیف‌ها متوقف شد')

    def test_pagination_and_untrusted_id_escaping(self):
        rows = [{**self.product_row, 'source_record_id': f'x-{i}'} for i in range(29)]
        rows.append({**self.product_row, 'source_record_id': '<script>alert(1)</script>'})
        receipt = self.product(make_csv(rows))
        self.client.force_login(self.product_author)
        first = self.detail(receipt)
        self.assertEqual(len(first.context['manifest']['page']), 25)
        self.assertContains(first, '?page=2')
        second = self.client.get(reverse('staff_import_receipt_detail', args=[receipt.pk]), {'page': 2})
        self.assertEqual(len(second.context['manifest']['page']), 5)
        self.assertContains(second, '&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(second, '<script>alert(1)</script>')
        self.assertIn('no-store', second['Cache-Control'])
        self.assertEqual(second['X-Robots-Tag'], 'noindex, nofollow')

    def test_item_bulk_create_failure_rolls_back_candidates_receipt_and_items(self):
        for create, model in [(self.product, ProductCandidate), (self.price, PriceCandidate)]:
            original = ImportReceiptItem.objects.bulk_create
            def partial_then_fail(items, **kwargs):
                original(items[:1], **kwargs)
                raise RuntimeError('simulated write failure')
            with patch.object(ImportReceiptItem.objects, 'bulk_create', side_effect=partial_then_fail):
                with self.assertRaises(RuntimeError): create()
            self.assertEqual(model.objects.count(), 0)
            self.assertEqual(ImportReceipt.objects.count(), 0); self.assertEqual(ImportReceiptItem.objects.count(), 0)

    def test_outcome_count_mismatch_rolls_back_staging_and_receipt(self):
        from ingestion import receipts
        for create, method, model in [(self.product, 'stage_products', ProductCandidate), (self.price, 'stage_csv', PriceCandidate)]:
            original = getattr(receipts, method)
            def discard_outcomes(*args, **kwargs):
                kwargs['on_staged'] = lambda *row: None
                return original(*args, **kwargs)
            with patch.object(receipts, method, side_effect=discard_outcomes):
                with self.assertRaises(ValueError): create()
            self.assertEqual(model.objects.count(), 0)
            self.assertEqual(ImportReceipt.objects.count(), 0)
            self.assertEqual(ImportReceiptItem.objects.count(), 0)

    def test_malformed_unicode_in_price_candidate_is_not_rendered(self):
        receipt = self.price(); item = receipt.items.first(); candidate = item.price_candidate
        fields = dict(candidate.source_fields); fields['manufacturer'] = '\ud800'
        PriceCandidate.objects.filter(pk=candidate.pk).update(source_fields=fields)
        self.client.force_login(self.price_author)
        response = self.detail(receipt)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'اطلاعات ردیف یا نامزد ناسازگار است')
        self.assertNotContains(response, reverse('staff_price_detail', args=[candidate.pk]))

    def test_callback_failure_rolls_back_original_staging_and_preview_rejects_callback(self):
        for stage, content, kwargs, exception, model in [
            (stage_products, PRODUCT, {'actor': self.product_author}, IntakeError, ProductCandidate),
            (stage_csv, PRICE, {'staged_by': self.price_author}, ImportValidationError, PriceCandidate)]:
            with self.subTest(stage=stage):
                with self.assertRaises(exception):
                    stage(io.BytesIO(content), 'مثال', 'https://example.org', on_staged=lambda *args: None, **kwargs)
                def fail(*args): raise RuntimeError('simulated outcome failure')
                with self.assertRaises(RuntimeError):
                    stage(io.BytesIO(content), 'مثال', 'https://example.org', commit=True, rights_attested=True, on_staged=fail, **kwargs)
                self.assertEqual(model.objects.count(), 0)

    def test_database_constraints_immutability_and_protected_refs(self):
        receipt = self.product(); item = receipt.items.first()
        with self.assertRaises(ValidationError): item.save()
        with self.assertRaises(ValidationError): item.delete()
        with self.assertRaises(ProtectedError): item.product_candidate.delete()
        with self.assertRaises(ProtectedError): ImportReceipt.objects.filter(pk=receipt.pk).delete()
        base = dict(receipt=receipt, ordinal=3, source_record_id='x', payload_sha256='0' * 64,
                    was_created=True, product_candidate=item.product_candidate)
        for fields in [dict(ordinal=0), dict(ordinal=5001), dict(ordinal=1), dict(product_candidate=None), dict(match_status='unmatched')]:
            with self.subTest(fields=fields), self.assertRaises(IntegrityError), transaction.atomic():
                ImportReceiptItem.objects.create(**(base | fields))
        with self.assertRaises(IntegrityError), transaction.atomic():
            ImportReceipt.objects.filter(pk=receipt.pk).update(manifest_version=2)
        self.assertFalse(Permission.objects.filter(content_type__app_label='ingestion', content_type__model='importreceiptitem').exists())

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_debug_gate_still_applies(self):
        receipt = self.product(); self.client.force_login(self.product_author)
        response = self.detail(receipt)
        self.assertEqual(response.status_code, 404)
        self.assertIn('no-store', response['Cache-Control'])


class ReceiptMigrationTests(TransactionTestCase):
    def test_existing_receipt_not_backfilled(self):
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor
        executor = MigrationExecutor(connection)
        old = [('ingestion', '0001_initial')]
        new = [('ingestion', '0002_importreceiptitem_importreceipt_manifest_version_and_more')]
        try:
            executor.migrate(old)
            apps = executor.loader.project_state(old).apps
            User = apps.get_model('auth', 'User')
            Receipt = apps.get_model('ingestion', 'ImportReceipt')
            actor = User.objects.create(username='migration-actor')
            old_receipt = Receipt.objects.create(kind='product', source_name='قدیمی', source_url='https://example.org',
                                                 actor_id=actor.pk, rows=1, created=1, duplicates=0)
            executor = MigrationExecutor(connection); executor.migrate(new)
            apps = executor.loader.project_state(new).apps
            Receipt = apps.get_model('ingestion', 'ImportReceipt')
            Item = apps.get_model('ingestion', 'ImportReceiptItem')
            self.assertIsNone(Receipt.objects.get(pk=old_receipt.pk).manifest_version)
            self.assertFalse(Item.objects.filter(receipt_id=old_receipt.pk).exists())
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
