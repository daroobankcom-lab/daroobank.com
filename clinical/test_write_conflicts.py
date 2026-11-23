"""Selected conflict behavior of synthetic clinical draft and reference writes."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TransactionTestCase, override_settings
from django.urls import reverse

from .evidence import add_reference, evidence_state
from .models import ClinicalDraft, ClinicalReferenceAssertion
from .services import DraftConflict, create_draft


class DriverFailure(Exception):
    def __init__(self, code):
        self.sqlstate = code


def fail_with(code):
    try:
        raise DriverFailure(code)
    except DriverFailure as exc:
        raise OperationalError('private synthetic driver detail') from exc


@override_settings(STAFF_PORTAL_ENABLED=True)
class ClinicalWriteConflictTests(TransactionTestCase):
    def setUp(self):
        self.author = get_user_model().objects.create_user('clinical-conflict-author', is_staff=True)
        self.author.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical',
                                         codename__in=['view_clinicaldraft', 'add_clinicaldraft']))
        self.data = dict(subject='موضوع فرضی', audience='patient', title='عنوان ساختگی',
            statement='این گزاره فقط برای آزمون ساختگی است.', reference_title='مرجع ساختگی',
            reference_url='https://example.org/ref', reference_location='محل ساختگی', reference_author='',
            reference_version='', reference_published_on=None, reference_accessed_on=None)
        self.reference = dict(reference_title='مرجع تکمیلی ساختگی', reference_url='https://example.org/extra',
            reference_location='محل ساختگی', reference_author='', reference_version='',
            reference_published_on=None, reference_accessed_on=None, relation='supports')
        self.parent = create_draft(actor=self.author, data=self.data)
        self.hash = evidence_state(self.parent)['fingerprint']

    def perform(self, kind):
        actor = get_user_model().objects.get(pk=self.author.pk)
        if kind == 'revise':
            return create_draft(actor=actor, data=self.data, parent_id=self.parent.pk,
                expected_parent_hash=self.parent.payload_sha256, change_reason='دلیل ساختگی برای اصلاح')
        return add_reference(actor=actor, draft_id=self.parent.pk, data=self.reference,
            expected_draft_hash=self.parent.payload_sha256, expected_evidence_hash=self.hash)

    def worker(self, kind):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '300ms'")
                cursor.execute("SET statement_timeout = '8s'")
            return self.perform(kind)
        finally:
            connection.close()

    def test_real_parent_lock_timeout_is_translated_for_revision_and_reference(self):
        for kind in ('revise', 'reference'):
            with self.subTest(kind=kind):
                with transaction.atomic(), ThreadPoolExecutor(max_workers=1) as pool:
                    ClinicalDraft.objects.select_for_update().get(pk=self.parent.pk)
                    with self.assertRaises(DraftConflict) as caught:
                        pool.submit(self.worker, kind).result(timeout=10)
                    driver = caught.exception.__cause__.__cause__
                    self.assertEqual(getattr(driver, 'sqlstate', None) or getattr(driver, 'pgcode', None), '55P03')
                self.assertEqual(ClinicalDraft.objects.count(), 1)
                self.assertFalse(ClinicalReferenceAssertion.objects.exists())
        self.assertTrue(self.perform('revise').pk)
        self.assertTrue(self.perform('reference')[1])

    def test_http_translates_selected_states_after_rollback_without_driver_detail(self):
        self.client.force_login(self.author)
        draft_form = {**{key: value if value is not None else '' for key, value in self.data.items()}, 'synthetic_ack': 'on'}
        reference_form = {**{key: value if value is not None else '' for key, value in self.reference.items()},
                          'synthetic_ack': 'on', 'expected_draft_hash': self.parent.payload_sha256,
                          'expected_evidence_hash': self.hash}
        cases = [
            ('staff_clinical_create', [], draft_form, 'clinical.services.ClinicalDraft.objects.create'),
            ('staff_clinical_revise', [self.parent.pk], {**draft_form, 'expected_parent_hash': self.parent.payload_sha256,
                'change_reason': 'دلیل ساختگی برای اصلاح'}, 'clinical.services.ClinicalDraft.objects.create'),
            ('staff_clinical_reference_create', [self.parent.pk], reference_form,
                'clinical.evidence.ClinicalReferenceAssertion.objects.create'),
        ]
        for route, args, data, target in cases:
            for code in ('55P03', '40P01', '40001'):
                with self.subTest(route=route, code=code):
                    def mutate_and_fail(**kwargs):
                        ClinicalDraft.objects.filter(pk=self.parent.pk).update(title='تغییر موقت ساختگی')
                        fail_with(code)
                    with patch(target, side_effect=mutate_and_fail):
                        response = self.client.post(reverse(route, args=args), data)
                    self.assertEqual(response.status_code, 409)
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                    self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                    self.assertContains(response, 'ثبت به دلیل تداخل هم‌زمان انجام نشد', status_code=409)
                    self.assertNotContains(response, 'private synthetic driver detail', status_code=409)
                    self.parent.refresh_from_db()
                    self.assertEqual(self.parent.title, self.data['title'])
                    self.assertEqual(ClinicalDraft.objects.count(), 1)
                    self.assertFalse(ClinicalReferenceAssertion.objects.exists())

    def test_unselected_database_error_is_not_hidden(self):
        with patch('clinical.services.ClinicalDraft.objects.create', side_effect=lambda **kw: fail_with('23505')):
            with self.assertRaises(OperationalError):
                create_draft(actor=self.author, data=self.data)
        self.assertEqual(ClinicalDraft.objects.count(), 1)
