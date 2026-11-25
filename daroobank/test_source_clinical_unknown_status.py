"""Selected unknown-review labels in source and clinical staff queues."""
import io
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from catalog.intake import stage_products
from catalog.models import ProductCandidate
from catalog.test_intake import make_csv
from clinical.models import ClinicalDraftReview
from clinical.services import create_draft, review_draft
from sources.models import SourceClaimReview
from sources.services import record_claim, review_claim


@override_settings(STAFF_PORTAL_ENABLED=True)
class SourceClinicalUnknownStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('unknown-source-author', is_staff=True)
        cls.reviewer = User.objects.create_user('unknown-source-reviewer', is_staff=True)
        for app, model in (('sources', 'sourceclaim'), ('clinical', 'clinicaldraft'), ('catalog', 'productcandidate')):
            perms = Permission.objects.filter(content_type__app_label=app)
            cls.author.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'add_{model}']))
            cls.reviewer.user_permissions.add(*perms.filter(codename__in=[f'view_{model}', f'review_{model}']))
        cls.claim, _ = record_claim(actor=cls.author, data=dict(source_name='منبع ساختگی',
            source_url='https://example.org/status', owner='مالک ساختگی', evidence_url='https://example.org/proof',
            evidence_note='', claims_collection=True, claims_storage=False, claims_publication=False,
            starts_on=None, expires_on=None))
        cls.draft = create_draft(actor=cls.author, data=dict(subject='موضوع فرضی', audience='patient',
            title='عنوان ساختگی', statement='گزاره کاملاً ساختگی برای آزمون.', reference_title='مرجع ساختگی',
            reference_url='https://example.org/status', reference_location='محل ساختگی', reference_author='',
            reference_version='', reference_published_on=None, reference_accessed_on=None))
        product_row = dict(source_record_id='source-status-product', name_fa='نام ساختگی', name_en='',
                           manufacturer='سازنده', strength='1 mg', dosage_form='قرص',
                           package_description='10 عدد', irc='123')
        stage_products(io.BytesIO(make_csv([product_row])), 'منبع ساختگی', 'https://example.org/status',
                       actor=cls.author, commit=True, rights_attested=True)
        cls.product = ProductCandidate.objects.get()
        cls.source_review = review_claim(actor=cls.reviewer, claim_id=cls.claim.pk, decision='defer',
            reason='توضیح ساختگی برای بازبینی منبع', expected_review=0, expected_hash=cls.claim.payload_sha256)
        cls.clinical_review = review_draft(actor=cls.reviewer, draft_id=cls.draft.pk, decision='defer',
            reason='توضیح ساختگی برای بازبینی پیش نویس', expected_review=0, expected_hash=cls.draft.payload_sha256)

    def omit_selected_constraints(self):
        config = connection.settings_dict
        if (connection.vendor != 'postgresql' or config.get('ENGINE') != 'daroobank.isolated_postgresql'
                or not re.fullmatch(r'test_daroobank_synthetic_[0-9a-f]{32}', str(config.get('NAME', '')))
                or not connection.in_atomic_block):
            raise RuntimeError('Constraint mutation requires a transactional isolated synthetic test database.')
        with connection.cursor() as cursor:
            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
            cursor.execute('ALTER TABLE sources_sourceclaimreview DROP CONSTRAINT source_review_valid_decision')
            cursor.execute('ALTER TABLE clinical_clinicaldraftreview DROP CONSTRAINT clinical_review_valid_decision')

    def test_selected_constraints_restore_after_savepoint_rollback(self):
        checks = [('sources_sourceclaimreview', 'source_review_valid_decision'),
                  ('clinical_clinicaldraftreview', 'clinical_review_valid_decision')]
        def present(table, name):
            with connection.cursor() as cursor:
                return name in connection.introspection.get_constraints(cursor, table)
        self.assertTrue(all(present(table, name) for table, name in checks))
        with transaction.atomic():
            self.omit_selected_constraints()
            self.assertTrue(all(not present(table, name) for table, name in checks))
            transaction.set_rollback(True)
        self.assertTrue(all(present(table, name) for table, name in checks))

    def test_unknown_review_is_not_labeled_as_pending_in_queues_or_related_claims(self):
        self.omit_selected_constraints()
        SourceClaimReview.objects.filter(pk=self.source_review.pk).update(decision='bad-source')
        ClinicalDraftReview.objects.filter(pk=self.clinical_review.pk).update(decision='bad-clinic')
        self.client.force_login(self.reviewer)
        for endpoint in ('staff_sources', 'staff_clinical_drafts'):
            response = self.client.get(reverse(endpoint))
            self.assertContains(response, 'وضعیت بازبینی نامعتبر')
            self.assertNotContains(response, 'bad-source')
            self.assertNotContains(response, 'bad-clinic')
            self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        response = self.client.get(reverse('staff_product_detail', args=[self.product.pk]))
        self.assertContains(response, 'وضعیت بازبینی نامعتبر')
        self.assertNotContains(response, 'bad-source')
        for endpoint, pk in (('staff_clinical_detail', self.draft.pk), ('staff_source_detail', self.claim.pk)):
            response = self.client.get(reverse(endpoint, args=[pk]))
            self.assertContains(response, 'بازبینی با جزئیات نامشخص')
            self.assertNotContains(response, 'bad-source')
            self.assertNotContains(response, 'bad-clinic')
