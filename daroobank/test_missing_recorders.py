"""Selected synthetic missing source-recorder and clinical-author scenarios."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections, connection
from django.test import TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from clinical.evidence import add_reference, evidence_state
from clinical.inspection import inspect_drafts
from clinical.models import ClinicalDraft, ClinicalDraftReview, ClinicalReferenceAssertion
from clinical.services import DraftConflict, create_draft, review_draft
from sources.models import SourceClaim, SourceClaimReview
from sources.date_inspection import inspect_dates
from sources.services import ReviewConflict, record_claim, review_claim


@override_settings(STAFF_PORTAL_ENABLED=True)
class MissingRecorderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('missing-creator-author', is_staff=True)
        cls.reviewer = User.objects.create_user('missing-creator-reviewer', is_staff=True)
        cls.viewer = User.objects.create_user('missing-creator-viewer', is_staff=True)
        cls.no_access = User.objects.create_user('missing-creator-no-access', is_staff=True)
        for app, entity in [('sources', 'sourceclaim'), ('clinical', 'clinicaldraft')]:
            perms = Permission.objects.filter(content_type__app_label=app)
            cls.author.user_permissions.add(*perms.filter(codename__in=[f'view_{entity}', f'add_{entity}']))
            cls.reviewer.user_permissions.add(*perms.filter(codename__in=[f'view_{entity}', f'add_{entity}', f'review_{entity}']))
            cls.viewer.user_permissions.add(perms.get(codename=f'view_{entity}'))
        cls.claim, _ = record_claim(actor=cls.author, data=dict(source_name='منبع ساختگی',
            source_url='https://example.org/claim', owner='مالک فرضی', evidence_url='https://example.org/evidence',
            evidence_note='', claims_collection=True, claims_storage=False, claims_publication=False,
            starts_on=None, expires_on=None))
        cls.data = dict(subject='موضوع ساختگی', audience='patient', title='عنوان محرمانه ساختگی',
            statement='متن ساختگی فقط برای آزمون است.', reference_title='مرجع فرضی',
            reference_url='https://example.org/clinical', reference_location='بخش فرضی', reference_author='',
            reference_version='', reference_published_on=None, reference_accessed_on=None)
        cls.ref = dict(reference_title='ارجاع تکمیلی ساختگی', reference_url='https://example.org/ref',
            reference_location='بخش فرضی', reference_author='', reference_version='',
            reference_published_on=None, reference_accessed_on=None, relation='supports')
        cls.draft = create_draft(actor=cls.author, data=cls.data)
        cls.reason = 'دلیل ساختگی برای این آزمون بازبینی.'
        cls.missing = 2_147_483_000  # test auth_user PK is a PostgreSQL integer

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def source_review(self):
        return dict(decision='defer', reason=self.reason, expected_review=0, expected_hash=self.claim.payload_sha256)

    def clinical_review(self):
        return dict(decision='defer', reason=self.reason, expected_review=0, expected_hash=self.draft.payload_sha256,
                    expected_evidence_hash=evidence_state(self.draft)['fingerprint'])

    def test_missing_source_recorder_visible_but_review_fails_closed(self):
        try:
            SourceClaim.objects.filter(pk=self.claim.pk).update(recorded_by_id=self.missing)
            with self.assertRaises(ReviewConflict):
                review_claim(actor=self.reviewer, claim_id=self.claim.pk, **self.source_review())
            self.client.force_login(self.reviewer)
            detail = self.client.get(reverse('staff_source_detail', args=[self.claim.pk]))
            self.assertEqual(detail.status_code, 200)
            self.assertContains(detail, 'حساب ثبت‌کننده در دسترس نیست')
            self.assertNotContains(detail, 'ثبت بازبینی اولیه')
            self.assert_private(detail)
            listing = self.client.get(reverse('staff_sources'))
            self.assertEqual(listing.context['page'].paginator.count, 1)
            self.assertContains(listing, reverse('staff_source_detail', args=[self.claim.pk]))
            self.assertContains(listing, 'حساب ثبت‌کننده در دسترس نیست')
            response = self.client.post(reverse('staff_source_review', args=[self.claim.pk]), self.source_review())
            self.assertEqual(response.status_code, 409)
            self.assertContains(response, 'حساب ثبت‌کننده در دسترس نیست', status_code=409)
            self.assert_private(response)
            self.assertFalse(SourceClaimReview.objects.exists())
            self.client.force_login(self.no_access)
            self.assertEqual(self.client.get(reverse('staff_source_detail', args=[self.claim.pk])).status_code, 403)
        finally:
            SourceClaim.objects.filter(pk=self.claim.pk).update(recorded_by_id=self.author.pk)

    def test_missing_clinical_author_stops_three_writers_and_hides_content(self):
        payload = self.clinical_review()
        try:
            ClinicalDraft.objects.filter(pk=self.draft.pk).update(author_id=self.missing)
            with self.assertRaises(DraftConflict):
                review_draft(actor=self.reviewer, draft_id=self.draft.pk, **payload)
            with self.assertRaises(DraftConflict):
                add_reference(actor=self.reviewer, draft_id=self.draft.pk, data=self.ref,
                    expected_draft_hash=self.draft.payload_sha256, expected_evidence_hash=payload['expected_evidence_hash'])
            with self.assertRaises(DraftConflict):
                create_draft(actor=self.reviewer, data=self.data, parent_id=self.draft.pk,
                    expected_parent_hash=self.draft.payload_sha256, change_reason=self.reason)
            self.client.force_login(self.reviewer)
            detail = self.client.get(reverse('staff_clinical_detail', args=[self.draft.pk]))
            self.assertEqual(detail.status_code, 200)
            self.assertContains(detail, 'حساب نویسنده در دسترس نیست')
            self.assertNotContains(detail, self.data['title'])
            self.assertNotContains(detail, 'ثبت بازبینی اولیه')
            self.assert_private(detail)
            listing = self.client.get(reverse('staff_clinical_drafts'))
            self.assertEqual(listing.context['page'].paginator.count, 1)
            self.assertContains(listing, reverse('staff_clinical_detail', args=[self.draft.pk]))
            self.assertNotContains(listing, self.data['title'])
            response = self.client.post(reverse('staff_clinical_review', args=[self.draft.pk]), payload)
            self.assertEqual(response.status_code, 409)
            self.assertContains(response, 'حساب نویسنده در دسترس نیست', status_code=409)
            self.assert_private(response)
            for route in ('staff_clinical_revise', 'staff_clinical_reference_create'):
                response = self.client.get(reverse(route, args=[self.draft.pk]))
                self.assertEqual(response.status_code, 409)
                self.assertNotContains(response, self.data['title'], status_code=409)
                self.assert_private(response)
            self.assertEqual(ClinicalDraft.objects.count(), 1)
            self.assertFalse(ClinicalDraftReview.objects.exists())
            self.assertFalse(ClinicalReferenceAssertion.objects.exists())
            self.client.force_login(self.no_access)
            self.assertEqual(self.client.get(reverse('staff_clinical_detail', args=[self.draft.pk])).status_code, 403)
        finally:
            ClinicalDraft.objects.filter(pk=self.draft.pk).update(author_id=self.author.pk)

    def test_source_dates_ignore_creator_but_clinical_scan_reports_missing_author(self):
        try:
            SourceClaim.objects.filter(pk=self.claim.pk).update(recorded_by_id=self.missing)
            ClinicalDraft.objects.filter(pk=self.draft.pk).update(author_id=self.missing)
            self.assertEqual(inspect_dates()['rows'], [{'id': self.claim.pk, 'status': 'unknown'}])
            self.assertEqual(inspect_drafts()['rows'], [{'id': self.draft.pk, 'status': 'author_missing'}])
            self.client.force_login(self.viewer)
            self.assertContains(self.client.get(reverse('staff_source_date_inspection')), 'وجود حساب ثبت‌کننده بررسی نمی‌شود')
            self.assertContains(self.client.get(reverse('staff_clinical_inspection')), 'حساب نویسنده در دسترس نیست')
        finally:
            SourceClaim.objects.filter(pk=self.claim.pk).update(recorded_by_id=self.author.pk)
            ClinicalDraft.objects.filter(pk=self.draft.pk).update(author_id=self.author.pk)

    def test_current_account_existence_is_not_activity_or_qualification(self):
        get_user_model().objects.filter(pk=self.author.pk).update(is_active=False, is_staff=False)
        source = review_claim(actor=self.reviewer, claim_id=self.claim.pk, **self.source_review())
        clinical = review_draft(actor=self.reviewer, draft_id=self.draft.pk, **self.clinical_review())
        self.assertEqual(source.review_snapshot['recorded_by_id'], self.author.pk)
        self.assertEqual(clinical.review_snapshot['author_id'], self.author.pk)
        self.client.force_login(self.viewer)
        self.assertNotContains(self.client.get(reverse('staff_source_detail', args=[self.claim.pk])), 'حساب ثبت‌کننده در دسترس نیست')
        self.assertNotContains(self.client.get(reverse('staff_clinical_detail', args=[self.draft.pk])), 'حساب نویسنده در دسترس نیست')

    def test_immediate_parent_author_is_not_checked_for_child_review(self):
        child = create_draft(actor=self.reviewer, data=self.data, parent_id=self.draft.pk,
                             expected_parent_hash=self.draft.payload_sha256, change_reason=self.reason)
        other = get_user_model().objects.create_user('independent-reviewer', is_staff=True)
        other.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical',
                                   codename__in=['view_clinicaldraft', 'review_clinicaldraft']))
        try:
            ClinicalDraft.objects.filter(pk=self.draft.pk).update(author_id=self.missing)
            event = review_draft(actor=other, draft_id=child.pk, decision='defer', reason=self.reason,
                expected_review=0, expected_hash=child.payload_sha256,
                expected_evidence_hash=evidence_state(child)['fingerprint'])
            self.assertEqual(event.draft_id, child.pk)
        finally:
            ClinicalDraft.objects.filter(pk=self.draft.pk).update(author_id=self.author.pk)

    def test_source_actor_check_does_not_make_uncooperative_later_writes_impossible(self):
        from daroobank.account_checks import current_account_exists
        def mutate_after_read(pk, *, using):
            present = current_account_exists(pk, using=using)
            SourceClaim.objects.filter(pk=self.claim.pk).update(recorded_by_id=self.missing)
            return present
        try:
            with patch('sources.services.current_account_exists', side_effect=mutate_after_read):
                event = review_claim(actor=self.reviewer, claim_id=self.claim.pk, **self.source_review())
            self.assertEqual(event.review_snapshot['recorded_by_id'], self.author.pk)
            self.assertEqual(SourceClaim.objects.get(pk=self.claim.pk).recorded_by_id, self.missing)
        finally:
            SourceClaim.objects.filter(pk=self.claim.pk).update(recorded_by_id=self.author.pk)

    def test_clinical_check_does_not_block_later_uncooperative_mutation(self):
        from daroobank.account_checks import current_account_exists
        def mutate_after_read(pk, *, using):
            present = current_account_exists(pk, using=using)
            ClinicalDraft.objects.filter(pk=self.draft.pk).update(author_id=self.missing)
            return present
        operations = (
            lambda: review_draft(actor=self.reviewer, draft_id=self.draft.pk, **self.clinical_review()),
            lambda: add_reference(actor=self.reviewer, draft_id=self.draft.pk, data=self.ref,
                expected_draft_hash=self.draft.payload_sha256, expected_evidence_hash=evidence_state(self.draft)['fingerprint']),
            lambda: create_draft(actor=self.reviewer, data=self.data, parent_id=self.draft.pk,
                expected_parent_hash=self.draft.payload_sha256, change_reason=self.reason),
        )
        for operation in operations:
            try:
                with patch('clinical.services.current_account_exists', side_effect=mutate_after_read):
                    self.assertIsNotNone(operation())
                self.assertEqual(ClinicalDraft.objects.get(pk=self.draft.pk).author_id, self.missing)
            finally:
                ClinicalDraft.objects.filter(pk=self.draft.pk).update(author_id=self.author.pk)

    def test_account_helpers_ignore_invalid_ids_without_queries(self):
        from daroobank.account_checks import current_account_exists, current_accounts
        with self.assertNumQueries(0):
            self.assertEqual(current_accounts([None, False, -1, '1', 2**63], using='default'), {})
            for value in [None, True, -1, '1', 2**63]:
                self.assertFalse(current_account_exists(value, using='default'))
        with self.assertNumQueries(1):
            self.assertEqual(set(current_accounts([self.author.pk, self.author.pk, None], using='default')), {self.author.pk})

    def test_clinical_queue_account_lookup_has_no_per_row_queries(self):
        self.client.force_login(self.viewer)
        path = reverse('staff_clinical_drafts')
        self.client.get(path)
        with CaptureQueriesContext(connection) as one:
            self.client.get(path)
        for i in range(19):
            create_draft(actor=self.author, data={**self.data, 'title': f'عنوان ساختگی {i}'})
        with CaptureQueriesContext(connection) as many:
            response = self.client.get(path)
        self.assertEqual(len(one), len(many))
        account_reads = [q for q in many if '"auth_user"' in q['sql'].lower() and ' in ' in q['sql'].lower()]
        self.assertEqual(len(account_reads), 1)
        selected = account_reads[0]['sql'].upper().split(' FROM ', 1)[0]
        self.assertIn('"ID"', selected)
        for field in ('PASSWORD', 'USERNAME', 'EMAIL'):
            self.assertNotIn(field, selected, account_reads[0]['sql'])
        self.assertEqual(len(response.context['page'].object_list), 20)
        self.assertTrue(all(item.is_valid for item in response.context['page'].object_list))

    def test_ordinary_review_and_revision_still_work(self):
        event = review_claim(actor=self.reviewer, claim_id=self.claim.pk, **self.source_review())
        self.assertEqual(event.review_snapshot['recorded_by_id'], self.author.pk)
        event = review_draft(actor=self.reviewer, draft_id=self.draft.pk, **self.clinical_review())
        self.assertEqual(event.review_snapshot['author_id'], self.author.pk)
        ref, created = add_reference(actor=self.reviewer, draft_id=self.draft.pk, data=self.ref,
            expected_draft_hash=self.draft.payload_sha256, expected_evidence_hash=evidence_state(self.draft)['fingerprint'])
        self.assertTrue(created)
        child = create_draft(actor=self.reviewer, data=self.data, parent_id=self.draft.pk,
            expected_parent_hash=self.draft.payload_sha256, change_reason=self.reason)
        self.assertEqual(child.parent_id, self.draft.pk)
        self.assertEqual(ref.draft_id, self.draft.pk)


class CreatorAccountConcurrencyTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user('creator-race-author', is_staff=True)
        self.reviewer = User.objects.create_user('creator-race-reviewer', is_staff=True)
        for app, entity in [('sources', 'sourceclaim'), ('clinical', 'clinicaldraft')]:
            perms = Permission.objects.filter(content_type__app_label=app)
            self.author.user_permissions.add(*perms.filter(codename__in=[f'view_{entity}', f'add_{entity}']))
            self.reviewer.user_permissions.add(*perms.filter(codename__in=[f'view_{entity}', f'review_{entity}']))
        self.claim, _ = record_claim(actor=self.author, data=dict(source_name='منبع ساختگی',
            source_url='https://example.org/race', owner='مالک فرضی', evidence_url='https://example.org/proof',
            evidence_note='', claims_collection=True, claims_storage=False, claims_publication=False,
            starts_on=None, expires_on=None))
        self.draft = create_draft(actor=self.author, data=dict(subject='موضوع فرضی', audience='patient',
            title='عنوان ساختگی', statement='گزاره ساختگی برای آزمون', reference_title='مرجع فرضی',
            reference_url='https://example.org/race-ref', reference_location='بخش فرضی', reference_author='',
            reference_version='', reference_published_on=None, reference_accessed_on=None))

    def worker(self, operation):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '2s'")
                cursor.execute("SET statement_timeout = '12s'")
            return operation()
        finally:
            connection.close()

    def test_author_account_is_not_locked_by_source_or_clinical_review(self):
        from daroobank.account_checks import current_account_exists
        for domain in ('sources', 'clinical'):
            with self.subTest(domain=domain):
                get_user_model().objects.filter(pk=self.author.pk).update(is_active=True)
                ready, resume = Event(), Event()
                def pause(pk, *, using):
                    present = current_account_exists(pk, using=using)
                    ready.set()
                    if not resume.wait(8):
                        raise TimeoutError('Synthetic writer did not resume')
                    return present
                def review():
                    actor = get_user_model().objects.get(pk=self.reviewer.pk)
                    if domain == 'sources':
                        return review_claim(actor=actor, claim_id=self.claim.pk, decision='defer',
                            reason='دلیل ساختگی برای این آزمون هم‌زمانی', expected_review=0,
                            expected_hash=self.claim.payload_sha256)
                    return review_draft(actor=actor, draft_id=self.draft.pk, decision='defer',
                        reason='دلیل ساختگی برای این آزمون هم‌زمانی', expected_review=0,
                        expected_hash=self.draft.payload_sha256,
                        expected_evidence_hash=evidence_state(self.draft)['fingerprint'])
                with patch(f'{domain}.services.current_account_exists', side_effect=pause):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(self.worker, review)
                        try:
                            self.assertTrue(ready.wait(8))
                            self.assertEqual(get_user_model().objects.filter(pk=self.author.pk).update(is_active=False), 1)
                        finally:
                            resume.set()
                        self.assertIsNotNone(future.result(timeout=10))
                self.assertFalse(get_user_model().objects.get(pk=self.author.pk).is_active)
