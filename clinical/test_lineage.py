import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .lineage import (CURSOR_MAX_AGE, CURSOR_SALT, MAX_CURSOR_LENGTH, PAGE_SIZE,
                      InvalidLineageCursor, LineageNotFound, inspect_lineage)
from .models import ClinicalDraft, ClinicalDraftReview
from .services import create_draft, draft_data, fingerprint, valid_draft, valid_payload


@override_settings(STAFF_PORTAL_ENABLED=True)
class ClinicalLineageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.author = User.objects.create_user('clinical-lineage-author', is_staff=True)
        cls.viewer = User.objects.create_user('clinical-lineage-viewer', is_staff=True)
        cls.no_view = User.objects.create_user('clinical-lineage-no-view', is_staff=True)
        cls.regular = User.objects.create_user('clinical-lineage-regular')
        cls.inactive = User.objects.create_user('clinical-lineage-inactive', is_staff=True, is_active=False)
        perms = Permission.objects.filter(content_type__app_label='clinical')
        view = perms.get(codename='view_clinicaldraft')
        cls.author.user_permissions.add(view, perms.get(codename='add_clinicaldraft'))
        for actor in [cls.viewer, cls.regular, cls.inactive]:
            actor.user_permissions.add(view)
        cls.data = {'subject': 'موضوع ساختگی خصوصی', 'audience': 'patient', 'title': 'عنوان ساختگی خصوصی',
                    'statement': 'متن خصوصی ساختگی برای آزمون زنجیره', 'reference_title': 'مرجع ساختگی',
                    'reference_url': 'https://example.org/lineage', 'reference_location': 'بخش ساختگی',
                    'reference_author': '', 'reference_version': '', 'reference_published_on': None,
                    'reference_accessed_on': None}
        cls.reason = 'دلیل خصوصی ساختگی برای اصلاح'

    def chain(self, size):
        nodes = [create_draft(actor=self.author, data=self.data)]
        for i in range(size):
            parent = nodes[-1]
            nodes.append(create_draft(actor=self.author, data={**self.data, 'title': f'عنوان ساختگی خصوصی {i}'},
                         parent_id=parent.pk, expected_parent_hash=parent.payload_sha256, change_reason=self.reason))
        return nodes

    def inspect(self, node, cursor=''):
        return inspect_lineage(actor=self.viewer, anchor_id=node.pk, cursor=cursor)

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_root_single_branch_and_no_writes(self):
        root, child = self.chain(1)
        branch = create_draft(actor=self.author, data=self.data, parent_id=root.pk,
                              expected_parent_hash=root.payload_sha256, change_reason=self.reason)
        with patch('socket.create_connection', side_effect=AssertionError('network forbidden')):
            root_report = self.inspect(root)
            child_report = self.inspect(child)
            branch_report = self.inspect(branch)
        self.assertEqual(root_report['status'], 'no_parent')
        self.assertEqual(root_report['rows'], [])
        self.assertEqual(child_report['rows'], [{'child_id': child.pk, 'parent_id': root.pk, 'depth': 1}])
        self.assertEqual(branch_report['rows'][0]['child_id'], branch.pk)
        self.assertEqual(ClinicalDraft.objects.count(), 3)
        self.assertEqual(ClinicalDraftReview.objects.count(), 0)
        self.client.force_login(self.viewer)
        path = reverse('staff_clinical_lineage', args=[child.pk])
        self.assertContains(self.client.get(reverse('staff_clinical_detail', args=[child.pk])), path)
        response = self.client.get(path)
        self.assertContains(response, reverse('staff_clinical_detail', args=[root.pk]))
        for text in [self.data['subject'], self.data['title'], self.data['statement'], self.data['reference_url'],
                     self.reason, child.payload_sha256]:
            self.assertNotContains(response, text)
        self.assert_private(response)

    def test_page_boundaries_and_query_limits(self):
        nodes = self.chain(PAGE_SIZE * 2 + 1)
        leaf = nodes[-1]
        self.assertTrue(self.viewer.has_perm('clinical.view_clinicaldraft'))  # exclude auth-cache warmup
        with CaptureQueriesContext(connection) as queries:
            first = self.inspect(leaf)
        self.assertLessEqual(len(queries), 20)
        self.assertTrue(all(q['sql'].lstrip().upper().startswith('SELECT') for q in queries))
        self.assertEqual(first['status'], 'more')
        self.assertEqual(len(first['rows']), PAGE_SIZE)
        self.assertEqual([row['child_id'] for row in first['rows']], [x.pk for x in nodes[:0:-1][:PAGE_SIZE]])
        decoded = signing.loads(first['next_cursor'], salt=CURSOR_SALT)
        self.assertNotEqual(decoded['anchor_hash'], leaf.payload_sha256)
        self.assertNotIn(self.reason, first['next_cursor'])
        with CaptureQueriesContext(connection) as queries:
            second = self.inspect(leaf, first['next_cursor'])
        self.assertLessEqual(len(queries), 21)
        self.assertEqual(second['status'], 'more')
        third = self.inspect(leaf, second['next_cursor'])
        self.assertEqual(third['status'], 'no_parent')
        self.assertEqual([r['depth'] for r in first['rows'] + second['rows'] + third['rows']], list(range(1, 42)))
        self.assertEqual(third['rows'][-1]['parent_id'], nodes[0].pk)
        self.assertIsNone(third['next_cursor'])
        # Exactly 20 links terminates without a pointless continuation.
        exact = self.inspect(nodes[20])
        self.assertEqual(exact['status'], 'no_parent')
        self.assertEqual(len(exact['rows']), PAGE_SIZE)
        self.assertIsNone(exact['next_cursor'])
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_clinical_lineage', args=[leaf.pk]))
        self.assertContains(response, 'بررسی بخش بعدی')
        self.assertNotContains(response, self.data['statement'])
        response = self.client.get(reverse('staff_clinical_lineage', args=[leaf.pk]), {'cursor': first['next_cursor']})
        self.assertContains(response, 'گام 21')

    def test_inconsistency_stops_before_bad_link_and_hides_data(self):
        nodes = self.chain(4)
        ClinicalDraft.objects.filter(pk=nodes[1].pk).update(statement='پیام محرمانه ناسازگار')
        report = self.inspect(nodes[-1])
        self.assertEqual(report['status'], 'inconsistent')
        self.assertEqual(len(report['rows']), 2)
        self.assertIsNone(report['next_cursor'])
        self.assertNotIn(nodes[1].pk, [r['parent_id'] for r in report['rows']])
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_clinical_lineage', args=[nodes[-1].pk]))
        self.assertContains(response, 'ناسازگار است')
        self.assertNotContains(response, 'پیام محرمانه ناسازگار')
        ClinicalDraft.objects.filter(pk=nodes[-1].pk).update(statement='نسخه ناسازگار محرمانه')
        report = self.inspect(nodes[-1])
        self.assertEqual(report['status'], 'inconsistent')
        self.assertEqual(report['rows'], [])
        self.assertContains(self.client.get(reverse('staff_clinical_detail', args=[nodes[-1].pk])),
                            reverse('staff_clinical_lineage', args=[nodes[-1].pk]))

    def test_missing_parent_with_valid_child_payload_is_not_treated_as_root(self):
        gap = create_draft(actor=self.author, data=self.data)
        gap_id = gap.pk
        ClinicalDraft.objects.filter(pk=gap_id).delete()
        root, child = self.chain(1)
        original = (child.parent_id, child.parent_payload_sha256, child.payload_sha256)
        digest = fingerprint(draft_data(child), gap_id, root.payload_sha256, child.change_reason)
        try:
            ClinicalDraft.objects.filter(pk=child.pk).update(parent_id=gap_id, payload_sha256=digest)
            child.refresh_from_db()
            self.assertTrue(valid_payload(child))
            report = self.inspect(child)
            self.assertEqual(report['status'], 'inconsistent')
            self.assertEqual(report['rows'], [])
        finally:
            ClinicalDraft.objects.filter(pk=child.pk).update(parent_id=original[0], parent_payload_sha256=original[1],
                                                              payload_sha256=original[2])

    def test_coherent_parent_change_between_reads_stops_at_seam(self):
        nodes = self.chain(3)
        parent = nodes[-2]
        original = (parent.title, parent.payload_sha256)
        altered = {**draft_data(parent), 'title': 'تغییر همزمان ساختگی'}
        digest = fingerprint(altered, parent.parent_id, parent.parent_payload_sha256, parent.change_reason)
        def validate_then_change(current):
            result = valid_draft(current)
            if current.pk == nodes[-1].pk:
                ClinicalDraft.objects.filter(pk=parent.pk).update(title=altered['title'], payload_sha256=digest)
            return result
        try:
            with patch('clinical.lineage.valid_draft', side_effect=validate_then_change):
                report = self.inspect(nodes[-1])
            self.assertEqual(report['status'], 'inconsistent')
            self.assertEqual(len(report['rows']), 1)
            self.assertIsNone(report['next_cursor'])
        finally:
            ClinicalDraft.objects.filter(pk=parent.pk).update(title=original[0], payload_sha256=original[1])

    def test_cursor_validation_expiration_binding_and_nonreflection(self):
        nodes = self.chain(PAGE_SIZE + 1)
        leaf = nodes[-1]
        token = self.inspect(leaf)['next_cursor']
        data = signing.loads(token, salt=CURSOR_SALT)
        with patch('django.core.signing.time.time', return_value=time.time() - CURSOR_MAX_AGE - 5):
            expired = signing.dumps(data, salt=CURSOR_SALT)
        invalid = ['canary<script>', token + 'x', '.' + token, 'a' * (MAX_CURSOR_LENGTH + 1), expired]
        for change in [dict(depth=True), dict(depth=19), dict(depth=100000), dict(anchor=True),
                       dict(current=leaf.pk), dict(current_hash='a' * 63), dict(extra=1)]:
            invalid.append(signing.dumps({**data, **change}, salt=CURSOR_SALT))
        for item in invalid:
            with self.subTest(item=item[:12]), self.assertRaises(InvalidLineageCursor):
                self.inspect(leaf, item)
        with self.assertRaises(InvalidLineageCursor):
            self.inspect(nodes[-2], token)
        self.client.force_login(self.viewer)
        path = reverse('staff_clinical_lineage', args=[leaf.pk])
        response = self.client.get(path, {'cursor': 'canary<script>'})
        self.assertEqual(response.status_code, 400)
        self.assertNotContains(response, 'canary', status_code=400)
        self.assertContains(response, f'href="{path}"', status_code=400)
        self.assert_private(response)

    def test_cursor_rejects_changed_anchor_or_current_and_rechecks_permissions(self):
        nodes = self.chain(PAGE_SIZE + 1)
        leaf = nodes[-1]
        token = self.inspect(leaf)['next_cursor']
        current_id = signing.loads(token, salt=CURSOR_SALT)['current']
        ClinicalDraft.objects.filter(pk=current_id).update(statement='بيانات ناسازگار')
        with self.assertRaises(InvalidLineageCursor): self.inspect(leaf, token)
        ClinicalDraft.objects.filter(pk=current_id).update(statement=self.data['statement'])
        ClinicalDraft.objects.filter(pk=leaf.pk).update(statement='بيانات ناسازگار')
        with self.assertRaises(InvalidLineageCursor): self.inspect(leaf, token)
        with self.assertRaises(PermissionDenied):
            inspect_lineage(actor=self.no_view, anchor_id=leaf.pk, cursor=token)

    def test_coherent_payload_changes_invalidate_cursor(self):
        nodes = self.chain(PAGE_SIZE + 1)
        leaf = nodes[-1]
        token = self.inspect(leaf)['next_cursor']
        current_id = signing.loads(token, salt=CURSOR_SALT)['current']
        for node_id in [current_id, leaf.pk]:
            node = ClinicalDraft.objects.get(pk=node_id)
            original = (node.title, node.payload_sha256)
            data = {**draft_data(node), 'title': 'تغییر سازگار ساختگی'}
            digest = fingerprint(data, node.parent_id, node.parent_payload_sha256, node.change_reason)
            try:
                ClinicalDraft.objects.filter(pk=node_id).update(title=data['title'], payload_sha256=digest)
                self.assertTrue(valid_payload(ClinicalDraft.objects.get(pk=node_id)))
                with self.assertRaises(InvalidLineageCursor): self.inspect(leaf, token)
            finally:
                ClinicalDraft.objects.filter(pk=node_id).update(title=original[0], payload_sha256=original[1])

    def test_continuation_is_not_a_snapshot_of_prior_links(self):
        nodes = self.chain(PAGE_SIZE + 2)
        leaf = nodes[-1]
        token = self.inspect(leaf)['next_cursor']
        # Change a previously traversed child other than the anchor/current.
        ClinicalDraft.objects.filter(pk=nodes[-2].pk).update(statement='تغییر ناسازگار')
        continuation = self.inspect(leaf, token)
        self.assertEqual(continuation['status'], 'no_parent')
        self.assertEqual(len(continuation['rows']), 2)
        self.assertEqual(self.inspect(leaf)['status'], 'inconsistent')

    def test_permissions_methods_gate_and_invalid_ids(self):
        root = self.chain(0)[0]
        path = reverse('staff_clinical_lineage', args=[root.pk])
        for actor in [None, self.no_view, self.regular, self.inactive]:
            with self.assertRaises(PermissionDenied):
                inspect_lineage(actor=actor, anchor_id=root.pk)
        for value in [0, True, -1, 2**63, '1', 99999999]:
            with self.subTest(value=value), self.assertRaises(LineageNotFound):
                inspect_lineage(actor=self.viewer, anchor_id=value)
        with self.assertRaises(InvalidLineageCursor):
            inspect_lineage(actor=self.viewer, anchor_id=root.pk, cursor=None)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        self.assert_private(response)
        self.client.force_login(self.no_view)
        response = self.client.get(path, {'cursor': 'canary'})
        self.assertEqual(response.status_code, 403)
        self.assert_private(response)
        group_user = get_user_model().objects.create_user('clinical-lineage-group', is_staff=True)
        group = Group.objects.create(name='clinical-lineage-viewers')
        group.permissions.add(Permission.objects.get(content_type__app_label='clinical', codename='view_clinicaldraft'))
        group_user.groups.add(group)
        self.client.force_login(group_user)
        for method, expected in [('get', 200), ('head', 200), ('post', 405)]:
            response = getattr(self.client, method)(path)
            self.assertEqual(response.status_code, expected)
            self.assert_private(response)
        self.assertEqual(self.client.get(reverse('staff_clinical_lineage', args=[2**63])).status_code, 404)
        self.assertNotContains(self.client.get(reverse('sitemap')), path)

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_disabled_portal(self):
        self.client.force_login(self.viewer)
        for method in [self.client.get, self.client.post]:
            response = method(reverse('staff_clinical_lineage', args=[1]))
            self.assertEqual(response.status_code, 404)
            self.assert_private(response)
