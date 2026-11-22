import io
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from catalog.intake import stage_products
from catalog.models import ProductCandidate, ProductPresentation
from pricing.importer import stage_csv
from pricing.models import PriceCandidate
from .models import ImportReceipt
from .receipts import stage_price_with_receipt, stage_product_with_receipt

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = (ROOT / 'examples/product_candidates.synthetic.csv').read_bytes()
PRICE = (ROOT / 'examples/price_candidates.synthetic.csv').read_bytes()


class ReceiptTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        U = get_user_model()
        cls.product_author = U.objects.create_user('receipt-product-author', password='test-only-password', is_staff=True)
        cls.price_author = U.objects.create_user('receipt-price-author', password='test-only-password', is_staff=True)
        cls.product_viewer = U.objects.create_user('receipt-product-viewer', password='test-only-password', is_staff=True)
        cls.price_viewer = U.objects.create_user('receipt-price-viewer', password='test-only-password', is_staff=True)
        cls.both_viewer = U.objects.create_user('receipt-both-viewer', password='test-only-password', is_staff=True)
        cls.source_viewer = U.objects.create_user('receipt-source-only', password='test-only-password', is_staff=True)
        cls.regular = U.objects.create_user('receipt-regular', password='test-only-password')
        cls.inactive = U.objects.create_user('receipt-inactive', password='test-only-password', is_staff=True, is_active=False)
        def grant(user, app, *codes):
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label=app, codename__in=codes))
        grant(cls.product_author, 'catalog', 'view_productcandidate', 'add_productcandidate')
        grant(cls.price_author, 'pricing', 'view_pricecandidate', 'add_pricecandidate')
        for user in [cls.product_viewer, cls.both_viewer, cls.regular, cls.inactive]: grant(user, 'catalog', 'view_productcandidate')
        for user in [cls.price_viewer, cls.both_viewer]: grant(user, 'pricing', 'view_pricecandidate')
        grant(cls.source_viewer, 'sources', 'view_sourceclaim')
        cls.group_viewer = U.objects.create_user('receipt-group', password='test-only-password', is_staff=True)
        group = Group.objects.create(name='receipt-product-group')
        group.permissions.add(Permission.objects.get(content_type__app_label='catalog', codename='view_productcandidate'))
        cls.group_viewer.groups.add(group)

    def upload(self, kind, action='stage', rights=True, file=None, name=None):
        return self.client.post(reverse('staff_product_upload' if kind == 'product' else 'staff_price_upload'), {
            'source_name': name or f'{kind} ساختگی', 'source_url': f'https://example.org/{kind}', 'action': action,
            'rights_attested': 'on' if rights else '', 'csv_file': SimpleUploadedFile('synthetic.csv',
                file if file is not None else (PRODUCT if kind == 'product' else PRICE), content_type='text/csv'),
        })

    def stage_both(self):
        self.client.force_login(self.product_author); self.upload('product')
        self.client.force_login(self.price_author); self.upload('price')
        return ImportReceipt.objects.get(kind='product'), ImportReceipt.objects.get(kind='price')

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control']); self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_web_stages_receipts_and_replays_count_all_rows(self):
        for kind, author in [('product', self.product_author), ('price', self.price_author)]:
            self.client.force_login(author)
            first = self.upload(kind)
            receipt = ImportReceipt.objects.filter(kind=kind).get()
            self.assertContains(first, reverse('staff_import_receipt_detail', args=[receipt.pk]))
            self.assertEqual((receipt.rows, receipt.created, receipt.duplicates, receipt.actor), (2, 2, 0, author))
            self.assertEqual(receipt.source_url, f'https://example.org/{kind}')
            self.assertEqual(receipt.source_name, f'{kind} ساختگی')
            if kind == 'price': self.assertEqual((receipt.suggested, receipt.ambiguous, receipt.unmatched), (0, 0, 2))
            else: self.assertEqual((receipt.suggested, receipt.ambiguous, receipt.unmatched), (None, None, None))
            second = self.upload(kind)
            replay = ImportReceipt.objects.filter(kind=kind).latest('pk')
            self.assertNotEqual(receipt.pk, replay.pk)
            self.assertEqual((replay.rows, replay.created, replay.duplicates), (2, 0, 2))
            if kind == 'price': self.assertEqual(replay.unmatched, 2)
            self.assertContains(second, reverse('staff_import_receipt_detail', args=[replay.pk]))
        self.assertEqual(ProductCandidate.objects.count(), 2)
        self.assertEqual(PriceCandidate.objects.count(), 2)
        self.assertEqual(ProductPresentation.objects.count(), 0)

    def test_price_receipt_counts_are_recomputed_for_replayed_rows(self):
        self.client.force_login(self.price_author)
        self.upload('price')
        first = ImportReceipt.objects.get()
        self.assertEqual((first.suggested, first.unmatched), (0, 2))
        ProductPresentation.objects.create(name_fa='محصول فرضی', manufacturer='سازنده فرضی', strength='100 mg',
            dosage_form='قرص', package_description='10 عدد', irc='000000001', source_name='مثال',
            source_url='https://example.org/catalog')
        self.upload('price')
        second = ImportReceipt.objects.latest('pk')
        self.assertEqual((second.created, second.duplicates), (0, 2))
        self.assertEqual((second.suggested, second.ambiguous, second.unmatched), (1, 0, 1))
        self.assertEqual(PriceCandidate.objects.get(source_record_id='synthetic-1').match_status, 'unmatched')

    def test_preview_invalid_and_unattested_do_not_write_receipts(self):
        for kind, author in [('product', self.product_author), ('price', self.price_author)]:
            self.client.force_login(author)
            preview = self.upload(kind, action='preview', rights=False)
            self.assertContains(preview, 'نتیجه بررسی آزمایشی')
            self.assertNotContains(preview, 'مشاهده رسید این ثبت')
            self.upload(kind, rights=False)
            self.upload(kind, file=b'bad,csv\n1,2\n')
        self.assertEqual(ImportReceipt.objects.count(), 0)
        self.assertEqual(ProductCandidate.objects.count(), 0); self.assertEqual(PriceCandidate.objects.count(), 0)

    def test_atomic_rollback_when_receipt_or_staging_fails(self):
        for kind, author, model, service, file in [('product', self.product_author, ProductCandidate, stage_product_with_receipt, PRODUCT),
                                                   ('price', self.price_author, PriceCandidate, stage_price_with_receipt, PRICE)]:
            with self.subTest(kind=kind):
                with patch('ingestion.receipts.ImportReceipt.objects.create', side_effect=RuntimeError('synthetic failure')):
                    with self.assertRaises(RuntimeError):
                        service(io.BytesIO(file), 'نمونه', 'https://example.org', actor=author, rights_attested=True)
                self.assertEqual(model.objects.count(), 0); self.assertEqual(ImportReceipt.objects.count(), 0)
                original = model.objects.get_or_create
                counter = [0]
                def fail_second(*args, **kwargs):
                    counter[0] += 1
                    if counter[0] == 2: raise RuntimeError('synthetic row error')
                    return original(*args, **kwargs)
                with patch.object(model.objects, 'get_or_create', side_effect=fail_second):
                    with self.assertRaises(RuntimeError):
                        service(io.BytesIO(file), 'نمونه', 'https://example.org', actor=author, rights_attested=True)
                self.assertEqual(model.objects.count(), 0); self.assertEqual(ImportReceipt.objects.count(), 0)

    def test_service_permission_and_attestation_gates(self):
        for actor in [self.product_viewer, self.price_viewer, self.source_viewer, self.regular, self.inactive, None]:
            for service, content in [(stage_product_with_receipt, PRODUCT), (stage_price_with_receipt, PRICE)]:
                with self.subTest(actor=actor, service=service), self.assertRaises(PermissionDenied):
                    service(io.BytesIO(content), 'Synthetic', 'https://example.org', actor=actor, rights_attested=True)
        for service, content, author in [(stage_product_with_receipt, PRODUCT, self.product_author),
                                         (stage_price_with_receipt, PRICE, self.price_author)]:
            with self.assertRaises(ValueError):
                service(io.BytesIO(content), 'Synthetic', 'https://example.org', actor=author, rights_attested=False)
        self.assertFalse(ImportReceipt.objects.exists())

    def test_legacy_direct_services_and_cli_do_not_create_receipts(self):
        stage_products(io.BytesIO(PRODUCT), 'نمونه', 'https://example.org', actor=self.product_author, commit=True, rights_attested=True)
        stage_csv(io.BytesIO(PRICE), 'نمونه', 'https://example.org', staged_by=self.price_author, commit=True, rights_attested=True)
        call_command('stage_price_csv', str(ROOT / 'examples/price_candidates.synthetic.csv'), source_name='Synthetic',
                     source_url='https://example.org/other', commit=True, attest_authorized=True, stdout=io.StringIO())
        self.assertEqual(ProductCandidate.objects.count(), 2); self.assertEqual(PriceCandidate.objects.count(), 4)
        self.assertEqual(ImportReceipt.objects.count(), 0)

    def test_domain_permission_filters_detail_and_no_count_leak(self):
        product, price = self.stage_both()
        index = reverse('staff_import_receipts')
        response = self.client.get(index)  # still logged in, authorized price author
        self.assertContains(response, 'price ساختگی'); self.assertNotContains(response, 'product ساختگی')
        for user, allowed, forbidden in [(self.product_viewer, product, price), (self.price_viewer, price, product), (self.group_viewer, product, price)]:
            self.client.force_login(user)
            response = self.client.get(index)
            self.assertEqual(response.status_code, 200); self.assert_private(response)
            self.assertEqual(response.context['page'].paginator.count, 1)
            self.assertContains(response, allowed.source_name); self.assertNotContains(response, forbidden.source_name)
            self.assertEqual(self.client.get(reverse('staff_import_receipt_detail', args=[allowed.pk])).status_code, 200)
            self.assertEqual(self.client.get(reverse('staff_import_receipt_detail', args=[forbidden.pk])).status_code, 404)
            self.assertEqual(self.client.get(index, {'kind': forbidden.kind}).status_code, 403)
        self.client.force_login(self.both_viewer)
        self.assertEqual(self.client.get(index).context['page'].paginator.count, 2)
        self.assertEqual(self.client.get(index, {'kind': 'product'}).context['page'].paginator.count, 1)
        self.assertEqual(self.client.get(index, {'kind': 'price'}).context['page'].paginator.count, 1)
        self.assertEqual(self.client.get(index, {'kind': '<script>'}).status_code, 400)
        self.assertEqual(self.client.get(reverse('staff_import_receipt_detail', args=[9223372036854775808])).status_code, 404)
        self.assertEqual(self.client.head(index).status_code, 200)
        self.assertEqual(self.client.post(index).status_code, 405)
        self.assertEqual(self.client.post(reverse('staff_import_receipt_detail', args=[price.pk])).status_code, 405)
        for user in [self.source_viewer, self.regular]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(index).status_code, 403)
            self.assertEqual(self.client.get(reverse('staff_import_receipt_detail', args=[product.pk])).status_code, 403)
        self.client.force_login(self.inactive)
        self.assertEqual(self.client.get(index).status_code, 302)
        self.client.logout(); response = self.client.get(index)
        self.assertEqual(response.status_code, 302); self.assert_private(response)

    def test_pagination_escaping_and_public_exclusion(self):
        self.client.force_login(self.product_author)
        self.upload('product', name='<script>alert(1)</script>')
        receipt = ImportReceipt.objects.get()
        for _ in range(24): self.upload('product', name='<script>alert(1)</script>')
        page = self.client.get(reverse('staff_import_receipts'), {'kind': 'product'})
        self.assertEqual(len(page.context['page']), 20)
        self.assertContains(page, 'kind=product&amp;page=2')
        self.assertNotContains(page, '<script>alert(1)</script>')
        self.assertContains(page, '&lt;script&gt;')
        self.assertEqual(len(self.client.get(reverse('staff_import_receipts'), {'kind': 'product', 'page': 2}).context['page']), 5)
        detail = self.client.get(reverse('staff_import_receipt_detail', args=[receipt.pk]))
        self.assert_private(detail); self.assertContains(detail, '&lt;script&gt;'); self.assertNotContains(detail, '<script>')
        self.assertNotContains(detail, 'href="https://example.org/product"')
        self.assertNotContains(self.client.get(reverse('sitemap')), '/staff/')
        self.assertEqual(self.client.get(reverse('search_api'), {'q': 'فرآورده ساختگی'}).json()['data'], [])

    def test_csrf_and_ordinary_immutability_guards(self):
        client = Client(enforce_csrf_checks=True); client.force_login(self.product_author)
        url = reverse('staff_product_upload')
        def data():
            return {'source_name': 'نمونه', 'source_url': 'https://example.org', 'action': 'stage', 'rights_attested': 'on',
                    'csv_file': SimpleUploadedFile('synthetic.csv', PRODUCT, content_type='text/csv')}
        self.assertEqual(client.post(url, data()).status_code, 403)
        self.assertEqual(ImportReceipt.objects.count(), 0)
        client.get(url); payload = data(); payload['csrfmiddlewaretoken'] = client.cookies['csrftoken'].value
        self.assertEqual(client.post(url, payload).status_code, 200)
        receipt = ImportReceipt.objects.get()
        with self.assertRaises(ValidationError): receipt.save()
        with self.assertRaises(ValidationError): receipt.delete()

    def test_database_constraints_and_no_default_receipt_permissions(self):
        self.assertFalse(Permission.objects.filter(content_type__app_label='ingestion', content_type__model='importreceipt').exists())
        base = dict(source_name='نمونه', source_url='https://example.org', actor=self.product_author,
                    kind='product', rows=1, created=1, duplicates=0)
        invalid = [dict(rows=0, created=0), dict(rows=2), dict(kind='unknown'), dict(rows=1001, created=1001),
                   dict(suggested=0), dict(kind='price', suggested=None, ambiguous=0, unmatched=1),
                   dict(kind='price', suggested=1, ambiguous=1, unmatched=0), dict(duplicates=-1)]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                ImportReceipt.objects.create(**(base | changes))
        self.assertEqual(ImportReceipt.objects.count(), 0)

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_debug_gate(self):
        self.client.force_login(self.product_author)
        for name, args in [('staff_import_receipts', []), ('staff_import_receipt_detail', [1])]:
            for method in [self.client.get, self.client.post]:
                response = method(reverse(name, args=args)); self.assertEqual(response.status_code, 404); self.assert_private(response)
