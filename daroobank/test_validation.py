import io
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TestCase

from catalog.intake import IntakeError, ReviewConflict as ProductConflict, review_product, stage_products
from catalog.models import ProductCandidate, ProductCandidateReview
from pricing.importer import ImportValidationError, stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import ReviewConflict as PriceConflict, record_preliminary_review
from sources.services import ClaimError, validate_url
from .validation import valid_private_source_url, valid_review_reason

ROOT = Path(__file__).resolve().parent.parent
PRODUCT_CSV = (ROOT / 'examples/product_candidates.synthetic.csv').read_bytes()
PRICE_CSV = (ROOT / 'examples/price_candidates.synthetic.csv').read_bytes()


class SharedValidationTests(SimpleTestCase):
    def test_untrusted_urls_never_fetch_and_reject_secrets_and_invalid_unicode(self):
        good = ['https://example.org', 'https://example.org/feed%3Ftype', 'https://example.org/a%23b']
        bad = ['', 'http://example.org', 'https://u:p@example.org', 'https://@example.org',
               'https://example.org/?', 'https://example.org/?token=x', 'https://example.org/#',
               'https://example.org/#fragment', 'https://example.org/\ud800', 'https://example.org/a\n',
               'https://example.org/\x00', 'https://example.org/' + 'x' * 200, None]
        for url in good:
            self.assertTrue(valid_private_source_url(url), repr(url))
            validate_url(url)
        for url in bad:
            with self.subTest(url=ascii(url)):
                self.assertFalse(valid_private_source_url(url))
                with self.assertRaises(ClaimError): validate_url(url)

    def test_review_text_validation(self):
        self.assertTrue(valid_review_reason('متن اول به اندازه کافی\nمتن دوم'))
        for reason in [None, '', 'x' * 11, 'x' * 1001, 'x' * 12 + '\ud800', 'x' * 12 + '\x00', 'x' * 12 + '\x1b']:
            with self.subTest(reason=ascii(reason)):
                self.assertFalse(valid_review_reason(reason))


class ExistingIntakeHardeningTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('validation-author', is_staff=True)
        cls.reviewer = User.objects.create_user('validation-reviewer', is_staff=True)
        for app, model in [('catalog', 'productcandidate'), ('pricing', 'pricecandidate')]:
            cls.author.user_permissions.add(*Permission.objects.filter(content_type__app_label=app, codename__in=[f'view_{model}', f'add_{model}']))
            cls.reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label=app, codename__in=[f'view_{model}', f'review_{model}']))

    def test_staging_rejects_unsafe_source_urls_and_bad_names_before_writes(self):
        for url in ['https://@example.org', 'https://example.org/?', 'https://example.org/#', 'https://example.org/\ud800']:
            with self.subTest(url=ascii(url)):
                with self.assertRaises(IntakeError):
                    stage_products(io.BytesIO(PRODUCT_CSV), 'Synthetic', url, actor=self.author, commit=True, rights_attested=True)
                with self.assertRaises(ImportValidationError):
                    stage_csv(io.BytesIO(PRICE_CSV), 'Synthetic', url, staged_by=self.author, commit=True, rights_attested=True)
        for name in ['a\x00b', 'a\ud800b']:
            with self.subTest(name=ascii(name)):
                with self.assertRaises(IntakeError):
                    stage_products(io.BytesIO(PRODUCT_CSV), name, 'https://example.org', actor=self.author, commit=True, rights_attested=True)
                with self.assertRaises(ImportValidationError):
                    stage_csv(io.BytesIO(PRICE_CSV), name, 'https://example.org', staged_by=self.author, commit=True, rights_attested=True)
        self.assertEqual(ProductCandidate.objects.count(), 0)
        self.assertEqual(PriceCandidate.objects.count(), 0)

    def test_invalid_review_reasons_and_legacy_url_fail_closed(self):
        stage_products(io.BytesIO(PRODUCT_CSV), 'Synthetic', 'https://example.org', actor=self.author, commit=True, rights_attested=True)
        stage_csv(io.BytesIO(PRICE_CSV), 'Synthetic', 'https://example.org', staged_by=self.author, commit=True, rights_attested=True)
        product = ProductCandidate.objects.first()
        price = PriceCandidate.objects.first()
        def product_review(reason):
            return review_product(candidate_id=product.pk, actor=self.reviewer, decision='defer', reason=reason,
                                  expected_review=0, expected_hash=product.payload_sha256)
        def price_review(reason):
            return record_preliminary_review(candidate_id=price.pk, actor=self.reviewer, decision='defer', reason=reason,
                                             expected_review=0, expected_product=0, expected_product_hash='')
        for reason in ['a' * 12 + '\ud800', 'a' * 12 + '\x00']:
            with self.subTest(reason=ascii(reason)):
                with self.assertRaises(ProductConflict): product_review(reason)
                with self.assertRaises(PriceConflict): price_review(reason)
        ProductCandidate.objects.filter(pk=product.pk).update(source_url='https://example.org/?')
        PriceCandidate.objects.filter(pk=price.pk).update(source_url='https://example.org/?')
        with self.assertRaises(ProductConflict): product_review('دلیل ساختگی برای بررسی بیشتر')
        with self.assertRaises(PriceConflict): price_review('دلیل ساختگی برای بررسی بیشتر')
        self.assertEqual(ProductCandidateReview.objects.count(), 0)
        self.assertEqual(PriceCandidateReview.objects.count(), 0)
