"""Public-route inventory and private-data leakage matrix; synthetic evidence.

Every non-staff route is enumerated from the live URL resolver and probed with an
anonymous client and with a fully permitted staff client. Each probe asserts the
declared status, that no private staff marker reaches the body, and that the
known public read routes still carry their public privacy headers.

A published presentation carrying its own marker is the positive control: it must
appear, which is what makes the absence of the private markers meaningful.

This is a leakage regression test on synthetic data, not a privacy review, a data
classification decision or an approval to publish anything.
"""
import io
import json
from datetime import datetime, timezone as dt_timezone

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import get_resolver, reverse

from catalog.intake import stage_products
from catalog.models import ProductPresentation
from catalog.test_intake import make_csv
from clinical.models import ClinicalDraft
from clinical.services import create_draft
from ingestion.receipts import stage_product_with_receipt
from pricing.importer import stage_csv
from pricing.test_workflow import csv_bytes
from sources.services import record_claim

from .test_staff_authorization_matrix import ALL_PERMISSIONS

PUBLIC = 'MARKER-PUBLIC-PRESENTATION-7d41'
PRIVATE_MARKERS = {
    'claim_owner': 'MARKER-CLAIM-OWNER-7d41',
    'claim_note': 'MARKER-CLAIM-EVIDENCE-7d41',
    'claim_url': 'https://example.org/marker-claim-7d41',
    'product_source': 'https://example.org/marker-product-7d41',
    'product_row': 'MARKER-PRODUCT-ROW-7d41',
    'price_source': 'https://example.org/marker-price-7d41',
    'draft_statement': 'MARKER-CLINICAL-STATEMENT-7d41',
    'draft_title': 'MARKER-CLINICAL-TITLE-7d41',
    'identity_ingredient': 'MARKER-IDENTITY-INGREDIENT-7d41',
    'receipt_source': 'https://example.org/marker-receipt-7d41',
}

# label, route name, kwargs, query, expected status for both account shapes
PUBLIC_ROUTES = (
    ('home', 'home', {}, {}, 200),
    ('about', 'about', {}, {}, 200),
    ('prices', 'prices', {}, {}, 200),
    ('robots', 'robots', {}, {}, 200),
    ('sitemap', 'sitemap', {}, {}, 200),
    ('search', 'search', {}, {}, 200),
    ('search-for-private-candidate', 'search', {}, {'q': PRIVATE_MARKERS['product_row']}, 200),
    ('search-for-published-presentation', 'search', {}, {'q': PUBLIC}, 200),
    ('search-api', 'search_api', {}, {}, 200),
    ('search-api-for-private-draft', 'search_api', {}, {'q': PRIVATE_MARKERS['draft_title']}, 200),
    ('openapi', 'openapi_document', {}, {}, 200),
    ('presentation-detail', 'presentation_detail', {'pk': 'PRESENTATION'}, {}, 200),
    ('presentation-api', 'presentation_api', {'pk': 'PRESENTATION'}, {}, 200),
    ('presentation-detail-missing', 'presentation_detail', {'pk': 999_999_999}, {}, 404),
    ('presentation-api-missing', 'presentation_api', {'pk': 999_999_999}, {}, 404),
    ('health-live-disabled', 'health_live', {}, {}, 404),
    ('health-ready-disabled', 'health_ready', {}, {}, 404),
)
PUBLIC_HEADER_ROUTES = frozenset({'search', 'search_api', 'presentation_detail', 'presentation_api',
                                  'openapi_document'})
# These probes put a marker in the query string, which the page echoes back. They
# assert on the result set instead of marker absence, so that echoing is not
# mistaken for a leak.
QUERY_ECHO_ROUTES = frozenset({'search-for-private-candidate', 'search-api-for-private-draft',
                               'search-for-published-presentation'})


