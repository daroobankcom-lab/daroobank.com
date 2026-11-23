"""Short-read regressions for synthetic product and price CSV intake."""
import io
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.intake import IntakeError, parse_product_csv
from catalog.models import ProductCandidate
from pricing.importer import ImportValidationError, parse_csv
from pricing.models import PriceCandidate
from .models import ImportReceipt, ImportReceiptItem
from .receipts import stage_price_with_receipt, stage_product_with_receipt

ROOT = Path(__file__).resolve().parent.parent
PRODUCT = (ROOT / 'examples/product_candidates.synthetic.csv').read_bytes()
PRICE = (ROOT / 'examples/price_candidates.synthetic.csv').read_bytes()


class ShortReader:
    """A blocking binary stream allowed to return fewer bytes than requested."""
    def __init__(self, data):
        self.source = io.BytesIO(data)
        self.chunk = sum(len(line) for line in data.splitlines(keepends=True)[:2])

    def read(self, size):
        return self.source.read(min(size, self.chunk))


class ShortReadIntakeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user('short-read-actor', is_staff=True)
        for app, entity in [('catalog', 'productcandidate'), ('pricing', 'pricecandidate')]:
            cls.actor.user_permissions.add(*Permission.objects.filter(content_type__app_label=app,
                                           codename__in=[f'view_{entity}', f'add_{entity}']))

    def test_short_reads_include_all_rows_for_both_parsers(self):
        for parser, data in [(parse_product_csv, PRODUCT), (parse_csv, PRICE)]:
            with self.subTest(parser=parser.__name__):
                self.assertEqual(len(parser(ShortReader(data))), 2)

    def test_bad_tail_never_produces_partial_candidates_or_receipt(self):
        for service, error, data, model in [
            (stage_product_with_receipt, IntakeError, PRODUCT, ProductCandidate),
            (stage_price_with_receipt, ImportValidationError, PRICE, PriceCandidate),
        ]:
            with self.subTest(service=service.__name__):
                head = b''.join(data.splitlines(keepends=True)[:2])
                with self.assertRaises(error):
                    service(ShortReader(head + b'invalid,tail\n'), 'منبع ساختگی', 'https://example.org/feed',
                            actor=self.actor, rights_attested=True)
                self.assertEqual(model.objects.count(), 0)
                self.assertEqual(ImportReceipt.objects.count(), 0)
                self.assertEqual(ImportReceiptItem.objects.count(), 0)

    def test_successful_short_read_stages_every_row_and_manifest(self):
        for service, data, model in [
            (stage_product_with_receipt, PRODUCT, ProductCandidate),
            (stage_price_with_receipt, PRICE, PriceCandidate),
        ]:
            with self.subTest(service=service.__name__):
                counts, receipt = service(ShortReader(data), 'منبع ساختگی', 'https://example.org/feed',
                                          actor=self.actor, rights_attested=True)
                self.assertEqual((counts['rows'], receipt.rows, model.objects.count()), (2, 2, 2))
                self.assertEqual(receipt.items.count(), 2)

    def test_read_error_after_valid_prefix_aborts_both_receipt_paths(self):
        class NonblockingAfterPrefix:
            def __init__(self, data):
                self.prefix = b''.join(data.splitlines(keepends=True)[:2])
            def read(self, size):
                if self.prefix is not None:
                    result, self.prefix = self.prefix, None
                    return result
                return None
        for service, error, data, model in [
            (stage_product_with_receipt, IntakeError, PRODUCT, ProductCandidate),
            (stage_price_with_receipt, ImportValidationError, PRICE, PriceCandidate),
        ]:
            with self.subTest(service=service.__name__), self.assertRaises(error):
                service(NonblockingAfterPrefix(data), 'منبع ساختگی', 'https://example.org/feed',
                        actor=self.actor, rights_attested=True)
            self.assertEqual(model.objects.count(), 0)
            self.assertEqual(ImportReceipt.objects.count(), 0)
            self.assertEqual(ImportReceiptItem.objects.count(), 0)

    def test_size_limit_is_not_bypassed_by_short_reads(self):
        from unittest.mock import patch
        for parser, error, data, limit_name in [
            (parse_product_csv, IntakeError, PRODUCT, 'catalog.intake.MAX_FILE_BYTES'),
            (parse_csv, ImportValidationError, PRICE, 'pricing.importer.MAX_FILE_BYTES'),
        ]:
            with self.subTest(parser=parser.__name__), patch(limit_name, len(data) - 1):
                with self.assertRaises(error):
                    parser(ShortReader(data))

    @override_settings(STAFF_PORTAL_ENABLED=True)
    def test_http_read_failures_remain_private_and_do_not_reflect_details(self):
        self.client.force_login(self.actor)
        for route, data, helper in [
            ('staff_product_upload', PRODUCT, 'catalog.intake.read_bounded_bytes'),
            ('staff_price_upload', PRICE, 'pricing.importer.read_bounded_bytes'),
        ]:
            with self.subTest(route=route), patch(helper, side_effect=OSError('internal synthetic canary')):
                response = self.client.post(reverse(route), {
                    'source_name': 'منبع ساختگی', 'source_url': 'https://example.org/feed',
                    'action': 'stage', 'rights_attested': 'on',
                    'csv_file': SimpleUploadedFile('synthetic.csv', data, content_type='text/csv'),
                })
                self.assertEqual(response.status_code, 200)  # existing validation-error behavior
                self.assertContains(response, 'فایل معتبر نیست؛ هیچ داده‌ای ثبت نشد')
                self.assertNotContains(response, 'internal synthetic canary')
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertFalse(ProductCandidate.objects.exists())
        self.assertFalse(PriceCandidate.objects.exists())
        self.assertFalse(ImportReceipt.objects.exists())
        self.assertFalse(ImportReceiptItem.objects.exists())

    def test_price_cli_read_failure_is_validation_error_not_success(self):
        output = io.StringIO()
        with patch('pricing.importer.read_bounded_bytes', side_effect=OSError('synthetic canary')):
            with self.assertRaisesMessage(CommandError, 'Cannot read input file.'):
                call_command('stage_price_csv', str(ROOT / 'examples/price_candidates.synthetic.csv'),
                             source_name='نمونه', source_url='https://example.org/feed', stdout=output)
        self.assertNotIn('DRY RUN', output.getvalue())
        self.assertNotIn('synthetic canary', output.getvalue())
