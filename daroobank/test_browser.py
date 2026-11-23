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

from catalog.identity import digest, ingredient_snapshot, revise_identity
from catalog.models import IngredientDraft, IdentityPackageReview, ProductPresentation
from catalog.test_identity import ALL, INGREDIENT, build, user
from clinical.services import create_draft, draft_data, review_draft
from clinical.evidence import evidence_state
from ingestion.models import ImportReceipt
from pricing.importer import stage_csv
from pricing.models import PriceCandidate
from pricing.test_workflow import csv_bytes
from sources.services import record_claim
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
        record_claim(actor=author, data={
            'source_name': 'منبع ساختگی مرورگر', 'source_url': 'https://example.org/fixture',
            'owner': 'مالک فرضی', 'evidence_url': 'https://example.org/evidence', 'evidence_note': '',
            'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
            'starts_on': None, 'expires_on': timezone.localdate() - timedelta(days=1),
        })
        reviewer = user('browser-reviewer', 'view_identityworkspace', 'review_identityworkspace')
        reviewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical',
                                      codename__in=['view_clinicaldraft', 'review_clinicaldraft']))
        review_draft(actor=reviewer, draft_id=clinical_leaf.pk, decision='defer',
                     reason='دلیل خصوصی ساختگی بازبینی مرورگر', expected_review=0,
                     expected_hash=clinical_leaf.payload_sha256,
                     expected_evidence_hash=evidence_state(clinical_leaf)['fingerprint'])
        price_stager = user('browser-price-stager')
        price_stager.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing',
                                         codename__in=['view_pricecandidate', 'add_pricecandidate']))
        ingredient, _, formulation, product, package = build(author)
        leaf = ingredient
        for i in range(22):
            leaf = revise_identity(actor=author, kind='ingredient', parent_id=leaf.pk,
                data={**INGREDIENT, 'name_fa': f'ماده ساختگی خصوصی مرورگر {i}'},
                change_reason='اصلاح ساختگی برای آزمایش مرورگر', expected_graph_hash=digest(ingredient_snapshot(leaf)))
        ProductPresentation.objects.create(name_fa='داروی عمومی ساختگی مرورگر', name_en='Browser Synthetic Product',
            manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص', package_description='10 عدد',
            irc='001', source_name='منبع ساختگی', source_url='https://example.org/public',
            verified_at=timezone.now(), published=True)
        stage_csv(io.BytesIO(csv_bytes([dict(source_record_id='browser-detail', irc='001', manufacturer='سازنده فرضی',
            strength='1 mg', dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
            category='retail', unit='package', effective_date='', source_published_date='')])),
            'منبع ساختگی مرورگر', 'https://example.org/browser-detail', staged_by=price_stager,
            commit=True, rights_attested=True)
        browser_price = PriceCandidate.objects.get(source_record_id='browser-detail')
        # The subprocess receives only what it needs; database credentials are not propagated.
        env = {key: os.environ[key] for key in ('PATH', 'HOME', 'LANG', 'TMPDIR') if key in os.environ}
        env.update(BROWSER_BASE_URL=self.live_server_url, BROWSER_AUTHOR='browser-author', BROWSER_REVIEWER='browser-reviewer',
                   BROWSER_PASSWORD='test-only', BROWSER_INGREDIENT=str(ingredient.pk), BROWSER_LEAF=str(leaf.pk),
                   BROWSER_FORMULATION=str(formulation.pk), BROWSER_PRODUCT=str(product.pk), BROWSER_PACKAGE=str(package.pk),
                   BROWSER_CLINICAL_LEAF=str(clinical_leaf.pk), BROWSER_PRICE=str(browser_price.pk))
        try:
            result = subprocess.run(['node', 'smoke.cjs'], cwd=ROOT / 'tests' / 'browser', env=env,
                                    capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired:
            if os.environ.get('GITHUB_ACTIONS') == 'true':
                print(browser_failure_annotation(None, ''), flush=True)
            raise
        if result.returncode and os.environ.get('GITHUB_ACTIONS') == 'true':
            print(browser_failure_annotation(result.returncode, result.stderr), flush=True)
        self.assertEqual(result.returncode, 0, f'Chromium test failed:\n{result.stdout}\n{result.stderr}')
        self.assertEqual(IngredientDraft.objects.filter(name_fa='csrf-canary').count(), 0)
        self.assertEqual(IngredientDraft.objects.filter(name_fa='ماده تازه ساختگی مرورگر').count(), 1)
        self.assertEqual(IdentityPackageReview.objects.count(), 1)
        self.assertEqual(PriceCandidate.objects.count(), 1)
        self.assertEqual(ImportReceipt.objects.count(), 0)
        self.assertIn('browser checks passed', result.stdout)
        print(result.stdout.strip())
