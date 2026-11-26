"""Narrow synthetic tests for the price staging actor recheck; not revocation."""
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import TransactionTestCase

from ingestion.models import ImportReceipt
from .importer import ImportValidationError, _find_or_create_candidate, stage_csv
from .models import PriceCandidate
from .test_workflow import csv_bytes

SOURCE = 'منبع ساختگی'
URL = 'https://example.org/price-stage'


def price(record_id='one'):
    return dict(source_record_id=record_id, irc='001', manufacturer='سازنده فرضی', strength='5 mg',
                dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
                category='retail', unit='package', effective_date='', source_published_date='')


class PricingStageActorRecheckTests(TransactionTestCase):
    def setUp(self):
        self.stager = get_user_model().objects.create_user('synthetic-price-stage-actor', password='synthetic-only',
                                                           is_staff=True)
        self.stager.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing'))

    def stage(self, actor=None, record_id='one', **kwargs):
        return stage_csv(io.BytesIO(csv_bytes([price(record_id)])), SOURCE, URL, commit=True, rights_attested=True,
                         staged_by=actor or self.stager, **kwargs)

    def test_matching_session_hash_allows_staging_and_omitted_hash_keeps_service_calls(self):
        counts = self.stage(record_id='one', session_auth_hash=self.stager.get_session_auth_hash())
        self.assertEqual(counts['created'], 1)
        PriceCandidate.objects.all().delete()
        ImportReceipt.objects.all().delete()
        self.assertEqual(self.stage(record_id='two')['created'], 1)

    def test_stale_or_malformed_session_hash_is_denied_for_an_active_stager(self):
        for stale in ('synthetic-not-a-real-hash', '', 12345, ['synthetic']):
            with self.subTest(stale=type(stale).__name__):
                with self.assertRaises(PermissionDenied):
                    self.stage(session_auth_hash=stale)
        self.assertFalse(PriceCandidate.objects.exists())

    def test_password_changed_before_staging_denies_the_previous_session_hash(self):
        previous = self.stager.get_session_auth_hash()
        current = get_user_model().objects.get(pk=self.stager.pk)
        current.set_password('synthetic-rotated')
        current.save(update_fields=['password'])
        with self.assertRaises(PermissionDenied):
            self.stage(actor=current, session_auth_hash=previous)
        self.assertFalse(PriceCandidate.objects.exists())
        self.assertEqual(self.stage(actor=current, record_id='three',
                                    session_auth_hash=current.get_session_auth_hash())['created'], 1)

    def test_stager_disabled_or_destaffed_before_staging_is_denied_despite_stale_actor(self):
        for field in ('is_active', 'is_staff'):
            with self.subTest(field=field):
                stale_actor = get_user_model().objects.get(pk=self.stager.pk)
                get_user_model().objects.filter(pk=self.stager.pk).update(**{field: False})
                with self.assertRaises(PermissionDenied):
                    self.stage(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash())
                self.assertFalse(PriceCandidate.objects.exists())
                get_user_model().objects.filter(pk=self.stager.pk).update(**{field: True})

    def test_stage_permission_removed_before_staging_is_denied_despite_stale_cache(self):
        stale_actor = get_user_model().objects.get(pk=self.stager.pk)
        self.assertTrue(stale_actor.has_perm('pricing.add_pricecandidate'))  # prime backend cache
        # Remove through a second instance so the request actor keeps its stale cache.
        other = get_user_model().objects.get(pk=self.stager.pk)
        other.user_permissions.remove(*Permission.objects.filter(content_type__app_label='pricing',
                                                                 codename='add_pricecandidate'))
        with self.assertRaises(PermissionDenied):
            self.stage(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash())
        self.assertFalse(PriceCandidate.objects.exists())

    def test_deleted_stager_is_denied_even_if_the_instance_still_looks_active(self):
        stale_actor = get_user_model().objects.get(pk=self.stager.pk)
        unprimed_actor = get_user_model().objects.get(pk=self.stager.pk)
        # A request actor that already cached its permissions passes the service's
        # own pre-check, so only the fresh recheck inside the transaction denies it.
        self.assertTrue(stale_actor.has_perm('pricing.add_pricecandidate'))
        get_user_model().objects.filter(pk=self.stager.pk).delete()
        with self.assertRaises(PermissionDenied):
            self.stage(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash())
        # An actor without a primed cache is rejected earlier, by the pre-check.
        with self.assertRaises(ImportValidationError):
            self.stage(actor=unprimed_actor, session_auth_hash=unprimed_actor.get_session_auth_hash())
        self.assertFalse(PriceCandidate.objects.exists())

    def test_receipt_wrapper_forwards_the_session_hash_and_denies_a_stale_one(self):
        from ingestion.receipts import stage_price_with_receipt
        with self.assertRaises(PermissionDenied):
            stage_price_with_receipt(io.BytesIO(csv_bytes([price()])), SOURCE, URL, actor=self.stager,
                                     rights_attested=True, session_auth_hash='synthetic-not-a-real-hash')
        self.assertFalse(PriceCandidate.objects.exists())
        self.assertFalse(ImportReceipt.objects.exists())
        counts, receipt = stage_price_with_receipt(io.BytesIO(csv_bytes([price()])), SOURCE, URL, actor=self.stager,
                                                   rights_attested=True,
                                                   session_auth_hash=self.stager.get_session_auth_hash())
        self.assertEqual(counts['created'], 1)
        self.assertEqual(receipt.actor_id, self.stager.pk)

    def test_password_changed_after_the_stager_recheck_can_still_race_the_upload(self):
        # A remaining gap: the recheck is an unlocked point-in-time read, so a
        # credential change committed afterwards is not detected by this service.
        stale_actor = get_user_model().objects.get(pk=self.stager.pk)
        session_hash = stale_actor.get_session_auth_hash()
        ready, resume = Event(), Event()

        def pause(*args, **kwargs):
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic price staging writer did not resume')
            return _find_or_create_candidate(*args, **kwargs)

        def writer():
            close_old_connections()
            try:
                return self.stage(actor=stale_actor, session_auth_hash=session_hash)
            finally:
                close_old_connections()

        with patch('pricing.importer._find_or_create_candidate', side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(writer)
                try:
                    self.assertTrue(ready.wait(10), 'Price staging writer did not reach candidate insertion')
                    current = get_user_model().objects.get(pk=self.stager.pk)
                    current.is_active = False
                    current.set_unusable_password()
                    current.save(update_fields=['is_active', 'password'])
                    get_user_model().objects.filter(pk=self.stager.pk).update(is_active=True)
                finally:
                    resume.set()
                counts = future.result(timeout=20)
        self.assertEqual(counts['created'], 1)
        self.assertEqual(PriceCandidate.objects.count(), 1)
        self.assertFalse(get_user_model().objects.get(pk=self.stager.pk).has_usable_password())
