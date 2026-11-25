"""Opt-in, isolated PostgreSQL + real Chromium smoke tests with synthetic data."""
import io
import os
import subprocess
from datetime import timedelta
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth.models import Permission
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connection
from django.test import override_settings
from django.utils import timezone

from catalog.identity import create_package, digest, ingredient_snapshot, revise_identity
from catalog.intake import review_product, stage_products
from catalog.test_intake import make_csv
from catalog.models import IngredientDraft, IngredientRevision, IdentityPackageReview, ProductCandidate, ProductCandidateReview, ProductPresentation
from catalog.quality import MAX_INSPECTED_SEARCH_LENGTH
from catalog.test_identity import ALL, INGREDIENT, PACKAGE, build, user
from clinical.services import create_draft, draft_data, review_draft
from clinical.models import ClinicalDraft, ClinicalDraftReview
from clinical.evidence import evidence_state
from ingestion.models import ImportReceipt
from ingestion.receipts import stage_price_with_receipt
from pricing.importer import stage_csv
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.test_workflow import csv_bytes
from pricing.reviews import record_preliminary_review
from sources.services import record_claim, review_claim
from sources.models import SourceClaim, SourceClaimReview
from tools.browser_test_diagnostics import browser_failure_annotation

ROOT = Path(__file__).resolve().parent.parent


