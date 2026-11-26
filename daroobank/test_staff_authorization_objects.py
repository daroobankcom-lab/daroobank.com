"""Staff authorization against existing rows; synthetic evidence, not a review.

`test_staff_authorization_matrix.py` probes every route with a missing primary
key, which shows whether a permission check runs but not what an account sees
when the row exists. This suite repeats the matrix against real synthetic rows so
that:

* an unauthorized account still gets 403 rather than a 404 or content, so the
  route does not turn existence into an oracle;
* an authorized account reaches the row (never 403, never 404);
* no probe writes or deletes anything.

It remains a record of current behavior on a development-only portal with
synthetic data, not an authorization design review.
"""
import io
import types
from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.identity import create_ingredient
from catalog.intake import stage_products
from catalog.models import IdentityPackageDraft, IdentityPackageReview, IngredientDraft, ProductCandidate, ProductCandidateReview, ProductPresentation
from catalog.test_identity import PACKAGE, build
from catalog.test_intake import make_csv
from clinical.models import ClinicalDraft, ClinicalDraftReview, ClinicalReferenceAssertion
from clinical.services import create_draft
from ingestion.models import ImportReceipt, ImportReceiptItem
from ingestion.receipts import stage_product_with_receipt
from pricing.importer import stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.test_workflow import csv_bytes
from sources.models import SourceClaim, SourceClaimReview
from sources.services import record_claim

from .test_staff_authorization_matrix import (ALL_PERMISSIONS, CLAIM, DRAFT, IDENTITY, PRESENTATION, PRICE,
                                              PRODUCT, ROUTES, STAFF_ONLY, VIEW_PERMISSIONS, satisfies)

PRODUCT_ROW = dict(source_record_id='one', name_fa='فرآورده فرضی', name_en='Synthetic', manufacturer='سازنده فرضی',
                   strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
PRICE_ROW = dict(source_record_id='one', irc='001', manufacturer='سازنده فرضی', strength='5 mg',
                 dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
                 category='retail', unit='package', effective_date='', source_published_date='')
DRAFT_DATA = {'subject': 'موضوع فرضی', 'audience': 'patient', 'title': 'عنوان ساختگی',
              'statement': 'گزاره ساختگی صرفاً برای آزمون', 'reference_title': 'ارجاع فرضی',
              'reference_url': 'https://example.org/reference', 'reference_location': 'بخش فرضی',
              'reference_author': '', 'reference_version': '', 'reference_published_on': None,
              'reference_accessed_on': None}
CLAIM_DATA = {'source_name': 'منبع ساختگی', 'source_url': 'https://example.org/matrix-object',
              'owner': 'مالک فرضی', 'evidence_url': 'https://example.org/evidence', 'evidence_note': '',
              'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
              'starts_on': None, 'expires_on': None}
PRESENTATION_FIELDS = dict(name_fa='نام ساختگی محرمانه', name_en='Private synthetic name',
                           manufacturer='سازنده فرضی', strength='۵ میلی‌گرم', dosage_form='قرص',
                           package_description='۱۰ عدد', irc='۰۰۱', source_name='منبع ساختگی',
                           source_url='https://example.org/private',
                           verified_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc))
COUNTED_MODELS = (SourceClaim, SourceClaimReview, ProductCandidate, ProductCandidateReview, PriceCandidate,
                  PriceCandidateReview, ClinicalDraft, ClinicalDraftReview, ClinicalReferenceAssertion,
                  IngredientDraft, IdentityPackageDraft, IdentityPackageReview, ImportReceipt, ImportReceiptItem,
                  ProductPresentation)


def build_object_rows(author):
    """Create one real row per object route through the normal services.

    Shared with `test_staff_denial_parity.py` so both suites compare the same
    rows. Returns a namespace; the caller supplies a fully permitted author.
    """
    rows = types.SimpleNamespace()
    rows.claim = record_claim(actor=author, data=dict(CLAIM_DATA))[0]
    stage_products(io.BytesIO(make_csv([PRODUCT_ROW])), 'منبع ساختگی', 'https://example.org/matrix-product',
                   actor=author, commit=True, rights_attested=True)
    rows.candidate = ProductCandidate.objects.get()
    stage_csv(io.BytesIO(csv_bytes([PRICE_ROW])), 'منبع ساختگی', 'https://example.org/matrix-price',
              staged_by=author, commit=True, rights_attested=True)
    rows.price = PriceCandidate.objects.get()
    rows.draft = create_draft(actor=author, data=dict(DRAFT_DATA))
    rows.ingredient, _part, _form, _product, rows.package = build(author)
    rows.presentation = ProductPresentation.objects.create(**PRESENTATION_FIELDS, published=True)
    _counts, rows.receipt = stage_product_with_receipt(
        io.BytesIO(make_csv([dict(PRODUCT_ROW, source_record_id='two')])), 'منبع ساختگی',
        'https://example.org/matrix-receipt', actor=author, rights_attested=True)
    return rows


