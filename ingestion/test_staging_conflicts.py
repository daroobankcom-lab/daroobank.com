"""Selected source-staging conflict behavior with synthetic PostgreSQL data."""
import io
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command, CommandError
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from catalog.models import ProductCandidate
from ingestion.exceptions import StagingConflict
from ingestion.locks import lock_source_stage
from ingestion.models import ImportReceipt, ImportReceiptItem
from pricing.models import PriceCandidate

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = (ROOT / 'examples/product_candidates.synthetic.csv').read_bytes()
PRICE = (ROOT / 'examples/price_candidates.synthetic.csv').read_bytes()


class DriverFailure(Exception):
    def __init__(self, code):
        self.sqlstate = code


def fail_with(code):
    try:
        raise DriverFailure(code)
    except DriverFailure as exc:
        raise OperationalError('private synthetic driver detail') from exc


@override_settings(STAFF_PORTAL_ENABLED=True)
class StagingConflictTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('staging-conflict', is_staff=True)
        for app, codes in [('catalog', ['view_productcandidate', 'add_productcandidate']),
                           ('pricing', ['view_pricecandidate', 'add_pricecandidate'])]:
            self.user.user_permissions.add(*Permission.objects.filter(content_type__app_label=app, codename__in=codes))
        self.url = 'https://example.org/staging-conflict'

    def test_real_advisory_lock_timeout_renders_private_http_conflict(self):
        self.client.force_login(self.user)
        from ingestion.receipts import stage_product_with_receipt, stage_price_with_receipt
        cases = [('product', 'staff_product_upload', PRODUCT, 'catalog.staff_views.stage_product_with_receipt', stage_product_with_receipt),
                 ('price', 'staff_price_upload', PRICE, 'pricing.staff_views.stage_price_with_receipt', stage_price_with_receipt)]
        for domain, route, data, target, service in cases:
            with self.subTest(domain=domain):
                def configured(*args, **kwargs):
                    with connection.cursor() as cursor:
                        cursor.execute("SET lock_timeout = '300ms'")
                        cursor.execute("SET statement_timeout = '8s'")
                    return service(*args, **kwargs)
                def post():
                    close_old_connections()
                    try:
                        return self.client.post(reverse(route), {'source_name': 'منبع ساختگی', 'source_url': self.url,
                            'action': 'stage', 'rights_attested': 'on',
                            'csv_file': SimpleUploadedFile('synthetic.csv', data, content_type='text/csv')})
                    finally:
                        connection.close()
                with patch(target, side_effect=configured), ThreadPoolExecutor(max_workers=1) as pool:
                    with transaction.atomic():
                        lock_source_stage(domain, self.url)
                        response = pool.submit(post).result(timeout=10)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                self.assertContains(response, 'فایل را دوباره انتخاب کنید', status_code=409)
                self.assertContains(response, 'role="alert"', status_code=409)
                self.assertNotContains(response, 'lock timeout', status_code=409)
                self.assertFalse(ProductCandidate.objects.exists())
                self.assertFalse(PriceCandidate.objects.exists())
                self.assertFalse(ImportReceipt.objects.exists())
                self.assertFalse(ImportReceiptItem.objects.exists())

    def test_selected_errors_roll_back_candidate_and_full_receipt_before_http_response(self):
        from ingestion.receipts import _write_items
        self.client.force_login(self.user)
        cases = [('product', 'staff_product_upload', PRODUCT, ProductCandidate),
                 ('price', 'staff_price_upload', PRICE, PriceCandidate)]
        for domain, route, data, model in cases:
            for location in ('second_candidate', 'manifest_written'):
                for code in ('55P03', '40P01', '40001'):
                    with self.subTest(domain=domain, location=location, code=code):
                        original = model.objects.get_or_create
                        count = [0]
                        def fail_second(*args, **kwargs):
                            count[0] += 1
                            if count[0] == 2:
                                fail_with(code)
                            return original(*args, **kwargs)
                        def fail_after_manifest(*args, **kwargs):
                            _write_items(*args, **kwargs)
                            self.assertGreater(ImportReceiptItem.objects.count(), 0)
                            fail_with(code)
                        target = (f'{model.__module__}.{model.__name__}.objects.get_or_create'
                                  if location == 'second_candidate' else 'ingestion.receipts._write_items')
                        with patch(target, side_effect=fail_second if location == 'second_candidate' else fail_after_manifest):
                            response = self.client.post(reverse(route), {
                                'source_name': 'منبع ساختگی', 'source_url': self.url, 'action': 'stage',
                                'rights_attested': 'on',
                                'csv_file': SimpleUploadedFile('synthetic.csv', data, content_type='text/csv')})
                        self.assertEqual(response.status_code, 409)
                        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                        self.assertContains(response, 'فایل را دوباره انتخاب کنید', status_code=409)
                        self.assertNotContains(response, 'private synthetic driver detail', status_code=409)
                        self.assertNotContains(response, 'staff-upload-result', status_code=409)
                        self.assertFalse(ProductCandidate.objects.exists())
                        self.assertFalse(PriceCandidate.objects.exists())
                        self.assertFalse(ImportReceipt.objects.exists())
                        self.assertFalse(ImportReceiptItem.objects.exists())

    def test_unknown_database_errors_are_not_misclassified(self):
        from ingestion.receipts import stage_product_with_receipt, stage_price_with_receipt
        for service, data in ((stage_product_with_receipt, PRODUCT), (stage_price_with_receipt, PRICE)):
            with self.subTest(service=service.__name__), patch('ingestion.receipts._write_items', side_effect=lambda *a: fail_with('23505')):
                with self.assertRaises(OperationalError):
                    service(io.BytesIO(data), 'منبع ساختگی', self.url, actor=self.user, rights_attested=True)
                self.assertFalse(ProductCandidate.objects.exists())
                self.assertFalse(PriceCandidate.objects.exists())
                self.assertFalse(ImportReceipt.objects.exists())
                self.assertFalse(ImportReceiptItem.objects.exists())

    def test_preview_price_conflict_is_not_reported_as_invalid_file(self):
        self.client.force_login(self.user)
        with patch('pricing.importer._load_irc_index', side_effect=lambda *a, **kw: fail_with('40001')):
            response = self.client.post(reverse('staff_price_upload'), {
                'source_name': 'منبع ساختگی', 'source_url': self.url, 'action': 'preview',
                'csv_file': SimpleUploadedFile('synthetic.csv', PRICE, content_type='text/csv')})
        self.assertContains(response, 'فایل را دوباره انتخاب کنید', status_code=409)
        self.assertNotContains(response, 'فایل معتبر نیست', status_code=409)
        self.assertFalse(PriceCandidate.objects.exists())
        self.assertFalse(ImportReceipt.objects.exists())

    def test_cli_reports_staging_conflict_without_driver_details(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch('pricing.management.commands.stage_price_csv.stage_csv', side_effect=StagingConflict('تداخل ساختگی')):
            with self.assertRaises(CommandError) as caught:
                call_command('stage_price_csv', 'synthetic.csv', source_name='منبع ساختگی',
                             source_url=self.url, commit=True, attest_authorized=True, stdout=output, stderr=errors)
        self.assertEqual(str(caught.exception), 'تداخل ساختگی')
        self.assertNotIn('STAGED', output.getvalue())
        self.assertFalse(PriceCandidate.objects.exists())

    def test_failed_new_receipt_preserves_previous_committed_receipt_and_candidates(self):
        from ingestion.receipts import _write_items, stage_product_with_receipt, stage_price_with_receipt
        for service, data, model in ((stage_product_with_receipt, PRODUCT, ProductCandidate),
                                     (stage_price_with_receipt, PRICE, PriceCandidate)):
            with self.subTest(service=service.__name__):
                _, old_receipt = service(io.BytesIO(data), 'منبع ساختگی', self.url,
                                         actor=self.user, rights_attested=True)
                ids = set(model.objects.values_list('pk', flat=True))
                item_ids = set(old_receipt.items.values_list('pk', flat=True))
                def fail_after_items(*args, **kwargs):
                    _write_items(*args, **kwargs)
                    fail_with('40001')
                with patch('ingestion.receipts._write_items', side_effect=fail_after_items):
                    with self.assertRaises(StagingConflict) as caught:
                        service(io.BytesIO(data), 'منبع ساختگی', self.url + '/new',
                                actor=self.user, rights_attested=True)
                self.assertEqual(caught.exception.__cause__.__cause__.sqlstate, '40001')
                self.assertEqual(set(model.objects.values_list('pk', flat=True)), ids)
                self.assertEqual(set(old_receipt.items.values_list('pk', flat=True)), item_ids)
                self.assertEqual(ImportReceipt.objects.filter(kind=old_receipt.kind).count(), 1)
