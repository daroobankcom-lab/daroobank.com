"""Synthetic source claim write conflicts; no source authorization or automatic retry."""
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .models import SourceClaim
from .services import record_claim

DATA = {'source_name': 'منبع ساختگی', 'source_url': 'https://example.org/synthetic',
        'owner': 'مالک فرضی', 'evidence_url': 'https://example.org/evidence', 'evidence_note': '',
        'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
        'starts_on': None, 'expires_on': None}


def source_actor(name):
    actor = get_user_model().objects.create_user(name, is_staff=True)
    actor.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources',
        codename__in=['view_sourceclaim', 'add_sourceclaim']))
    return actor


class DriverFailure(Exception):
    def __init__(self, code):
        self.sqlstate = code


def fail_with(code):
    try:
        raise DriverFailure(code)
    except DriverFailure as exc:
        raise OperationalError('sensitive synthetic driver detail') from exc


@override_settings(STAFF_PORTAL_ENABLED=True)
class ClaimWriteConflictTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = source_actor('claim-conflict-actor')

    def test_selected_failures_after_create_roll_back_and_preserve_cause(self):
        from .services import ClaimConflict
        create = SourceClaim.objects.get_or_create
        for code in ('55P03', '40P01', '40001'):
            def create_then_fail(*args, **kwargs):
                create(*args, **kwargs)
                fail_with(code)
            with self.subTest(code=code), patch('sources.services.SourceClaim.objects.get_or_create', side_effect=create_then_fail):
                with self.assertRaises(ClaimConflict) as caught:
                    record_claim(actor=self.actor, data=DATA)
                self.assertIsInstance(caught.exception.__cause__, OperationalError)
                self.assertNotIn('sensitive synthetic driver detail', str(caught.exception))
                self.assertFalse(SourceClaim.objects.exists())
                self.assertFalse(transaction.get_connection().needs_rollback)
        claim, created = record_claim(actor=self.actor, data=DATA)
        self.assertTrue(created)
        self.assertEqual(claim.recorded_by_id, self.actor.pk)

    def test_unselected_database_failure_is_not_masked(self):
        with patch('sources.services.SourceClaim.objects.get_or_create', side_effect=lambda *a, **k: fail_with('23505')):
            with self.assertRaises(OperationalError):
                record_claim(actor=self.actor, data=DATA)
        self.assertFalse(SourceClaim.objects.exists())

    def test_http_selected_failure_is_private_and_not_reflected(self):
        self.client.force_login(self.actor)
        payload = {**DATA, 'claims_collection': 'on', 'starts_on': '', 'expires_on': '', 'attestation': 'on'}
        with patch('sources.services.SourceClaim.objects.get_or_create', side_effect=lambda *a, **k: fail_with('40P01')):
            response = self.client.post(reverse('staff_source_create'), payload)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'تداخل هم‌زمان', status_code=409)
        self.assertNotContains(response, 'sensitive synthetic driver detail', status_code=409)
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertFalse(SourceClaim.objects.exists())


@override_settings(STAFF_PORTAL_ENABLED=True)
class ClaimWriteRealLockTests(TransactionTestCase):
    def setUp(self):
        self.actor = source_actor('claim-lock-actor')
        self.other = source_actor('claim-lock-other')

    def worker(self, func):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '300ms'")
                cursor.execute("SET statement_timeout = '8s'")
            return func()
        finally:
            connection.close()

    def test_http_real_unique_insert_timeout_rolls_back_and_returns_private_conflict(self):
        client = Client()
        client.force_login(self.other)
        payload = {**DATA, 'claims_collection': 'on', 'starts_on': '', 'expires_on': '', 'attestation': 'on'}
        with transaction.atomic():
            original, created = record_claim(actor=self.actor, data=DATA)
            self.assertTrue(created)
            with ThreadPoolExecutor(max_workers=1) as executor:
                response = executor.submit(self.worker, lambda: client.post(reverse('staff_source_create'), payload)).result(timeout=10)
            self.assertEqual(response.status_code, 409)
            self.assertContains(response, 'تداخل هم‌زمان', status_code=409)
            self.assertNotContains(response, 'lock timeout', status_code=409)
            self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(SourceClaim.objects.count(), 1)
        self.assertEqual(SourceClaim.objects.get().recorded_by_id, self.actor.pk)
        self.assertEqual(SourceClaim.objects.get().pk, original.pk)

    def test_unique_insert_wait_timeout_is_translated_and_replay_preserves_first_recorder(self):
        from .services import ClaimConflict
        with transaction.atomic():
            original, created = record_claim(actor=self.actor, data=DATA)
            self.assertTrue(created)
            with ThreadPoolExecutor(max_workers=1) as executor:
                with self.assertRaises(ClaimConflict) as caught:
                    executor.submit(self.worker, lambda: record_claim(actor=self.other, data=DATA)).result(timeout=10)
                self.assertIsInstance(caught.exception.__cause__, OperationalError)
                self.assertEqual(caught.exception.__cause__.__cause__.sqlstate, '55P03')
        replay, created = record_claim(actor=self.other, data=DATA)
        self.assertFalse(created)
        self.assertEqual(replay.pk, original.pk)
        self.assertEqual(replay.recorded_by_id, self.actor.pk)
        self.assertEqual(SourceClaim.objects.count(), 1)
