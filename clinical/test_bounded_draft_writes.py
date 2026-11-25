"""Selected bounded clinical writer reads, with synthetic PostgreSQL data."""
from unittest.mock import patch

from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from . import test_lineage as fixtures
from .evidence import add_reference, evidence_state
from .legacy_reason_test_utils import set_legacy_reason
from .models import ClinicalDraft, ClinicalDraftReview, ClinicalReferenceAssertion
from .services import DraftConflict, create_draft, valid_draft


class BoundedClinicalWritesTests(TestCase):
    chain = fixtures.ClinicalLineageTests.chain

    @classmethod
    def setUpTestData(cls):
        fixtures.ClinicalLineageTests.setUpTestData.__func__(cls)
        from django.contrib.auth.models import Permission
        cls.viewer.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical',
            codename__in=['add_clinicaldraft', 'review_clinicaldraft']))
        cls.reference = dict(reference_title='ارجاع ساختگی', reference_url='https://example.org/ref',
            reference_location='مکان ساختگی', reference_author='', reference_version='',
            reference_published_on=None, reference_accessed_on=None, relation='supports')

    def run_writer(self, kind, draft, actor=None):
        from .services import review_draft
        actor = actor or self.viewer
        if kind == 'revise':
            return create_draft(actor=actor, data=self.data, parent_id=draft.pk,
                expected_parent_hash=draft.payload_sha256, change_reason=self.reason)
        if kind == 'reference':
            return add_reference(actor=actor, draft_id=draft.pk, data=self.reference,
                expected_draft_hash=draft.payload_sha256, expected_evidence_hash=evidence_state(draft)['fingerprint'])
        return review_draft(actor=actor, draft_id=draft.pk, decision='defer', reason=self.reason,
            expected_review=0, expected_hash=draft.payload_sha256,
            expected_evidence_hash=evidence_state(draft)['fingerprint'])

    def assert_locked_bounded(self, queries, locks):
        sqls = [q['sql'] for q in queries if q['sql'].startswith('SELECT') and
                'FROM "clinical_clinicaldraft"' in q['sql']]
        self.assertEqual(len(sqls), locks)
        for sql in sqls:
            selection = sql.rsplit(' FROM "clinical_clinicaldraft"', 1)[0].lower()
            self.assertIn('FOR UPDATE', sql)
            self.assertGreaterEqual(selection.count('substring'), 2)
            self.assertNotRegex(selection, r'(?:^select |, )"clinical_clinicaldraft"\."(?:statement|change_reason)"(?:,|$)')
            self.assertNotIn(' JOIN ', sql.upper())

    def test_child_and_parent_oversized_conflict_without_partial_validation(self):
        _, parent, child = self.chain(2)
        for kind in ('revise', 'reference', 'review'):
            for target, field in ((child, 'statement'), (child, 'change_reason'),
                                  (parent, 'statement'), (parent, 'change_reason')):
                with self.subTest(kind=kind, target=target.pk, field=field):
                    old = getattr(target, field)
                    ClinicalDraft.objects.filter(pk=target.pk).update(**{field: 'ر' * 100_000 + 'canary'})
                    try:
                        self.viewer.has_perm('clinical.review_clinicaldraft')
                        before = (ClinicalDraft.objects.count(), ClinicalDraftReview.objects.count(), ClinicalReferenceAssertion.objects.count())
                        from .services import validate_data
                        def assert_complete(data):
                            self.assertIsNotNone(data['statement'])
                            self.assertLessEqual(len(data['statement']), 4000)
                            return validate_data(data)
                        from .services import valid_review_reason
                        def assert_reason_complete(reason):
                            self.assertLessEqual(len(reason), 1000)
                            return valid_review_reason(reason)
                        with patch('clinical.services.validate_data', side_effect=assert_complete), \
                             patch('clinical.services.valid_review_reason', side_effect=assert_reason_complete):
                            with CaptureQueriesContext(connection) as queries:
                                with self.assertRaises(DraftConflict) as caught:
                                    self.run_writer(kind, child)
                        self.assertIn('سازگاری بررسی نشد', str(caught.exception))
                        self.assert_locked_bounded(queries, 1 if target == child else 2)
                        self.assertEqual(before, (ClinicalDraft.objects.count(), ClinicalDraftReview.objects.count(), ClinicalReferenceAssertion.objects.count()))
                    finally:
                        ClinicalDraft.objects.filter(pk=target.pk).update(**{field: old})

    def test_valid_long_whitespace_reason_is_still_refused_without_writes(self):
        root = self.chain(0)[0]
        child = create_draft(actor=self.author, data=self.data, parent_id=root.pk,
            expected_parent_hash=root.payload_sha256, change_reason=self.reason + ' ' * 100_000)
        set_legacy_reason(child, self.reason + ' ' * 100_000)
        self.assertTrue(valid_draft(ClinicalDraft.objects.select_related('parent').get(pk=child.pk)))
        for kind in ('revise', 'reference', 'review'):
            with self.subTest(kind=kind), self.assertRaises(DraftConflict):
                self.run_writer(kind, child)
        self.assertEqual(ClinicalDraft.objects.count(), 2)
        self.assertFalse(ClinicalReferenceAssertion.objects.exists())
        self.assertFalse(ClinicalDraftReview.objects.exists())

    def test_exact_complete_thresholds_allow_existing_writers(self):
        for kind in ('revise', 'reference', 'review'):
            with self.subTest(kind=kind):
                root = create_draft(actor=self.author, data={**self.data, 'statement': 'ر' * 4000})
                child = create_draft(actor=self.author, data=self.data, parent_id=root.pk,
                                     expected_parent_hash=root.payload_sha256, change_reason='ر' * 1000)
                with CaptureQueriesContext(connection) as queries:
                    result = self.run_writer(kind, child)
                self.assertIsNotNone(result)
                self.assert_locked_bounded(queries, 2)

    def test_http_writers_conflict_if_current_changes_after_form_precheck(self):
        from django.test import override_settings
        from django.urls import reverse
        from .services import review_draft
        parent, child = self.chain(1)
        state = evidence_state(child)['fingerprint']
        draft_form = {**{k: v if v is not None else '' for k, v in self.data.items()},
                      'synthetic_ack': 'on', 'expected_parent_hash': child.payload_sha256,
                      'change_reason': self.reason}
        reference_form = {**{k: v if v is not None else '' for k, v in self.reference.items()},
                          'synthetic_ack': 'on', 'expected_draft_hash': child.payload_sha256,
                          'expected_evidence_hash': state}
        cases = [
            ('staff_clinical_revise', draft_form, 'clinical.staff_views.create_draft', create_draft),
            ('staff_clinical_reference_create', reference_form, 'clinical.staff_views.add_reference', add_reference),
            ('staff_clinical_review', {'decision': 'defer', 'reason': self.reason, 'expected_review': 0,
                'expected_hash': child.payload_sha256, 'expected_evidence_hash': state},
                'clinical.staff_views.review_draft', review_draft),
        ]
        self.client.force_login(self.viewer)
        for route, data, target, service in cases:
            with self.subTest(route=route), override_settings(STAFF_PORTAL_ENABLED=True):
                def mutate_before_lock(**kwargs):
                    ClinicalDraft.objects.filter(pk=child.pk).update(statement='آ' * 100_000 + 'http-writer-canary')
                    return service(**kwargs)
                try:
                    with patch(target, side_effect=mutate_before_lock):
                        response = self.client.post(reverse(route, args=[child.pk]), data)
                    self.assertEqual(response.status_code, 409)
                    self.assertContains(response, 'سازگاری بررسی نشد', status_code=409)
                    self.assertNotContains(response, 'http-writer-canary', status_code=409)
                    self.assertIn('no-store', response['Cache-Control'])
                    self.assertEqual(ClinicalDraft.objects.count(), 2)
                    self.assertFalse(ClinicalReferenceAssertion.objects.exists())
                    self.assertFalse(ClinicalDraftReview.objects.exists())
                finally:
                    ClinicalDraft.objects.filter(pk=child.pk).update(statement=self.data['statement'])

    def test_self_review_denial_takes_precedence_over_oversized(self):
        child = self.chain(1)[-1]
        from django.contrib.auth.models import Permission
        self.author.user_permissions.add(Permission.objects.get(content_type__app_label='clinical', codename='review_clinicaldraft'))
        ClinicalDraft.objects.filter(pk=child.pk).update(statement='آ' * 100_000)
        with self.assertRaises(PermissionDenied):
            self.run_writer('review', child, actor=self.author)


