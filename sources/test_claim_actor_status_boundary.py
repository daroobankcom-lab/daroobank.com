"""Narrow PostgreSQL source-claim account status serialization tests."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import OperationalError, close_old_connections, connection, transaction
from django.test import TransactionTestCase

from .models import SourceClaim
from .services import _find_or_create_claim, record_claim

DATA = {'source_name': 'Synthetic source', 'source_url': 'https://example.org/source',
        'owner': 'Synthetic owner', 'evidence_url': 'https://example.org/evidence', 'evidence_note': '',
        'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
        'starts_on': None, 'expires_on': None}


class ClaimActorStatusBoundaryTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user('synthetic-claim-actor', is_staff=True, is_superuser=True)

    def test_stale_actor_disabled_or_no_longer_staff_cannot_record(self):
        for field in ('is_active', 'is_staff'):
            with self.subTest(field=field):
                get_user_model().objects.filter(pk=self.actor.pk).update(**{field: False})
                with self.assertRaises(PermissionDenied):
                    record_claim(actor=self.actor, data=DATA)
                self.assertFalse(SourceClaim.objects.exists())
                get_user_model().objects.filter(pk=self.actor.pk).update(**{field: True})
        claim, created = record_claim(actor=self.actor, data=DATA)
        self.assertTrue(created)
        self.assertEqual(claim.recorded_by_id, self.actor.pk)

    def test_deleted_actor_is_denied_even_if_instance_still_looks_active(self):
        get_user_model().objects.filter(pk=self.actor.pk).delete()
        with self.assertRaises(PermissionDenied):
            record_claim(actor=self.actor, data=DATA)
        self.assertFalse(SourceClaim.objects.exists())

    def test_cached_permissions_can_outlive_a_permission_removal(self):
        # Documents a separate unresolved boundary, not desired authorization.
        user = get_user_model().objects.create_user('synthetic-permission-cache', is_staff=True)
        permissions = Permission.objects.filter(content_type__app_label='sources',
                                                 codename__in=['view_sourceclaim', 'add_sourceclaim'])
        user.user_permissions.add(*permissions)
        self.assertTrue(user.has_perm('sources.add_sourceclaim'))  # prime backend cache
        self.assertTrue(user.has_perm('sources.view_sourceclaim'))
        user.user_permissions.remove(*permissions)
        self.assertFalse(get_user_model().objects.get(pk=user.pk).has_perm('sources.add_sourceclaim'))
        claim, created = record_claim(actor=user, data=DATA)
        self.assertTrue(created)
        self.assertEqual(claim.recorded_by_id, user.pk)

    def test_account_update_waits_for_writer_but_key_share_remains_available(self):
        ready, resume = Event(), Event()
        def pause(*args, **kwargs):
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic writer did not resume')
            return _find_or_create_claim(*args, **kwargs)

        def writer():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                return record_claim(actor=actor, data=DATA)
            finally:
                close_old_connections()

        with patch('sources.services._find_or_create_claim', side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(writer)
                try:
                    self.assertTrue(ready.wait(10), 'Writer did not reach insertion')
                    # NO KEY UPDATE is compatible with a PostgreSQL foreign-key
                    # key-share lock but conflicts with account status UPDATE.
                    table = connection.ops.quote_name(get_user_model()._meta.db_table)
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL lock_timeout = '500ms'")
                            cursor.execute(f'SELECT id FROM {table} WHERE id = %s FOR KEY SHARE', [self.actor.pk])
                            self.assertEqual(cursor.fetchone()[0], self.actor.pk)
                    with self.assertRaises(OperationalError) as caught:
                        with transaction.atomic():
                            with connection.cursor() as cursor:
                                cursor.execute("SET LOCAL lock_timeout = '500ms'")
                            get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False)
                    driver = caught.exception.__cause__
                    self.assertEqual(getattr(driver, 'sqlstate', None) or getattr(driver, 'pgcode', None), '55P03')
                finally:
                    resume.set()
                claim, created = future.result(timeout=15)
        self.assertTrue(created)
        self.assertEqual(claim.recorded_by_id, self.actor.pk)
        self.assertEqual(get_user_model().objects.filter(pk=self.actor.pk).update(is_active=False), 1)
        self.assertFalse(get_user_model().objects.get(pk=self.actor.pk).is_active)
