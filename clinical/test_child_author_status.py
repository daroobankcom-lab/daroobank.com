"""Synthetic child previews distinguish missing accounts from malformed content."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .models import ClinicalDraft
from .services import create_draft


@override_settings(STAFF_PORTAL_ENABLED=True)
class ChildAuthorStatusTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('child-author', is_staff=True)
        cls.viewer = User.objects.create_user('child-viewer', is_staff=True)
        perms = Permission.objects.filter(content_type__app_label='clinical')
        cls.author.user_permissions.add(*perms.filter(codename__in=['view_clinicaldraft', 'add_clinicaldraft']))
        cls.viewer.user_permissions.add(perms.get(codename='view_clinicaldraft'))
        cls.data = dict(subject='موضوع ساختگی', audience='patient', title='عنوان ساختگی',
                        statement='متن ساختگی', reference_title='ارجاع ساختگی',
                        reference_url='https://example.org/clinical', reference_location='بخش ساختگی',
                        reference_author='', reference_version='', reference_published_on=None, reference_accessed_on=None)
        cls.missing = 2_147_483_000

    def draft(self):
        return create_draft(actor=self.author, data=self.data)
    def test_child_preview_distinguishes_missing_author_and_keeps_limit(self):
        parent = self.draft()
        children = [create_draft(actor=self.author, data={**self.data, 'title': f'عنوان فرزند {n}'},
                    parent_id=parent.pk, expected_parent_hash=parent.payload_sha256,
                    change_reason='دلیل اصلاح ساختگی') for n in range(12)]
        missing, invalid, oversized = children[-1], children[-2], children[-3]
        try:
            ClinicalDraft.objects.filter(pk=missing.pk).update(author_id=self.missing)
            ClinicalDraft.objects.filter(pk=invalid.pk).update(author_id=self.missing, title='عنوان ناسازگار')
            ClinicalDraft.objects.filter(pk=oversized.pk).update(statement='آ' * 100_000 + 'hidden-child-canary')
            self.client.force_login(self.viewer)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(reverse('staff_clinical_detail', args=[parent.pk]))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(response.context['children']), 10)
            self.assertTrue(response.context['children_limited'])
            by_id = {c.pk: c for c in response.context['children']}
            self.assertEqual(by_id[missing.pk].preview_status, 'author_missing')
            self.assertEqual(by_id[invalid.pk].preview_status, 'invalid')
            self.assertEqual(by_id[oversized.pk].preview_status, 'oversized')
            self.assertEqual(by_id[children[-4].pk].preview_status, 'available')
            self.assertContains(response, 'حساب نویسنده در دسترس نیست')
            self.assertContains(response, 'داده ناسازگار')
            self.assertContains(response, 'نسخه بیش از حد بازرسی؛ سازگاری بررسی نشد')
            self.assertNotContains(response, 'hidden-child-canary')
            self.assertNotContains(response, str(self.missing))
            self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
            account_selects = [q['sql'] for q in queries if 'FROM "auth_user"' in q['sql'] and ' IN ' in q['sql']]
            self.assertLessEqual(len(account_selects), 2)
        finally:
            ClinicalDraft.objects.filter(pk__in=[missing.pk, invalid.pk]).update(author_id=self.author.pk)

    def test_invalid_or_oversized_children_do_not_trigger_account_lookup(self):
        parent = self.draft()
        invalid = create_draft(actor=self.author, data=self.data, parent_id=parent.pk,
                    expected_parent_hash=parent.payload_sha256, change_reason='دلیل اصلاح ساختگی')
        oversized = create_draft(actor=self.author, data=self.data, parent_id=parent.pk,
                    expected_parent_hash=parent.payload_sha256, change_reason='دلیل اصلاح ساختگی')
        ClinicalDraft.objects.filter(pk=invalid.pk).update(title='عنوان ناسازگار')
        ClinicalDraft.objects.filter(pk=oversized.pk).update(statement='آ' * 100_000)
        self.client.force_login(self.viewer)
        with patch('clinical.staff_views.current_account_ids') as lookup:
            response = self.client.get(reverse('staff_clinical_detail', args=[parent.pk]))
        lookup.assert_not_called()
        self.assertEqual([child.preview_status for child in response.context['children']], ['oversized', 'invalid'])

    def test_only_valid_visible_children_are_included_in_one_account_lookup(self):
        parent = self.draft()
        child = create_draft(actor=self.author, data=self.data, parent_id=parent.pk,
                    expected_parent_hash=parent.payload_sha256, change_reason='دلیل اصلاح ساختگی')
        self.client.force_login(self.viewer)
        with patch('clinical.staff_views.current_account_ids', return_value=set()) as lookup:
            response = self.client.get(reverse('staff_clinical_detail', args=[parent.pk]))
        self.assertEqual(response.context['children'][0].preview_status, 'author_missing')
        lookup.assert_called_once_with([child.author_id], using='default')
