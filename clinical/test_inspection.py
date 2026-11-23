from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .evidence import add_reference, evidence_state, inspection_evidence_statuses, reference_fingerprint
from .inspection import InvalidInspection, inspect_drafts
from .models import ClinicalDraft, ClinicalReferenceAssertion
from .services import create_draft


class ClinicalInspectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user = get_user_model()
        cls.author = user.objects.create_user('inspection-author', is_staff=True)
        cls.viewer = user.objects.create_user('inspection-viewer', is_staff=True)
        cls.no_view = user.objects.create_user('inspection-no-view', is_staff=True)
        cls.regular = user.objects.create_user('inspection-regular')
        permissions = Permission.objects.filter(content_type__app_label='clinical')
        view = permissions.get(codename='view_clinicaldraft')
        cls.author.user_permissions.add(view, permissions.get(codename='add_clinicaldraft'))
        cls.viewer.user_permissions.add(view)
        cls.regular.user_permissions.add(view)
        cls.data = {'subject': 'موضوع خصوصی ساختگی', 'audience': 'patient', 'title': 'عنوان خصوصی ساختگی',
                    'statement': 'متن خصوصی ساختگی برای آزمایش', 'reference_title': 'ارجاع ساختگی',
                    'reference_url': 'https://example.org/private', 'reference_location': 'بخش ساختگی',
                    'reference_author': '', 'reference_version': '', 'reference_published_on': None,
                    'reference_accessed_on': None}

    def draft(self):
        return create_draft(actor=self.author, data=self.data)

    def add_ref(self, draft, title='مرجع تکمیلی ساختگی'):
        data = {k: self.data[k] for k in ('reference_title', 'reference_url', 'reference_location',
                'reference_author', 'reference_version', 'reference_published_on', 'reference_accessed_on')}
        data.update(reference_title=title, relation='context')
        return add_reference(actor=self.author, draft_id=draft.pk, data=data,
                             expected_draft_hash=draft.payload_sha256,
                             expected_evidence_hash=evidence_state(draft)['fingerprint'])[0]

    def test_classifies_current_payload_parent_and_evidence_without_exposing_text(self):
        healthy = self.draft()
        broken = self.draft()
        child = create_draft(actor=self.author, data=self.data, parent_id=broken.pk,
                             expected_parent_hash=broken.payload_sha256, change_reason='اصلاح ساختگی برای آزمون')
        invalid_evidence = self.draft()
        ref = self.add_ref(invalid_evidence)
        ClinicalDraft.objects.filter(pk=broken.pk).update(statement='متن تغییر یافته')
        ClinicalReferenceAssertion.objects.filter(pk=ref.pk).update(reference_title='متن تغییر یافته')
        with patch('socket.create_connection', side_effect=AssertionError('unexpected network')):
            report = inspect_drafts()
        self.assertEqual([r['status'] for r in report['rows']],
                         ['available', 'draft_invalid', 'draft_invalid', 'evidence_invalid'])
        self.assertEqual([r['id'] for r in report['rows']], [healthy.pk, broken.pk, child.pk, invalid_evidence.pk])
        self.assertEqual(set(report['rows'][0]), {'id', 'status'})
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_clinical_inspection'))
        self.assertEqual(response.status_code, 200)
        for secret in [self.data['title'], self.data['statement'], self.data['reference_url'], 'متن تغییر یافته']:
            self.assertNotContains(response, secret)
        self.assertContains(response, 'ارجاع تکمیلی ناسازگار')
        self.assertContains(response, 'ارجاع‌ها بررسی نشدند')
        self.assertEqual(ClinicalDraft.objects.count(), 4)
        self.assertEqual(ClinicalReferenceAssertion.objects.count(), 1)

    def test_over_limit_takes_precedence_without_unbounded_fetch(self):
        draft = self.draft()
        for i in range(10):
            self.add_ref(draft, title=f'ارجاع ساختگی {i}')
        ref = ClinicalReferenceAssertion.objects.filter(draft=draft).first()
        ref.pk = None
        ref.payload_sha256 = 'f' * 64
        ref.save()
        with CaptureQueriesContext(connection) as captured:
            report = inspect_drafts()
        self.assertEqual(report['rows'], [{'id': draft.pk, 'status': 'evidence_over_limit'}])
        self.assertEqual(len(captured), 3)  # drafts, authors, bounded assertions
        self.assertIn('ROW_NUMBER()', captured[2]['sql'].upper())
        self.assertIn('<= 11', captured[2]['sql'])

    def test_paging_filter_and_bounded_queries(self):
        drafts = [self.draft() for _ in range(51)]
        ClinicalDraft.objects.filter(pk=drafts[50].pk).update(statement='تغییر ساختگی')
        with CaptureQueriesContext(connection) as queries:
            first = inspect_drafts(category='draft_invalid')
        self.assertEqual(first['scanned'], 50)
        self.assertEqual(first['rows'], [])
        self.assertEqual(first['next_after'], drafts[49].pk)
        self.assertEqual(len(queries), 3)  # batch, authors, bounded per-draft window query
        self.assertIn('LIMIT 51', queries[0]['sql'].upper())
        next_page = inspect_drafts(after=first['next_after'], category='draft_invalid')
        self.assertEqual(next_page['rows'], [{'id': drafts[50].pk, 'status': 'draft_invalid'}])
        self.assertIsNone(next_page['next_after'])
        self.assertEqual(inspect_drafts(after=drafts[50].pk)['scanned'], 0)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_clinical_inspection'), {'category': 'draft_invalid', 'after': '۰'})
        self.assertContains(response, f'?after={drafts[49].pk}&amp;category=draft_invalid')
        self.assertContains(response, 'در این بخش نتیجه‌ای مطابق فیلتر دیده نشد')

    def test_each_reference_lookup_is_bounded_and_read_only(self):
        for i in range(50):
            draft = self.draft()
            self.add_ref(draft, title=f'ارجاع ساختگی {i}')
        with CaptureQueriesContext(connection) as captured:
            report = inspect_drafts()
        self.assertEqual(report['scanned'], 50)
        self.assertEqual(len(captured), 4)  # batch + authors + assertions + distinct recorders
        self.assertTrue(all(query['sql'].lstrip().upper().startswith('SELECT') for query in captured))
        self.assertIn('ROW_NUMBER()', captured[2]['sql'].upper())
        self.assertIn('PARTITION BY', captured[2]['sql'].upper())
        self.assertIn('<= 11', captured[2]['sql'])
        self.assertTrue(all(row['status'] == 'available' for row in report['rows']))

    def test_batch_matches_individual_statuses_and_missing_recorders(self):
        empty, good, invalid, over = [self.draft() for _ in range(4)]
        self.add_ref(good)
        ref = self.add_ref(invalid)
        ClinicalReferenceAssertion.objects.filter(pk=ref.pk).update(reference_title='ناسازگار')
        for i in range(10):
            self.add_ref(over, title=f'ارجاع ساختگی {i}')
        extra = ClinicalReferenceAssertion.objects.filter(draft=over).first()
        extra.pk = None
        extra.payload_sha256 = 'a' * 64
        extra.save()
        drafts = [empty, good, invalid, over]
        expected = {draft.pk: evidence_state(draft)['status'] for draft in drafts}
        self.assertEqual(expected, {empty.pk: 'available', good.pk: 'available', invalid.pk: 'invalid', over.pk: 'over_limit'})
        self.assertEqual(inspection_evidence_statuses(drafts), expected)
        with patch('clinical.evidence.get_user_model') as model:
            model.return_value.objects.in_bulk.return_value = {}
            self.assertEqual(inspection_evidence_statuses(drafts),
                             {empty.pk: 'available', good.pk: 'invalid', invalid.pk: 'invalid', over.pk: 'over_limit'})
            self.assertEqual(evidence_state(good)['status'], 'invalid')

    def test_only_drafts_with_a_missing_recorder_are_invalid(self):
        first, second, empty = [self.draft() for _ in range(3)]
        self.add_ref(first)
        ref = self.add_ref(second)
        ClinicalReferenceAssertion.objects.filter(pk=ref.pk).update(recorded_by=self.viewer)
        with patch('clinical.evidence.get_user_model') as model:
            model.return_value.objects.in_bulk.return_value = {self.author.pk: self.author}
            statuses = inspection_evidence_statuses([first, second, empty])
            self.assertEqual(statuses, {first.pk: 'available', second.pk: 'invalid', empty.pk: 'available'})
            self.assertEqual(statuses, {d.pk: evidence_state(d)['status'] for d in [first, second, empty]})

    def test_invalid_drafts_skip_reference_queries(self):
        draft = self.draft()
        self.add_ref(draft)
        ClinicalDraft.objects.filter(pk=draft.pk).update(statement='ناسازگار')
        with self.assertNumQueries(1):
            report = inspect_drafts()
        self.assertEqual(report['rows'], [{'id': draft.pk, 'status': 'draft_invalid'}])

    def test_reused_instances_refetch_assertions(self):
        draft = self.draft()
        self.assertEqual(inspection_evidence_statuses([draft])[draft.pk], 'available')
        ref = self.add_ref(draft)
        ClinicalReferenceAssertion.objects.filter(pk=ref.pk).update(reference_title='تغییر ناسازگار')
        with self.assertNumQueries(1):
            result = inspection_evidence_statuses([draft])
        self.assertEqual(result[draft.pk], 'invalid')
        self.assertEqual(result[draft.pk], evidence_state(draft)['status'])

    def test_batch_rejects_duplicate_unsaved_or_oversized_inputs(self):
        draft = self.draft()
        for value in ([draft, draft], [ClinicalDraft()], [ClinicalDraft(pk=123)], [draft] * 51):
            with self.subTest(size=len(value)), self.assertRaises(ValueError):
                inspection_evidence_statuses(value)
        with self.assertNumQueries(0):
            self.assertEqual(inspection_evidence_statuses([]), {})

    def test_per_draft_window_excludes_lookahead_and_caps_each_partition(self):
        drafts = [self.draft() for _ in range(51)]
        for draft in (drafts[0], drafts[49], drafts[50]):
            for i in range(10):
                self.add_ref(draft, title=f'ارجاع ساختگی {i}')
            for i in range(5):
                ref = ClinicalReferenceAssertion.objects.filter(draft=draft).first()
                ref.pk = None
                ref.payload_sha256 = f'{i:064x}'
                ref.save()
        loaded = list(ClinicalDraft.objects.filter(pk__in=[drafts[0].pk, drafts[49].pk]))
        statuses = inspection_evidence_statuses(loaded)
        self.assertEqual(set(statuses.values()), {'over_limit'})
        self.assertEqual([len(d._inspection_references) for d in loaded], [11, 11])
        with CaptureQueriesContext(connection) as captured:
            report = inspect_drafts()
        self.assertEqual(len(captured), 3)
        sql = captured[2]['sql']
        self.assertNotIn(f', {drafts[50].pk}', sql)  # lookahead does not enter the evidence query
        self.assertEqual(report['rows'][0]['status'], 'evidence_over_limit')
        self.assertEqual(report['rows'][49]['status'], 'evidence_over_limit')
        self.assertEqual(inspect_drafts(after=report['next_after'])['rows'][0]['status'], 'evidence_over_limit')

    def test_full_batch_at_reference_limit_is_bounded_and_equivalent(self):
        drafts = [self.draft() for _ in range(50)]
        refs = []
        for draft in drafts:
            for i in range(10):
                data = {k: self.data[k] for k in ('reference_title', 'reference_url', 'reference_location',
                        'reference_author', 'reference_version', 'reference_published_on', 'reference_accessed_on')}
                data.update(reference_title=f'ارجاع ساختگی {i}', relation='context')
                refs.append(ClinicalReferenceAssertion(draft=draft, recorded_by=self.author,
                            draft_payload_sha256=draft.payload_sha256,
                            payload_sha256=reference_fingerprint(data, draft.pk, draft.payload_sha256), **data))
        ClinicalReferenceAssertion.objects.bulk_create(refs)
        with self.assertNumQueries(2):  # assertions and one bulk recorder lookup
            statuses = inspection_evidence_statuses(drafts)
        self.assertTrue(all(value == 'available' for value in statuses.values()))
        self.assertEqual(sum(len(d._inspection_references) for d in drafts), 500)
        self.assertEqual(statuses, {d.pk: evidence_state(d)['status'] for d in drafts})
        # Corrupt data can exceed the service cap; retrieval stays bounded per draft.
        extra = []
        for draft in drafts:
            for i in range(5):
                data = {k: self.data[k] for k in ('reference_title', 'reference_url', 'reference_location',
                        'reference_author', 'reference_version', 'reference_published_on', 'reference_accessed_on')}
                data.update(reference_title=f'ارجاع اضافه ساختگی {i}', relation='context')
                extra.append(ClinicalReferenceAssertion(draft=draft, recorded_by=self.author,
                             draft_payload_sha256=draft.payload_sha256,
                             payload_sha256=reference_fingerprint(data, draft.pk, draft.payload_sha256), **data))
        ClinicalReferenceAssertion.objects.bulk_create(extra)
        with self.assertNumQueries(1):
            statuses = inspection_evidence_statuses(drafts)
        self.assertTrue(all(value == 'over_limit' for value in statuses.values()))
        self.assertEqual(sum(len(d._inspection_references) for d in drafts), 550)
        self.assertEqual(statuses, {d.pk: evidence_state(d)['status'] for d in drafts})

    def test_changes_between_calls_are_not_a_snapshot(self):
        drafts = [self.draft() for _ in range(51)]
        first = inspect_drafts()
        ClinicalDraft.objects.filter(pk=drafts[-1].pk).update(statement='داده تغییر یافته')
        second = inspect_drafts(after=first['next_after'])
        self.assertEqual(second['rows'], [{'id': drafts[-1].pk, 'status': 'draft_invalid'}])
        self.assertIsNone(second['next_after'])

    def test_invalid_inputs_fail_closed(self):
        for value in [-1, True, 2**63, '0', None]:
            with self.subTest(value=value), self.assertRaises(InvalidInspection):
                inspect_drafts(after=value)
        for value in [None, [], 'other']:
            with self.subTest(value=value), self.assertRaises(InvalidInspection):
                inspect_drafts(category=value)
        self.client.force_login(self.viewer)
        url = reverse('staff_clinical_inspection')
        for params in [{'after': '-1'}, {'after': '9223372036854775808'}, {'after': '1' * 100},
                       {'category': 'private-canary'}]:
            response = self.client.get(url, params)
            self.assertEqual(response.status_code, 400)
            self.assertNotContains(response, 'private-canary', status_code=400)
            self.assertContains(response, f'href="{url}"', status_code=400)
            self.private(response)
        self.assertEqual(self.client.get(url, {'after': '۰۰٠0'}).status_code, 200)

    def private(self, response):
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('private', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_permissions_methods_privacy_and_navigation(self):
        url = reverse('staff_clinical_inspection')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.private(response)
        for user in [self.no_view, self.regular]:
            self.client.force_login(user)
            response = self.client.get(url, {'after': 'invalid'})
            self.assertEqual(response.status_code, 403)
            self.private(response)
        self.client.force_login(self.viewer)
        self.assertContains(self.client.get(reverse('staff_clinical_drafts')), f'href="{url}"')
        for method, expected in [('get', 200), ('head', 200), ('post', 405)]:
            response = getattr(self.client, method)(url)
            self.assertEqual(response.status_code, expected)
            self.private(response)
        self.assertNotContains(self.client.get(reverse('sitemap')), url)

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_disabled_portal(self):
        self.client.force_login(self.viewer)
        for method in [self.client.get, self.client.post]:
            response = method(reverse('staff_clinical_inspection'))
            self.assertEqual(response.status_code, 404)
            self.private(response)