@override_settings(STAFF_PORTAL_ENABLED=True)
class PublicRoutePrivacyMatrixTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.staff = User.objects.create_user('public-matrix-staff', password='synthetic-only', is_staff=True)
        cls.staff.user_permissions.add(*Permission.objects.filter(codename__in=[c for _a, c in ALL_PERMISSIONS]))
        author = cls.staff

        record_claim(actor=author, data={'source_name': 'منبع ساختگی', 'source_url': PRIVATE_MARKERS['claim_url'],
                     'owner': PRIVATE_MARKERS['claim_owner'], 'evidence_url': 'https://example.org/marker-evidence',
                     'evidence_note': PRIVATE_MARKERS['claim_note'], 'claims_collection': True,
                     'claims_storage': False, 'claims_publication': False, 'starts_on': None, 'expires_on': None})
        stage_products(io.BytesIO(make_csv([dict(source_record_id='one', name_fa=PRIVATE_MARKERS['product_row'],
                       name_en='Synthetic', manufacturer='سازنده فرضی', strength='5 mg', dosage_form='قرص',
                       package_description='10 عدد', irc='001')])), 'منبع ساختگی', PRIVATE_MARKERS['product_source'],
                       actor=author, commit=True, rights_attested=True)
        stage_csv(io.BytesIO(csv_bytes([dict(source_record_id='one', irc='001', manufacturer='سازنده فرضی',
                    strength='5 mg', dosage_form='قرص', package_description='10 عدد', amount='100',
                    currency='RIAL', category='retail', unit='package', effective_date='',
                    source_published_date='')])), 'منبع ساختگی', PRIVATE_MARKERS['price_source'], staged_by=author,
                  commit=True, rights_attested=True)
        create_draft(actor=author, data={'subject': 'موضوع فرضی', 'audience': 'patient',
                     'title': PRIVATE_MARKERS['draft_title'], 'statement': PRIVATE_MARKERS['draft_statement'],
                     'reference_title': 'ارجاع فرضی', 'reference_url': 'https://example.org/reference',
                     'reference_location': 'بخش فرضی', 'reference_author': '', 'reference_version': '',
                     'reference_published_on': None, 'reference_accessed_on': None})
        from catalog.identity import create_ingredient
        create_ingredient(actor=author, data={'name_fa': PRIVATE_MARKERS['identity_ingredient'],
                          'name_en': 'Synthetic marker ingredient', 'source_name': 'منبع ساختگی',
                          'source_url': 'https://example.org/marker-identity'})
        stage_product_with_receipt(io.BytesIO(make_csv([dict(source_record_id='two', name_fa='فرآورده فرضی',
                                   name_en='Synthetic', manufacturer='سازنده فرضی', strength='5 mg',
                                   dosage_form='قرص', package_description='10 عدد', irc='002')])), 'منبع ساختگی',
                                   PRIVATE_MARKERS['receipt_source'], actor=author, rights_attested=True)

        cls.presentation = ProductPresentation.objects.create(
            name_fa=PUBLIC, name_en='Public synthetic presentation', manufacturer='سازنده فرضی',
            strength='۵ میلی‌گرم', dosage_form='قرص', package_description='۱۰ عدد', irc='۰۰۱',
            source_name='منبع ساختگی', source_url='https://example.org/public-presentation', published=True,
            verified_at=datetime(2026, 1, 1, tzinfo=dt_timezone.utc))

    def routes(self):
        for label, name, kwargs, query, status in PUBLIC_ROUTES:
            resolved = {'pk': self.presentation.pk} if kwargs.get('pk') == 'PRESENTATION' else kwargs
            yield label, name, resolved, query, status

    def probe(self, account, name, kwargs, query):
        client = self.client_class()
        if account is not None:
            client.force_login(account)
        return client.get(reverse(name, kwargs=kwargs) if kwargs else reverse(name), query)

    def test_inventory_covers_every_non_staff_route(self):
        names = {name for name in get_resolver().reverse_dict if isinstance(name, str) and not name.startswith('staff_')}
        declared = {row[1] for row in PUBLIC_ROUTES}
        self.assertEqual(names - declared, set(), 'A new public route needs an explicit privacy expectation.')
        self.assertEqual(declared - names, set(), 'A declared public route no longer exists.')

    def test_public_routes_answer_anonymous_and_staff_requests_alike(self):
        for account in (None, self.staff):
            for label, name, kwargs, query, status in self.routes():
                with self.subTest(account='anonymous' if account is None else 'staff', route=label):
                    response = self.probe(account, name, kwargs, query)
                    self.assertEqual(response.status_code, status)

    def test_no_private_marker_reaches_a_public_route(self):
        for account in (None, self.staff):
            for label, name, kwargs, query, _status in self.routes():
                if label in QUERY_ECHO_ROUTES:
                    continue
                response = self.probe(account, name, kwargs, query)
                body = response.content.decode('utf-8', errors='replace')
                for marker_label, marker in PRIVATE_MARKERS.items():
                    with self.subTest(account='anonymous' if account is None else 'staff', route=label,
                                      marker=marker_label):
                        self.assertNotIn(marker, body)

    def test_search_does_not_return_private_rows_but_does_return_published_ones(self):
        for account in (None, self.staff):
            who = 'anonymous' if account is None else 'staff'
            with self.subTest(account=who, case='private-candidate'):
                response = self.probe(account, 'search', {}, {'q': PRIVATE_MARKERS['product_row']})
                body = response.content.decode('utf-8')
                self.assertIn('نتیجه\u200cای در این بخش پیدا نشد', body)
                self.assertNotIn(f'/products/{self.presentation.pk}/', body)
            with self.subTest(account=who, case='private-draft-api'):
                payload = json.loads(self.probe(account, 'search_api', {},
                                           {'q': PRIVATE_MARKERS['draft_title']}).content)
                self.assertEqual(payload['data'], [])
            with self.subTest(account=who, case='published-presentation'):
                # Positive control: the public index is not simply empty.
                response = self.probe(account, 'search', {}, {'q': PUBLIC})
                self.assertIn(f'/products/{self.presentation.pk}/', response.content.decode('utf-8'))
                payload = json.loads(self.probe(account, 'search_api', {}, {'q': PUBLIC}).content)
                self.assertEqual([row['id'] for row in payload['data']], [self.presentation.pk])

    def test_private_markers_really_are_stored_in_private_rows(self):
        # Without this the leakage assertions could pass because nothing was ever
        # created. Each marker must be findable in the private model it came from.
        from catalog.models import IngredientDraft, ProductCandidate
        from ingestion.models import ImportReceipt
        from pricing.models import PriceCandidate
        from sources.models import SourceClaim

        checks = (
            (PRIVATE_MARKERS['claim_owner'],
             SourceClaim.objects.filter(owner=PRIVATE_MARKERS['claim_owner']).exists()),
            (PRIVATE_MARKERS['claim_note'],
             SourceClaim.objects.filter(evidence_note=PRIVATE_MARKERS['claim_note']).exists()),
            (PRIVATE_MARKERS['claim_url'],
             SourceClaim.objects.filter(source_url=PRIVATE_MARKERS['claim_url']).exists()),
            (PRIVATE_MARKERS['product_source'],
             ProductCandidate.objects.filter(source_url=PRIVATE_MARKERS['product_source']).exists()),
            (PRIVATE_MARKERS['product_row'],
             any(PRIVATE_MARKERS['product_row'] in json.dumps(candidate.source_fields, ensure_ascii=False)
                 for candidate in ProductCandidate.objects.all())),
            (PRIVATE_MARKERS['price_source'],
             PriceCandidate.objects.filter(source_url=PRIVATE_MARKERS['price_source']).exists()),
            (PRIVATE_MARKERS['draft_statement'],
             ClinicalDraft.objects.filter(statement=PRIVATE_MARKERS['draft_statement']).exists()),
            (PRIVATE_MARKERS['draft_title'],
             ClinicalDraft.objects.filter(title=PRIVATE_MARKERS['draft_title']).exists()),
            (PRIVATE_MARKERS['identity_ingredient'],
             IngredientDraft.objects.filter(name_fa=PRIVATE_MARKERS['identity_ingredient']).exists()),
            (PRIVATE_MARKERS['receipt_source'],
             ImportReceipt.objects.filter(source_url=PRIVATE_MARKERS['receipt_source']).exists()),
        )
        missing = [marker for marker, present in checks if not present]
        self.assertEqual(missing, [])
        self.assertEqual(len(checks), len(PRIVATE_MARKERS))
        # The only published presentation is the marker one; nothing private is published.
        self.assertEqual(ProductPresentation.objects.count(), 1)
        self.assertEqual(ProductPresentation.objects.get().name_fa, PUBLIC)

    def test_published_presentation_marker_is_visible_as_a_positive_control(self):
        # Without this the leakage assertions above could pass vacuously.
        response = self.probe(None, 'presentation_detail', {'pk': self.presentation.pk}, {})
        self.assertEqual(response.status_code, 200)
        self.assertIn(PUBLIC, response.content.decode('utf-8'))

    def test_public_read_routes_keep_public_privacy_headers(self):
        for account in (None, self.staff):
            for label, name, kwargs, query, _status in self.routes():
                if name not in PUBLIC_HEADER_ROUTES:
                    continue
                with self.subTest(account='anonymous' if account is None else 'staff', route=label):
                    response = self.probe(account, name, kwargs, query)
                    self.assertEqual(response['Cache-Control'], 'no-store')
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, follow')
                    self.assertEqual(response['Referrer-Policy'], 'no-referrer')

    def test_enabled_health_probes_stay_public_and_leak_nothing(self):
        # A TestCase wraps each test in a transaction and the readiness probe
        # deliberately refuses inside one, reporting `unavailable`; the readiness
        # behavior itself is covered by test_health_probes with
        # TransactionTestCase. What matters here is that neither probe depends on
        # the session and neither leaks more than its fixed body.
        expected = {'health_live': (200, b'ok\n'), 'health_ready': (503, b'unavailable\n')}
        with override_settings(HEALTH_PROBES_ENABLED=True):
            for account in (None, self.staff):
                for name, (status, body) in expected.items():
                    with self.subTest(account='anonymous' if account is None else 'staff', route=name):
                        response = self.probe(account, name, {}, {})
                        self.assertEqual(response.status_code, status)
                        self.assertEqual(response.content, body)
