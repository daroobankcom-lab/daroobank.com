"""Synthetic current-recorder clues in the source queue, not attribution proof."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from sources.models import SourceClaim
from sources.services import record_claim


@override_settings(STAFF_PORTAL_ENABLED=True)
class SourceQueueRecorderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('queue-recorder-author', is_staff=True)
        cls.viewer = User.objects.create_user('queue-recorder-viewer', is_staff=True)
        cls.other = User.objects.create_user('queue-recorder-other', is_staff=True)
        cls.viewer.user_permissions.add(Permission.objects.get(content_type__app_label='sources', codename='view_sourceclaim'))
        cls.author.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources',
                                        codename__in=['view_sourceclaim', 'add_sourceclaim']))
        cls.data = dict(source_name='نام ساختگی صف', source_url='https://example.org/0', owner='مالک ساختگی',
                        evidence_url='https://example.org/proof', evidence_note='', claims_collection=True,
                        claims_storage=False, claims_publication=False, starts_on=None, expires_on=None)
        cls.claim, _ = record_claim(actor=cls.author, data=cls.data)
        cls.missing = 2_147_483_000

    def test_missing_recorder_warning_is_local_private_and_does_not_change_date(self):
        try:
            SourceClaim.objects.filter(pk=self.claim.pk).update(recorded_by_id=self.missing)
            self.client.force_login(self.viewer)
            response = self.client.get(reverse('staff_sources'))
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, 'حساب ثبت‌کننده در دسترس نیست')
            self.assertContains(response, self.data['source_name'])
            self.assertNotContains(response, str(self.missing))
            self.assertEqual(response.context['date_counts']['unknown'], 1)
            self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
            self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
            self.assertEqual(response['Referrer-Policy'], 'same-origin')
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(reverse('staff_sources')).status_code, 403)
        finally:
            SourceClaim.objects.filter(pk=self.claim.pk).update(recorded_by_id=self.author.pk)

    def test_inactive_existing_recorder_does_not_trigger_missing_warning(self):
        get_user_model().objects.filter(pk=self.author.pk).update(is_active=False, is_staff=False)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_sources'))
        self.assertNotContains(response, 'حساب ثبت‌کننده در دسترس نیست')
        self.assertContains(response, 'وجود حساب به معنی فعال بودن یا احراز صلاحیت نیست')

    def test_one_lookup_for_page_not_one_per_row_or_lookahead(self):
        for i in range(25):
            record_claim(actor=self.author, data={**self.data, 'source_url': f'https://example.org/{i + 1}'})
        self.client.force_login(self.viewer)
        path = reverse('staff_sources')
        with patch('sources.staff_views.current_accounts', wraps=__import__(
                'daroobank.account_checks', fromlist=['current_accounts']).current_accounts) as lookup:
            with CaptureQueriesContext(connection) as captured:
                response = self.client.get(path)
        self.assertEqual(len(response.context['page'].object_list), 20)
        lookup.assert_called_once()
        self.assertEqual(len(lookup.call_args.args[0]), 20)
        account_reads = [q for q in captured if '"auth_user"' in q['sql'].lower() and ' in ' in q['sql'].lower()]
        self.assertEqual(len(account_reads), 1)
        with patch('sources.staff_views.current_accounts', wraps=lookup._mock_wraps) as next_lookup:
            second = self.client.get(path, {'page': 2})
            self.assertEqual(len(second.context['page'].object_list), 6)
            self.assertEqual(len(next_lookup.call_args.args[0]), 6)

    def test_empty_filtered_page_skips_account_lookup(self):
        self.client.force_login(self.viewer)
        with patch('sources.staff_views.current_accounts') as lookup:
            response = self.client.get(reverse('staff_sources'), {'status': 'reject'})
        self.assertEqual(len(response.context['page'].object_list), 0)
        lookup.assert_not_called()

    def test_reads_are_separate_not_a_snapshot(self):
        self.client.force_login(self.viewer)
        with patch('sources.staff_views.current_accounts', return_value={}):
            self.assertContains(self.client.get(reverse('staff_sources')), 'حساب ثبت‌کننده در دسترس نیست')
        self.assertNotContains(self.client.get(reverse('staff_sources')), 'حساب ثبت‌کننده در دسترس نیست')
