"""Synthetic author-presence checks in the bounded clinical inspection."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .evidence import add_reference, evidence_state
from .inspection import inspect_drafts
from .models import ClinicalDraft, ClinicalReferenceAssertion
from .services import create_draft


@override_settings(STAFF_PORTAL_ENABLED=True)
class ClinicalInspectionAuthorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('inspection-author-check', is_staff=True)
        cls.viewer = User.objects.create_user('inspection-author-viewer', is_staff=True)
        perms = Permission.objects.filter(content_type__app_label='clinical')
        cls.author.user_permissions.add(*perms.filter(codename__in=['view_clinicaldraft', 'add_clinicaldraft']))
        cls.viewer.user_permissions.add(perms.get(codename='view_clinicaldraft'))
        cls.data = dict(subject='موضوع ساختگی', audience='patient', title='عنوان محرمانه ساختگی',
                        statement='این متن ساختگی است و در گزارش نباید دیده شود.', reference_title='ارجاع ساختگی',
                        reference_url='https://example.org/clinical-private', reference_location='بخش ساختگی',
                        reference_author='', reference_version='', reference_published_on=None, reference_accessed_on=None)
        cls.missing = 2_147_483_000

    def draft(self):
        return create_draft(actor=self.author, data=self.data)

    def test_missing_author_is_separate_bounded_status_and_private(self):
        missing, healthy = self.draft(), self.draft()
        try:
            ClinicalDraft.objects.filter(pk=missing.pk).update(author_id=self.missing)
            with CaptureQueriesContext(connection) as queries:
                report = inspect_drafts()
            self.assertEqual(report['rows'], [{'id': missing.pk, 'status': 'author_missing'},
                                               {'id': healthy.pk, 'status': 'available'}])
            self.assertLessEqual(len(queries), 4)
            self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in queries))
            self.assertEqual(inspect_drafts(category='author_missing')['rows'], [report['rows'][0]])
            self.client.force_login(self.viewer)
            response = self.client.get(reverse('staff_clinical_inspection'), {'category': 'author_missing'})
            self.assertContains(response, 'حساب نویسنده در دسترس نیست')
            self.assertNotContains(response, self.data['title'])
            self.assertNotContains(response, self.data['statement'])
            self.assertNotContains(response, self.data['reference_url'])
            self.assertNotContains(response, str(self.missing))
            self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
            self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        finally:
            ClinicalDraft.objects.filter(pk=missing.pk).update(author_id=self.author.pk)

    def test_invalid_draft_takes_precedence_and_does_not_lookup_authors_or_evidence(self):
        draft = self.draft()
        try:
            ClinicalDraft.objects.filter(pk=draft.pk).update(author_id=self.missing, title='تغییر ناسازگار')
            with patch('clinical.inspection.current_account_ids') as accounts, patch('clinical.inspection.inspection_evidence_statuses') as evidence:
                self.assertEqual(inspect_drafts()['rows'], [{'id': draft.pk, 'status': 'draft_invalid'}])
                accounts.assert_not_called()
                evidence.assert_not_called()
        finally:
            ClinicalDraft.objects.filter(pk=draft.pk).update(author_id=self.author.pk, title=self.data['title'])

    def test_existing_inactive_nonstaff_author_is_not_treated_as_missing(self):
        draft = self.draft()
        get_user_model().objects.filter(pk=self.author.pk).update(is_active=False, is_staff=False)
        self.assertEqual(inspect_drafts()['rows'], [{'id': draft.pk, 'status': 'available'}])

    def test_filtered_pagination_uses_last_scanned_row_not_last_match(self):
        drafts = [self.draft() for _ in range(51)]
        try:
            ClinicalDraft.objects.filter(pk=drafts[-1].pk).update(author_id=self.missing)
            first = inspect_drafts(category='author_missing')
            self.assertEqual((first['scanned'], first['rows'], first['next_after']), (50, [], drafts[49].pk))
            second = inspect_drafts(category='author_missing', after=first['next_after'])
            self.assertEqual(second['rows'], [{'id': drafts[-1].pk, 'status': 'author_missing'}])
            self.assertIsNone(second['next_after'])
        finally:
            ClinicalDraft.objects.filter(pk=drafts[-1].pk).update(author_id=self.author.pk)

    def test_current_author_lookup_is_not_a_lock_or_a_snapshot(self):
        draft = self.draft()
        with patch('clinical.inspection.current_account_ids', return_value={}) as accounts:
            self.assertEqual(inspect_drafts()['rows'], [{'id': draft.pk, 'status': 'author_missing'}])
            accounts.assert_called_once()
        self.assertEqual(inspect_drafts()['rows'], [{'id': draft.pk, 'status': 'available'}])

    def test_missing_author_takes_precedence_and_skips_evidence(self):
        draft = self.draft()
        data = {key: self.data[key] for key in ('reference_title', 'reference_url', 'reference_location',
                'reference_author', 'reference_version', 'reference_published_on', 'reference_accessed_on')}
        reference, _ = add_reference(actor=self.author, draft_id=draft.pk, data={**data, 'relation': 'context'},
            expected_draft_hash=draft.payload_sha256, expected_evidence_hash=evidence_state(draft)['fingerprint'])
        try:
            ClinicalReferenceAssertion.objects.filter(pk=reference.pk).update(reference_title='تغییر ناسازگار')
            ClinicalDraft.objects.filter(pk=draft.pk).update(author_id=self.missing)
            with patch('clinical.inspection.inspection_evidence_statuses') as evidence:
                self.assertEqual(inspect_drafts()['rows'], [{'id': draft.pk, 'status': 'author_missing'}])
                evidence.assert_not_called()
            ClinicalDraft.objects.filter(pk=draft.pk).update(author_id=self.author.pk)
            self.assertEqual(inspect_drafts()['rows'], [{'id': draft.pk, 'status': 'evidence_invalid'}])
        finally:
            ClinicalDraft.objects.filter(pk=draft.pk).update(author_id=self.author.pk)

    def test_parent_author_is_not_checked_when_inspecting_child(self):
        parent = self.draft()
        child = create_draft(actor=self.author, data=self.data, parent_id=parent.pk,
            expected_parent_hash=parent.payload_sha256, change_reason='دلیل ساختگی برای اصلاح')
        try:
            ClinicalDraft.objects.filter(pk=parent.pk).update(author_id=self.missing)
            self.assertEqual(inspect_drafts()['rows'], [{'id': parent.pk, 'status': 'author_missing'},
                                                        {'id': child.pk, 'status': 'available'}])
        finally:
            ClinicalDraft.objects.filter(pk=parent.pk).update(author_id=self.author.pk)