OBJECT_ROUTES = (
        'staff_source_detail', 'staff_source_review_inspection', 'staff_source_review',
        'staff_product_detail', 'staff_product_review_inspection', 'staff_product_review',
        'staff_price_detail', 'staff_price_review_inspection', 'staff_price_review',
        'staff_clinical_detail', 'staff_clinical_review_inspection', 'staff_clinical_lineage',
        'staff_clinical_revise', 'staff_clinical_reference_create', 'staff_clinical_review',
        'staff_identity_detail', 'staff_identity_lineage', 'staff_identity_revise_component',
        'staff_identity_revise', 'staff_identity_review', 'staff_catalog_quality_irc',
        'staff_import_receipt_detail', 'staff_import_manifest_inspection',
)


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffAuthorizationObjectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.outsider = User.objects.create_user('object-outsider', password='synthetic-only')
        cls.bare = User.objects.create_user('object-bare-staff', password='synthetic-only', is_staff=True)
        cls.viewer = User.objects.create_user('object-view-staff', password='synthetic-only', is_staff=True)
        cls.viewer.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in VIEW_PERMISSIONS]))
        cls.full = User.objects.create_user('object-full-staff', password='synthetic-only', is_staff=True)
        cls.full.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))

        author = User.objects.create_user('object-author', password='synthetic-only', is_staff=True)
        author.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        rows = build_object_rows(author)
        cls.claim, cls.candidate, cls.price, cls.draft = rows.claim, rows.candidate, rows.price, rows.draft
        cls.ingredient, cls.package = rows.ingredient, rows.package
        cls.presentation, cls.receipt = rows.presentation, rows.receipt

    OBJECT_ROUTES = OBJECT_ROUTES

    def kwargs_for(self, name):
        objects = {
            'staff_source_detail': {'pk': self.claim.pk},
            'staff_source_review_inspection': {'pk': self.claim.pk},
            'staff_source_review': {'pk': self.claim.pk},
            'staff_product_detail': {'pk': self.candidate.pk},
            'staff_product_review_inspection': {'pk': self.candidate.pk},
            'staff_product_review': {'pk': self.candidate.pk},
            'staff_price_detail': {'pk': self.price.pk},
            'staff_price_review_inspection': {'pk': self.price.pk},
            'staff_price_review': {'pk': self.price.pk},
            'staff_clinical_detail': {'pk': self.draft.pk},
            'staff_clinical_review_inspection': {'pk': self.draft.pk},
            'staff_clinical_lineage': {'pk': self.draft.pk},
            'staff_clinical_revise': {'pk': self.draft.pk},
            'staff_clinical_reference_create': {'pk': self.draft.pk},
            'staff_clinical_review': {'pk': self.draft.pk},
            'staff_identity_detail': {'kind': 'package', 'pk': self.package.pk},
            'staff_identity_lineage': {'kind': 'package', 'pk': self.package.pk},
            'staff_identity_revise_component': {'kind': 'ingredient', 'pk': self.ingredient.pk},
            'staff_identity_revise': {'pk': self.package.pk},
            'staff_identity_review': {'pk': self.package.pk},
            'staff_catalog_quality_irc': {'pk': self.presentation.pk},
            'staff_import_receipt_detail': {'pk': self.receipt.pk},
            'staff_import_manifest_inspection': {'pk': self.receipt.pk},
        }
        return objects[name]

    def object_routes(self):
        # Only routes whose argument identifies a stored row; `staff_identity_create`
        # takes a kind, not an object, and stays in the missing-key matrix.
        return [(name, self.kwargs_for(name), method, requirement)
                for name, _kwargs, method, requirement in ROUTES if name in self.OBJECT_ROUTES]

    def counts(self):
        return {model: model.objects.count() for model in COUNTED_MODELS}

    def request(self, account, name, kwargs, method):
        client = self.client_class()
        if account is not None:
            client.force_login(account)
        url = reverse(name, kwargs=kwargs)
        return client.get(url) if method == 'GET' else client.post(url, {})

    def test_object_routes_are_exactly_the_routes_that_take_a_primary_key(self):
        self.assertEqual(len(self.object_routes()), 23)
        self.assertEqual(set(self.OBJECT_ROUTES),
                         {name for name, kwargs, _method, _requirement in ROUTES if 'pk' in kwargs})
        self.assertEqual(len(set(self.OBJECT_ROUTES)), len(self.OBJECT_ROUTES))

    def test_anonymous_requests_are_redirected_even_when_the_row_exists(self):
        login = reverse('staff_login')
        for name, kwargs, method, _requirement in self.object_routes():
            with self.subTest(route=name):
                response = self.request(None, name, kwargs, method)
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response['Location'].startswith(login))

    def test_unauthorized_accounts_get_403_rather_than_a_existence_oracle(self):
        for account in (self.outsider, self.bare, self.viewer):
            for name, kwargs, method, requirement in self.object_routes():
                if satisfies(account, requirement):
                    continue
                with self.subTest(account=account.username, route=name):
                    response = self.request(account, name, kwargs, method)
                    self.assertEqual(response.status_code, 403,
                                     'An existing row must not change the denial into 404 or content.')

    def test_authorized_accounts_render_existing_rows(self):
        # Exact expectations: a GET renders the row (200) and a POST-only review
        # route rejects the deliberately empty form (400) only after reaching it.
        # Anything else - 403, 404, a login redirect or a silent 302 - means the
        # account never reached the row this suite created.
        for account in (self.viewer, self.full):
            for name, kwargs, method, requirement in self.object_routes():
                if not satisfies(account, requirement):
                    continue
                with self.subTest(account=account.username, route=name):
                    response = self.request(account, name, kwargs, method)
                    self.assertEqual(response.status_code, 200 if method == 'GET' else 400)
                    self.assertIn('no-store', response['Cache-Control'])
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    def test_a_permission_less_staff_account_is_denied_every_object_route(self):
        for name, kwargs, method, requirement in self.object_routes():
            self.assertNotEqual(requirement, STAFF_ONLY)
            with self.subTest(route=name):
                self.assertEqual(self.request(self.bare, name, kwargs, method).status_code, 403)

    def test_probing_every_object_route_writes_nothing(self):
        before = self.counts()
        for account in (None, self.outsider, self.bare, self.viewer, self.full):
            for name, kwargs, method, _requirement in self.object_routes():
                self.request(account, name, kwargs, method)
        self.assertEqual(self.counts(), before)