@skipUnless(os.environ.get('DAROOBANK_BROWSER_TESTS') == '1', 'Optional Chromium dependencies are not enabled')
@override_settings(STAFF_PORTAL_ENABLED=True)
class SyntheticBrowserTests(StaticLiveServerTestCase):
    """The live server uses Django's throwaway test DB, never the development DB."""

    def test_public_and_private_synthetic_workflows_in_chromium(self):
        self.assertTrue(getattr(settings, 'DAROOBANK_BROWSER_ISOLATED', False),
                        'Use daroobank.browser_test_settings for isolated browser tests')
        self.assertEqual(connection.vendor, 'postgresql')
        self.assertRegex(connection.settings_dict['NAME'], r'^test_daroobank_browser_[0-9a-f]{32}$')
        author = user('browser-author', *ALL, 'view_productcandidate', 'view_productpresentation')
        author.user_permissions.add(Permission.objects.get(content_type__app_label='catalog', codename='add_productcandidate'))
        author.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources',
                                    codename__in=['view_sourceclaim', 'add_sourceclaim']))
        author.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical',
                                    codename__in=['view_clinicaldraft', 'add_clinicaldraft']))
        clinical_leaf = create_draft(actor=author, data={
            'subject': 'موضوع ساختگی مرورگر', 'audience': 'patient', 'title': 'عنوان خصوصی مرورگر',
            'statement': 'متن خصوصی و ساختگی برای آزمون مرورگر', 'reference_title': 'مرجع فرضی',
            'reference_url': 'https://example.org/browser', 'reference_location': 'بخش فرضی',
            'reference_author': '', 'reference_version': '', 'reference_published_on': None,
            'reference_accessed_on': None,
        })
        for i in range(21):
            clinical_leaf = create_draft(actor=author, data={**draft_data(clinical_leaf), 'title': f'نسخه خصوصی مرورگر {i}'},
                parent_id=clinical_leaf.pk, expected_parent_hash=clinical_leaf.payload_sha256,
                change_reason='اصلاح ساختگی برای آزمون مرورگر')
        oversized_draft = create_draft(actor=author, data=draft_data(clinical_leaf))
        ClinicalDraft.objects.filter(pk=oversized_draft.pk).update(
            statement='آ' * 100_000 + 'browser-draft-statement-canary')
        browser_claim, _ = record_claim(actor=author, data={
            'source_name': 'منبع ساختگی مرورگر', 'source_url': 'https://example.org/fixture',
            'owner': 'مالک فرضی', 'evidence_url': 'https://example.org/evidence', 'evidence_note': '',
            'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
            'starts_on': None, 'expires_on': timezone.localdate() - timedelta(days=1),
        })
        oversized_claim, _ = record_claim(actor=author, data={
            'source_name': 'ادعای ساختگی طولانی مرورگر', 'source_url': 'https://example.org/oversized-claim',
            'owner': 'مالک فرضی', 'evidence_url': 'https://example.org/evidence', 'evidence_note': '',
            'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
            'starts_on': None, 'expires_on': None,
        })
        SourceClaim.objects.filter(pk=oversized_claim.pk).update(
            evidence_note='ر' * 100_000 + 'browser-claim-note-canary')
        reviewer = user('browser-reviewer', 'view_identityworkspace', 'review_identityworkspace')
        reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical',
                                      codename__in=['view_clinicaldraft', 'review_clinicaldraft']))
        reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources',
                                      codename__in=['view_sourceclaim', 'review_sourceclaim']))
        reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog',
                                      codename__in=['view_productcandidate', 'review_productcandidate']))
        reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
                                      codename__in=['view_pricecandidate', 'review_pricecandidate']))
        review_claim(actor=reviewer, claim_id=browser_claim.pk, decision='defer',
                     reason='بازبینی منبع ساختگی برای مرورگر', expected_review=0,
                     expected_hash=browser_claim.payload_sha256)
        SourceClaimReview.objects.create(claim=browser_claim, reviewer=reviewer, decision='defer',
            reason='ر' * 100_000 + 'browser-source-oversized-reason-canary',
            claim_payload_sha256=browser_claim.payload_sha256,
            review_snapshot={'oversized': 'آ' * 100_000 + 'browser-source-oversized-snapshot-canary'})
        product_row = {'source_record_id': 'browser-product', 'name_fa': 'فرآورده ساختگی مرورگر',
                       'name_en': '', 'manufacturer': 'سازنده فرضی', 'strength': '1 mg',
                       'dosage_form': 'قرص', 'package_description': '10 عدد', 'irc': '001'}
        stage_products(io.BytesIO(make_csv([product_row])), 'منبع ساختگی مرورگر',
                       'https://example.org/browser-product', actor=author, commit=True, rights_attested=True)
        browser_candidate = ProductCandidate.objects.get(source_record_id='browser-product')
        stage_products(io.BytesIO(make_csv([{**product_row, 'strength': '2 mg'}])), 'منبع ساختگی مرورگر',
                       'https://example.org/browser-product', actor=author, commit=True, rights_attested=True)
        oversized_product_candidate = ProductCandidate.objects.exclude(pk=browser_candidate.pk).get(source_record_id='browser-product')
        ProductCandidate.objects.filter(pk=oversized_product_candidate.pk).update(
            source_fields={'browser-product-comparison-canary': 'آ' * 100_000})
        valid_product_review = review_product(actor=reviewer, candidate_id=browser_candidate.pk, decision='defer',
                       reason='بازبینی فرآورده ساختگی برای مرورگر', expected_review=0,
                       expected_hash=browser_candidate.payload_sha256)
        invalid_product_review = review_product(actor=reviewer, candidate_id=browser_candidate.pk, decision='defer',
                       reason='بازبینی ساختگی برای تغییر در آزمون مرورگر', expected_review=valid_product_review.pk,
                       expected_hash=browser_candidate.payload_sha256)
        # Direct mutation is restricted to the disposable synthetic browser DB.
        ProductCandidateReview.objects.filter(pk=invalid_product_review.pk).update(
            review_snapshot={'unexpected': 'browser-product-history-hidden-canary'},
            reason='browser-product-history-reason-canary توضیح ساختگی')
        ProductCandidateReview.objects.create(candidate=browser_candidate, reviewer=reviewer, decision='defer',
            reason='ر' * 100_000 + 'browser-oversized-reason-canary',
            candidate_payload_sha256=browser_candidate.payload_sha256,
            review_snapshot={'oversized': 'آ' * 100_000 + 'browser-oversized-snapshot-canary'})
        bad_product_row = {**product_row, 'source_record_id': 'browser-invalid-product', 'irc': '999'}
        stage_products(io.BytesIO(make_csv([bad_product_row])), 'منبع ساختگی مرورگر',
                       'https://example.org/browser-invalid-product', actor=author, commit=True, rights_attested=True)
        bad_product = ProductCandidate.objects.get(source_record_id='browser-invalid-product')
        ProductCandidate.objects.filter(pk=bad_product.pk).update(
            source_fields={**bad_product_row, 'name_fa': 'browser-product-hidden-canary'})
        review_draft(actor=reviewer, draft_id=clinical_leaf.pk, decision='defer',
                     reason='دلیل خصوصی ساختگی بازبینی مرورگر', expected_review=0,
                     expected_hash=clinical_leaf.payload_sha256,
                     expected_evidence_hash=evidence_state(clinical_leaf)['fingerprint'])
        ClinicalDraftReview.objects.create(draft=clinical_leaf, reviewer=reviewer, decision='defer',
            reason='ر' * 100_000 + 'browser-clinical-oversized-reason-canary',
            draft_payload_sha256=clinical_leaf.payload_sha256,
            review_snapshot={'oversized': 'آ' * 100_000 + 'browser-clinical-oversized-snapshot-canary'})
        price_stager = user('browser-price-stager')
        price_stager.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
                                         codename__in=['view_pricecandidate', 'add_pricecandidate']))
        ingredient, _, formulation, product, package = build(author)
        oversized_package = create_package(actor=author, data={**PACKAGE, 'description': 'بسته ساختگی بزرگ مرورگر'},
                                           product_id=product.pk)
        IdentityPackageReview.objects.create(package=oversized_package, reviewer=reviewer, decision='defer',
            reason='ر' * 100_000 + 'browser-identity-oversized-reason-canary', graph_sha256='0' * 64,
            graph_snapshot={'oversized': 'آ' * 100_000 + 'browser-identity-oversized-graph-canary'})
        leaf = ingredient
        for i in range(22):
            leaf = revise_identity(actor=author, kind='ingredient', parent_id=leaf.pk,
                data={**INGREDIENT, 'name_fa': f'ماده ساختگی خصوصی مرورگر {i}'},
                change_reason='اصلاح ساختگی برای آزمایش مرورگر', expected_graph_hash=digest(ingredient_snapshot(leaf)))
        oversized_ingredient = revise_identity(actor=author, kind='ingredient', parent_id=ingredient.pk,
            data={**INGREDIENT, 'name_fa': 'نسخه با دلیل طولانی ساختگی'},
            change_reason='دلیل ساختگی برای آزمون صفحه مرورگر', expected_graph_hash=digest(ingredient_snapshot(ingredient)))
        IngredientRevision.objects.filter(child_id=oversized_ingredient.pk).update(
            change_reason='ر' * 100_000 + 'browser-identity-link-reason-canary')
        public_product = ProductPresentation.objects.create(name_fa='داروی عمومی ساختگی مرورگر', name_en='Browser Synthetic Product',
            manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص', package_description='10 عدد',
            irc='001', source_name='منبع ساختگی', source_url='https://example.org/public',
            verified_at=timezone.now(), published=True)
        # Bypass-write a long projection to exercise the private quality warning;
        # keep the genuine terms so the public current-field recheck still matches.
        ProductPresentation.objects.filter(pk=public_product.pk).update(
            search_text=public_product.search_text + ' ' + 'x' * (MAX_INSPECTED_SEARCH_LENGTH + 1) + 'browser-private-canary')
        price_row = dict(source_record_id='browser-detail', irc='001', manufacturer='سازنده فرضی',
            strength='1 mg', dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
            category='retail', unit='package', effective_date='', source_published_date='')
        stage_csv(io.BytesIO(csv_bytes([price_row])), 'منبع ساختگی مرورگر', 'https://example.org/browser-detail',
                  staged_by=price_stager, commit=True, rights_attested=True)
        _, browser_receipt = stage_price_with_receipt(io.BytesIO(csv_bytes([price_row, price_row])), 'منبع ساختگی مرورگر',
            'https://example.org/browser-detail', actor=price_stager, rights_attested=True)
        _, oversized_receipt = stage_price_with_receipt(
            io.BytesIO(csv_bytes([{**price_row, 'source_record_id': 'oversized-receipt-row'}])),
            'منبع ساختگی مرورگر', 'https://example.org/oversized-receipt', actor=price_stager, rights_attested=True)
        PriceCandidate.objects.filter(pk=oversized_receipt.items.get().price_candidate_id).update(
            source_fields={'browser-receipt-json-canary': 'آ' * 100_000})
        browser_price = PriceCandidate.objects.get(source_record_id='browser-detail')
        stage_csv(io.BytesIO(csv_bytes([{**price_row, 'amount': '200'}])), 'منبع ساختگی مرورگر',
                  'https://example.org/browser-detail', staged_by=price_stager, commit=True, rights_attested=True)
        oversized_price_candidate = PriceCandidate.objects.exclude(pk=browser_price.pk).get(source_record_id='browser-detail')
        PriceCandidate.objects.filter(pk=oversized_price_candidate.pk).update(
            source_fields={'browser-price-comparison-canary': 'آ' * 100_000})
        valid_price_review = record_preliminary_review(actor=reviewer, candidate_id=browser_price.pk, decision='defer',
                                  reason='بازبینی قیمت ساختگی برای مرورگر', expected_review=0,
                                  expected_product=0, expected_product_hash='')
        invalid_price_review = record_preliminary_review(actor=reviewer, candidate_id=browser_price.pk, decision='defer',
                                  reason='بازبینی ساختگی برای تغییر در آزمون مرورگر', expected_review=valid_price_review.pk,
                                  expected_product=0, expected_product_hash='')
        # Bypass only the isolated synthetic DB to exercise the invalid-history display.
        PriceCandidateReview.objects.filter(pk=invalid_price_review.pk).update(
            review_snapshot={'unexpected': 'browser-history-hidden-canary'},
            reason='browser-history-reason-canary متنی ساختگی برای آزمون')
        PriceCandidateReview.objects.create(candidate=browser_price, reviewer=reviewer, decision='defer',
            reason='ر' * 100_000 + 'browser-oversized-reason-canary',
            candidate_payload_sha256=browser_price.payload_sha256,
            review_snapshot={'oversized': 'آ' * 100_000 + 'browser-oversized-snapshot-canary'})
        bad_price_row = {**price_row, 'source_record_id': 'browser-invalid-price', 'irc': '999'}
        stage_csv(io.BytesIO(csv_bytes([bad_price_row])), 'منبع ساختگی مرورگر',
                  'https://example.org/browser-invalid-price', staged_by=price_stager, commit=True, rights_attested=True)
        bad_price = PriceCandidate.objects.get(source_record_id='browser-invalid-price')
        PriceCandidate.objects.filter(pk=bad_price.pk).update(
            source_fields={**bad_price_row, 'manufacturer': 'browser-price-hidden-canary'},
            original_amount='browser-amount-hidden-canary')
        # The subprocess receives only what it needs; database credentials are not propagated.
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'TMPDIR') if key in os.environ}
        env.update(BROWSER_BASE_URL=self.live_server_url, BROWSER_AUTHOR='browser-author', BROWSER_REVIEWER='browser-reviewer',
                   BROWSER_PASSWORD='test-only', BROWSER_INGREDIENT=str(ingredient.pk), BROWSER_LEAF=str(leaf.pk),
                   BROWSER_FORMULATION=str(formulation.pk), BROWSER_PRODUCT=str(product.pk), BROWSER_PACKAGE=str(package.pk),
                   BROWSER_OVERSIZED_PACKAGE=str(oversized_package.pk), BROWSER_OVERSIZED_INGREDIENT=str(oversized_ingredient.pk),
                   BROWSER_CLINICAL_LEAF=str(clinical_leaf.pk), BROWSER_OVERSIZED_DRAFT=str(oversized_draft.pk), BROWSER_PRICE=str(browser_price.pk),
                   BROWSER_RECEIPT=str(browser_receipt.pk), BROWSER_OVERSIZED_RECEIPT=str(oversized_receipt.pk), BROWSER_CLAIM=str(browser_claim.pk), BROWSER_OVERSIZED_CLAIM=str(oversized_claim.pk),
                   BROWSER_CANDIDATE=str(browser_candidate.pk), BROWSER_OVERSIZED_CANDIDATE=str(oversized_product_candidate.pk),
                   BROWSER_OVERSIZED_PRICE=str(oversized_price_candidate.pk), BROWSER_BAD_CANDIDATE=str(bad_product.pk),
                   BROWSER_BAD_PRICE=str(bad_price.pk))
        try:
            result = subprocess.run(['node', 'smoke.cjs'], cwd=ROOT / 'tests' / 'browser', env=env,
                                    capture_output=True, text=True, timeout=240)
        except subprocess.TimeoutExpired:
            if os.environ.get('GITHUB_ACTIONS') == 'true':
                print(browser_failure_annotation(None, ''), flush=True)
            raise
        if result.returncode and os.environ.get('GITHUB_ACTIONS') == 'true':
            print(browser_failure_annotation(result.returncode, result.stderr), flush=True)
        self.assertEqual(result.returncode, 0, f'Chromium test failed:\n{result.stdout}\n{result.stderr}')
        self.assertEqual(IngredientDraft.objects.filter(name_fa='csrf-canary').count(), 0)
        self.assertEqual(IngredientDraft.objects.filter(name_fa='ماده تازه ساختگی مرورگر').count(), 1)
        self.assertEqual(IdentityPackageReview.objects.count(), 2)
        self.assertEqual(ClinicalDraftReview.objects.count(), 2)
        self.assertEqual(SourceClaimReview.objects.count(), 2)
        self.assertEqual(PriceCandidate.objects.count(), 4)
        self.assertEqual(ImportReceipt.objects.count(), 2)
        self.assertEqual(browser_receipt.items.count(), 2)
        self.assertIn('browser checks passed', result.stdout)
        print(result.stdout.strip())