from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from django.db import connection, transaction
from django.test import TransactionTestCase
from . import test_parent_locking as locking_fixtures


class BoundedClinicalWriterRaces(TransactionTestCase):
    setUp = locking_fixtures.ClinicalParentLockingTests.setUp
    chain = locking_fixtures.ClinicalParentLockingTests.chain
    operation = locking_fixtures.ClinicalParentLockingTests.operation
    worker = locking_fixtures.ClinicalParentLockingTests.worker
    wait_until_blocked = locking_fixtures.ClinicalParentLockingTests.wait_until_blocked

    def test_waiting_writers_see_committed_oversized_current_or_parent(self):
        for kind in ('review', 'add', 'revise'):
            for target_name in ('child', 'parent'):
                with self.subTest(kind=kind, target=target_name):
                    parent, child = self.chain()
                    target = child if target_name == 'child' else parent
                    before = (ClinicalDraft.objects.count(), ClinicalDraftReview.objects.count(),
                              ClinicalReferenceAssertion.objects.count())
                    pids = Queue()
                    def perform():
                        with connection.cursor() as cursor:
                            cursor.execute('SELECT pg_backend_pid()')
                            pid = cursor.fetchone()[0]
                        notified = False
                        def observe(execute, sql, params, many, context):
                            nonlocal notified
                            # Signal immediately before the writer attempts the
                            # target row lock, not before unrelated account,
                            # permission or evidence reads have completed.
                            if (not notified and 'FROM "clinical_clinicaldraft"' in sql
                                    and 'FOR UPDATE' in sql and params and params[-1] == target.pk):
                                notified = True
                                pids.put(pid)
                            return execute(sql, params, many, context)
                        with connection.execute_wrapper(observe):
                            return self.operation(kind, child)
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with transaction.atomic():
                            ClinicalDraft.objects.filter(pk=target.pk).update(statement='آ' * 100_000)
                            future = pool.submit(self.worker, perform)
                            pid = pids.get(timeout=12)
                            self.assertTrue(self.wait_until_blocked(pid, future),
                                            f'{kind} did not wait for the {target_name} row')
                        with self.assertRaises(DraftConflict):
                            future.result(timeout=10)
                    self.assertEqual(before, (ClinicalDraft.objects.count(), ClinicalDraftReview.objects.count(),
                                              ClinicalReferenceAssertion.objects.count()))
