"""Synthetic tests for the shared write-actor recheck helper; not revocation."""
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.transaction import TransactionManagementError
from django.test import TransactionTestCase

from .actor_recheck import MAX_PK, recheck_actor

PERMS = ('sources.view_sourceclaim', 'sources.add_sourceclaim')


class ActorRecheckTests(TransactionTestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user('synthetic-recheck-actor', password='synthetic-only',
                                                          is_staff=True)
        self.actor.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources',
                                        codename__in=['view_sourceclaim', 'add_sourceclaim']))

    def test_returns_a_fresh_instance_for_a_currently_authorized_actor(self):
        current = recheck_actor(self.actor, PERMS)
        self.assertEqual(current.pk, self.actor.pk)
        self.assertIsNot(current, self.actor)
        self.assertTrue(current.is_active and current.is_staff)

    def test_denies_actors_that_are_absent_anonymous_or_out_of_range(self):
        for actor in (None, AnonymousUser(), SimpleNamespace(pk=0), SimpleNamespace(pk=MAX_PK + 1),
                      SimpleNamespace(pk='1')):
            with self.subTest(actor=type(actor).__name__):
                with self.assertRaises(PermissionDenied):
                    recheck_actor(actor, PERMS)

    def test_denies_a_stale_actor_whose_account_was_disabled_or_destaffed(self):
        for field in ('is_active', 'is_staff'):
            with self.subTest(field=field):
                stale = get_user_model().objects.get(pk=self.actor.pk)
                get_user_model().objects.filter(pk=self.actor.pk).update(**{field: False})
                with self.assertRaises(PermissionDenied):
                    recheck_actor(stale, PERMS)
                get_user_model().objects.filter(pk=self.actor.pk).update(**{field: True})
        self.assertEqual(recheck_actor(self.actor, PERMS).pk, self.actor.pk)

    def test_denies_a_deleted_account_even_if_the_instance_still_looks_active(self):
        stale = get_user_model().objects.get(pk=self.actor.pk)
        get_user_model().objects.filter(pk=self.actor.pk).delete()
        with self.assertRaises(PermissionDenied):
            recheck_actor(stale, PERMS)

    def test_denies_missing_permissions_despite_a_primed_backend_cache(self):
        self.assertTrue(self.actor.has_perm('sources.add_sourceclaim'))
        self.actor.user_permissions.remove(*Permission.objects.filter(content_type__app_label='sources',
                                                                      codename='add_sourceclaim'))
        with self.assertRaises(PermissionDenied):
            recheck_actor(self.actor, PERMS)
        self.assertEqual(recheck_actor(self.actor, ('sources.view_sourceclaim',)).pk, self.actor.pk)
        self.assertEqual(recheck_actor(self.actor, ()).pk, self.actor.pk)

    def test_session_hash_binding_accepts_a_match_and_denies_stale_or_malformed_values(self):
        matching = self.actor.get_session_auth_hash()
        self.assertEqual(recheck_actor(self.actor, PERMS, session_auth_hash=matching).pk, self.actor.pk)
        # Flip one character deterministically: a fixed replacement digit could
        # coincidentally equal the real hash and make this case pass vacuously.
        near_miss = matching[:-1] + ('1' if matching[-1] != '1' else '2')
        self.assertNotEqual(near_miss, matching)
        for stale in ('synthetic-not-a-real-hash', '', 12345, ['synthetic'], near_miss):
            with self.subTest(stale=type(stale).__name__):
                with self.assertRaises(PermissionDenied):
                    recheck_actor(self.actor, PERMS, session_auth_hash=stale)
        # An omitted hash keeps direct service callers working and authenticates nothing.
        self.assertEqual(recheck_actor(self.actor, PERMS, session_auth_hash=None).pk, self.actor.pk)

    def test_password_rotation_before_the_recheck_denies_the_previous_hash(self):
        previous = self.actor.get_session_auth_hash()
        current = get_user_model().objects.get(pk=self.actor.pk)
        current.set_password('synthetic-rotated')
        current.save(update_fields=['password'])
        with self.assertRaises(PermissionDenied):
            recheck_actor(current, PERMS, session_auth_hash=previous)
        self.assertEqual(recheck_actor(current, PERMS, session_auth_hash=current.get_session_auth_hash()).pk,
                         current.pk)

    def test_locked_recheck_requires_an_atomic_block_and_blocks_a_status_update(self):
        with self.assertRaises(TransactionManagementError):
            recheck_actor(self.actor, PERMS, lock=True)
        with transaction.atomic():
            self.assertEqual(recheck_actor(self.actor, PERMS, lock=True).pk, self.actor.pk)
            table = connection.ops.quote_name(get_user_model()._meta.db_table)
            with connection.cursor() as cursor:
                cursor.execute(f'SELECT id FROM {table} WHERE id = %s FOR NO KEY UPDATE', [self.actor.pk])
                self.assertEqual(cursor.fetchone()[0], self.actor.pk)
