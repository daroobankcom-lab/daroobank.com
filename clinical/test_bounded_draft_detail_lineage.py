"""Synthetic bounds for clinical detail and parent-lineage reads."""
from unittest.mock import patch

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import test_lineage as fixtures
from .lineage import InvalidLineageCursor, inspect_lineage
from .legacy_reason_test_utils import set_legacy_reason
from .models import ClinicalDraft
from .services import DraftConflict, create_draft, valid_draft


@override_settings(STAFF_PORTAL_ENABLED=True)
class BoundedClinicalDetailLineageTests(TestCase):
    chain = fixtures.ClinicalLineageTests.chain
    inspect = fixtures.ClinicalLineageTests.inspect

    @classmethod
    def setUpTestData(cls):
        fixtures.ClinicalLineageTests.setUpTestData.__func__(cls)

    def assert_bounded(self, queries):
        selects = [q['sql'] for q in queries if q['sql'].startswith('SELECT') and 'FROM "clinical_clinicaldraft"' in q['sql']]
        self.assertTrue(selects)
        for sql in selects:
            if 'SELECT 1 ' in sql or 'COUNT(' in sql:
                continue
            selection = sql.rsplit(' FROM "clinical_clinicaldraft"', 1)[0].lower()
            self.assertGreaterEqual(selection.count('substring'), 4)
            self.assertNotRegex(selection, r'(?:^select |, )(?:"clinical_clinicaldraft"|t\d+)\."(?:statement|change_reason)"(?:,|$)')

    def test_current_or_parent_oversized_detail_and_lineage_are_uninspected(self):
        parent, child = self.chain(1)
        self.client.force_login(self.viewer)
        for target, field in [(child, 'statement'), (child, 'change_reason'), (parent, 'statement')]:
            original = getattr(target, field)
            with self.subTest(pk=target.pk, field=field):
                ClinicalDraft.objects.filter(pk=target.pk).update(**{field: 'آ' * 1_000_000 + 'private-canary'})
                try:
                    with CaptureQueriesContext(connection) as queries:
                        response = self.client.get(reverse('staff_clinical_detail', args=[child.pk]))
                    self.assertContains(response, 'نسخه یا والد بیش از حد بازرسی است؛ سازگاری بررسی نشد')
                    self.assertNotContains(response, 'private-canary')
                    self.assertNotContains(response, self.data['statement'])
                    self.assertFalse(response.context['can_review'])
                    self.assertIn('no-store', response['Cache-Control'])
                    self.assert_bounded(queries)
                    with CaptureQueriesContext(connection) as queries:
                        report = self.inspect(child)
                    self.assertEqual(report['status'], 'oversized')
                    self.assertEqual(report['rows'], [])
                    self.assertIsNone(report['next_cursor'])
                    self.assert_bounded(queries)
                    response = self.client.get(reverse('staff_clinical_lineage', args=[child.pk]))
                    self.assertContains(response, 'نسخه یا والد بیش از حد بازرسی است؛ سازگاری بررسی نشد')
                    self.assertNotContains(response, 'private-canary')
                finally:
                    ClinicalDraft.objects.filter(pk=target.pk).update(**{field: original})

    def test_valid_oversized_reason_is_not_mislabeled_in_detail_or_lineage(self):
        parent = self.chain(0)[0]
        reason = 'دلیل ساختگی قابل بررسی' + ' ' * 100_000
        child = create_draft(actor=self.author, data=self.data, parent_id=parent.pk,
                             expected_parent_hash=parent.payload_sha256, change_reason=reason)
        set_legacy_reason(child, reason)
        self.assertTrue(valid_draft(ClinicalDraft.objects.select_related('parent').get(pk=child.pk)))
        self.assertEqual(self.inspect(child)['status'], 'oversized')
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_clinical_detail', args=[child.pk]))
        self.assertContains(response, 'نسخه یا والد بیش از حد بازرسی است؛ سازگاری بررسی نشد')
        self.assertNotContains(response, 'داده این نسخه یا والد مستقیم آن ناسازگار است')

    def test_children_and_lookahead_are_bounded_with_existing_cap(self):
        root = self.chain(0)[0]
        children = [create_draft(actor=self.author, data={**self.data, 'title': f'فرزند ساختگی {i}'},
            parent_id=root.pk, expected_parent_hash=root.payload_sha256, change_reason=self.reason) for i in range(11)]
        ClinicalDraft.objects.filter(pk=children[0].pk).update(statement='آ' * 1_000_000 + 'lookahead-canary')
        ClinicalDraft.objects.filter(pk=children[-1].pk).update(change_reason='ر' * 1_000_000 + 'child-canary')
        self.client.force_login(self.viewer)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('staff_clinical_detail', args=[root.pk]))
        self.assertEqual(len(response.context['children']), 10)
        self.assertTrue(response.context['children_limited'])
        self.assertContains(response, 'نسخه بیش از حد بازرسی؛ سازگاری بررسی نشد')
        self.assertNotContains(response, 'child-canary')
        self.assertNotContains(response, 'lookahead-canary')
        self.assert_bounded(queries)

    def test_invalid_cursor_not_accepted_when_anchor_oversized(self):
        child = self.chain(1)[-1]
        ClinicalDraft.objects.filter(pk=child.pk).update(statement='آ' * 100_000)
        with self.assertRaises(InvalidLineageCursor):
            self.inspect(child, cursor='invalid-canary')

    def test_oversized_intermediate_parent_stops_before_its_link(self):
        nodes = self.chain(4)
        ClinicalDraft.objects.filter(pk=nodes[1].pk).update(change_reason='ر' * 100_000)
        with CaptureQueriesContext(connection) as queries:
            result = self.inspect(nodes[-1])
        self.assertEqual(result['status'], 'oversized')
        self.assertEqual(len(result['rows']), 2)
        self.assertNotIn(nodes[1].pk, [row['parent_id'] for row in result['rows']])
        self.assertIsNone(result['next_cursor'])
        self.assert_bounded(queries)

    def test_oversized_cursor_current_is_rejected_without_fallback(self):
        from django.core import signing
        from .lineage import CURSOR_SALT, PAGE_SIZE
        nodes = self.chain(PAGE_SIZE + 1)
        token = self.inspect(nodes[-1])['next_cursor']
        current_id = signing.loads(token, salt=CURSOR_SALT)['current']
        ClinicalDraft.objects.filter(pk=current_id).update(statement='آ' * 100_000)
        with CaptureQueriesContext(connection) as queries:
            with self.assertRaises(InvalidLineageCursor):
                self.inspect(nodes[-1], token)
        self.assert_bounded(queries)

    def test_permission_and_invalid_forms_remain_private(self):
        child = self.chain(1)[-1]
        ClinicalDraft.objects.filter(pk=child.pk).update(statement='آ' * 100_000 + 'private-canary')
        self.client.force_login(self.no_view)
        for route in ['staff_clinical_detail', 'staff_clinical_lineage']:
            self.assertEqual(self.client.get(reverse(route, args=[child.pk])).status_code, 403)
        from django.contrib.auth.models import Permission
        self.viewer.user_permissions.add(Permission.objects.get(content_type__app_label='clinical', codename='review_clinicaldraft'))
        self.client.force_login(self.viewer)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(reverse('staff_clinical_review', args=[child.pk]), {})
        self.assertEqual(response.status_code, 400)
        self.assertContains(response, 'نسخه یا والد بیش از حد بازرسی است؛ سازگاری بررسی نشد', status_code=400)
        self.assertNotContains(response, 'private-canary', status_code=400)
        self.assertIn('no-store', response['Cache-Control'])
        self.assert_bounded(queries)
        for route in ['staff_clinical_revise', 'staff_clinical_reference_create']:
            # Give add permission, then verify GET does not expose an edit form.
            self.viewer.user_permissions.add(Permission.objects.get(content_type__app_label='clinical', codename='add_clinicaldraft'))
            for key in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
                self.viewer.__dict__.pop(key, None)
            self.client.force_login(self.viewer)
            response = self.client.get(reverse(route, args=[child.pk]))
            self.assertEqual(response.status_code, 409)
            self.assertContains(response, 'نسخه یا والد بیش از حد بازرسی است؛ سازگاری بررسی نشد', status_code=409)
            self.assertNotContains(response, 'private-canary', status_code=409)

    def test_failed_form_and_conflict_refresh_are_bounded(self):
        child = self.chain(1)[-1]
        from django.contrib.auth.models import Permission
        self.viewer.user_permissions.add(Permission.objects.get(content_type__app_label='clinical', codename='review_clinicaldraft'))
        self.client.force_login(self.viewer)
        def conflict(**kwargs):
            ClinicalDraft.objects.filter(pk=child.pk).update(statement='آ' * 100_000 + 'race-canary')
            raise DraftConflict('تداخل ساختگی')
        from .evidence import evidence_state
        with patch('clinical.staff_views.review_draft', side_effect=conflict):
            with CaptureQueriesContext(connection) as queries:
                response = self.client.post(reverse('staff_clinical_review', args=[child.pk]), {
                    'decision': 'defer', 'reason': 'توضیح ساختگی برای بررسی بیشتر', 'expected_review': 0,
                    'expected_hash': child.payload_sha256, 'expected_evidence_hash': evidence_state(child)['fingerprint']})
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'نسخه یا والد بیش از حد بازرسی است؛ سازگاری بررسی نشد', status_code=409)
        self.assertNotContains(response, 'race-canary', status_code=409)
        self.assert_bounded(queries)
