"""Selected review-writer error boundaries with synthetic PostgreSQL data."""
import io
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import DatabaseError, OperationalError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.intake import review_product, stage_products
from catalog.models import ProductCandidate, ProductCandidateReview
from catalog.test_intake import make_csv
from clinical.evidence import evidence_state
from clinical.models import ClinicalDraftReview
from clinical.services import create_draft, review_draft
from pricing.importer import stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.reviews import record_preliminary_review
from pricing.test_workflow import csv_bytes
from sources.models import SourceClaimReview
from sources.services import record_claim, review_claim
from .write_conflict_boundary import write_conflict_boundary


class DriverFailure(Exception):
    def __init__(self, code, attribute='sqlstate'):
        setattr(self, attribute, code)


def fail_with(code, attribute='sqlstate'):
    try:
        raise DriverFailure(code, attribute)
    except DriverFailure as exc:
        raise OperationalError('sensitive synthetic driver detail') from exc


@override_settings(STAFF_PORTAL_ENABLED=True)
class ReviewWriteBoundaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('boundary-conflict-author', is_staff=True)
        cls.reviewer = User.objects.create_user('boundary-conflict-reviewer', is_staff=True)
        for user in (cls.author, cls.reviewer):
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=['catalog', 'pricing', 'sources', 'clinical']))
        cls.claim, _ = record_claim(actor=cls.author, data=dict(source_name='منبع ساختگی',
            source_url='https://example.org/source', owner='مالک فرضی', evidence_url='https://example.org/evidence',
            evidence_note='', claims_collection=True, claims_storage=False, claims_publication=False,
            starts_on=None, expires_on=None))
        cls.draft = create_draft(actor=cls.author, data=dict(subject='موضوع فرضی', audience='patient',
            title='عنوان ساختگی', statement='گزاره ساختگی صرفاً برای آزمون', reference_title='ارجاع فرضی',
            reference_url='https://example.org/reference', reference_location='بخش فرضی', reference_author='',
            reference_version='', reference_published_on=None, reference_accessed_on=None))
        product = dict(source_record_id='one', name_fa='فرآورده فرضی', name_en='Synthetic', manufacturer='سازنده فرضی',
                       strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
        stage_products(io.BytesIO(make_csv([product])), 'منبع ساختگی', 'https://example.org/product',
                       actor=cls.author, commit=True, rights_attested=True)
        cls.product = ProductCandidate.objects.get()
        price = dict(source_record_id='one', irc='001', manufacturer='سازنده فرضی', strength='5 mg',
                     dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
                     category='retail', unit='package', effective_date='', source_published_date='')
        stage_csv(io.BytesIO(csv_bytes([price])), 'منبع ساختگی', 'https://example.org/price',
                  staged_by=cls.author, commit=True, rights_attested=True)
        cls.price = PriceCandidate.objects.get()

    def cases(self):
        common = dict(decision='defer', reason='دلیل ساختگی برای بررسی اولیه', expected_review=0)
        return [
            (self.claim, 'owner', SourceClaimReview, review_claim, 'sources.services.SourceClaimReview.objects.create',
             'claim_id', 'staff_source_review', {**common, 'expected_hash': self.claim.payload_sha256}),
            (self.draft, 'title', ClinicalDraftReview, review_draft, 'clinical.services.ClinicalDraftReview.objects.create',
             'draft_id', 'staff_clinical_review', {**common, 'expected_hash': self.draft.payload_sha256,
                                                    'expected_evidence_hash': evidence_state(self.draft)['fingerprint']}),
            (self.product, 'source_name', ProductCandidateReview, review_product, 'catalog.intake.ProductCandidateReview.objects.create',
             'candidate_id', 'staff_product_review', {**common, 'expected_hash': self.product.payload_sha256}),
            (self.price, 'source_name', PriceCandidateReview, record_preliminary_review, 'pricing.reviews.PriceCandidateReview.objects.create',
             'candidate_id', 'staff_price_review', {**common, 'expected_product': 0, 'expected_product_hash': ''}),
        ]

    def test_selected_states_are_translated_after_savepoint_rollback(self):
        for obj, field, review_model, service, target, id_key, _, data in self.cases():
            for code in ('55P03', '40P01', '40001'):
                with self.subTest(model=obj.__class__.__name__, code=code):
                    original = getattr(obj, field)
                    def mutate_and_fail(**kwargs):
                        obj.__class__.objects.filter(pk=obj.pk).update(**{field: 'تغییر موقت ساختگی'})
                        fail_with(code)
                    with patch(target, side_effect=mutate_and_fail):
                        with self.assertRaises(ValueError) as caught:
                            service(actor=self.reviewer, **{id_key: obj.pk}, **data)
                    self.assertEqual(caught.exception.__class__.__module__, service.__module__)
                    self.assertIn(caught.exception.__class__.__name__, ('ReviewConflict', 'DraftConflict'))
                    self.assertEqual(str(caught.exception), 'ثبت به دلیل تداخل هم‌زمان انجام نشد؛ دوباره تلاش کنید.')
                    self.assertIsInstance(caught.exception.__cause__, OperationalError)
                    obj.refresh_from_db()
                    self.assertEqual(getattr(obj, field), original)
                    self.assertFalse(review_model.objects.exists())

    def test_http_conflicts_are_private_and_do_not_echo_driver_details(self):
        self.client.force_login(self.reviewer)
        for obj, _, model, _, target, _, route, data in self.cases():
            with self.subTest(model=obj.__class__.__name__), patch(target, side_effect=lambda **kw: fail_with('40P01')):
                response = self.client.post(reverse(route, args=[obj.pk]), data)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                self.assertContains(response, 'ثبت به دلیل تداخل هم‌زمان انجام نشد', status_code=409)
                self.assertNotContains(response, 'sensitive synthetic driver detail', status_code=409)
                self.assertFalse(model.objects.exists())

    def test_unselected_database_errors_and_non_database_errors_are_not_masked(self):
        for code in ('23505', None):
            with self.subTest(code=code), self.assertRaises(OperationalError):
                with write_conflict_boundary(ValueError):
                    fail_with(code)
        with self.assertRaisesRegex(RuntimeError, 'unrelated'):
            with write_conflict_boundary(ValueError):
                raise RuntimeError('unrelated')
        with self.assertRaises(ValueError) as caught:
            with write_conflict_boundary(ValueError):
                fail_with('55P03', 'pgcode')
        self.assertIsInstance(caught.exception.__cause__, DatabaseError)
        self.assertFalse(transaction.get_connection().needs_rollback)
