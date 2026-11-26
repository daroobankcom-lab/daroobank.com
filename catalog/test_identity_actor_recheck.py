"""Narrow synthetic tests for the identity write-actor rechecks; not revocation."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import TransactionTestCase

from .identity import (create_formulation, create_ingredient, create_package, create_product, digest,
                       package_snapshot, revise_package, review_package)
from .models import (FormulationDraft, IdentityPackageDraft, IdentityPackageReview, IdentityProductDraft,
                     IngredientDraft)
from .test_identity import FORM, INGREDIENT, PACKAGE, PRODUCT, build, user

ALL = ('view_identityworkspace', 'add_identityworkspace', 'review_identityworkspace')
REASON = 'اصلاح ساختگی برای بررسی نسخه جدید'


class IdentityActorRecheckTests(TransactionTestCase):
    def setUp(self):
        self.author = user('synthetic-identity-author', *ALL)
        self.editor = user('synthetic-identity-editor', 'view_identityworkspace', 'add_identityworkspace')
        self.reviewer = user('synthetic-identity-reviewer', 'view_identityworkspace', 'review_identityworkspace')

    def create_ingredient(self, actor=None, **kwargs):
        return create_ingredient(actor=actor or self.author, data=dict(INGREDIENT), **kwargs)

    def stale_hashes(self):
        return ('synthetic-not-a-real-hash', '', 12345, ['synthetic'])

    def test_matching_session_hash_allows_writes_and_omitted_hash_keeps_service_calls(self):
        ingredient = self.create_ingredient(session_auth_hash=self.author.get_session_auth_hash())
        self.assertEqual(ingredient.recorded_by_id, self.author.pk)
        part = {'ingredient_id': ingredient.pk, 'numerator': Decimal('2.5'), 'numerator_unit': 'mg',
                'denominator': Decimal('1'), 'denominator_unit': 'tablet'}
        form = create_formulation(actor=self.author, data=dict(FORM), components=[part],
                                  session_auth_hash=self.author.get_session_auth_hash())
        product = create_product(actor=self.author, data=dict(PRODUCT), formulation_id=form.pk,
                                 session_auth_hash=self.author.get_session_auth_hash())
        package = create_package(actor=self.author, data=dict(PACKAGE), product_id=product.pk,
                                 session_auth_hash=self.author.get_session_auth_hash())
        self.assertEqual(package.recorded_by_id, self.author.pk)
        # Direct service callers keep the previous behavior when no hash is given.
        self.assertEqual(self.create_ingredient().recorded_by_id, self.author.pk)

    def test_stale_or_malformed_session_hash_is_denied_for_each_identity_write(self):
        ingredient = self.create_ingredient()
        part = {'ingredient_id': ingredient.pk, 'numerator': Decimal('2.5'), 'numerator_unit': 'mg',
                'denominator': Decimal('1'), 'denominator_unit': 'tablet'}
        form = create_formulation(actor=self.author, data=dict(FORM), components=[part])
        product = create_product(actor=self.author, data=dict(PRODUCT), formulation_id=form.pk)
        package = create_package(actor=self.author, data=dict(PACKAGE), product_id=product.pk)
        # Do not delete: formulation components protect their ingredient rows.
        # Compare counts instead, so a denied write cannot hide behind a cascade.
        before = {model: model.objects.count() for model in (IngredientDraft, FormulationDraft, IdentityProductDraft,
                                                             IdentityPackageDraft, IdentityPackageReview)}
        calls = [
            lambda stale: create_ingredient(actor=self.author, data=dict(INGREDIENT), session_auth_hash=stale),
            lambda stale: create_formulation(actor=self.author, data=dict(FORM), components=[part],
                                             session_auth_hash=stale),
            lambda stale: create_product(actor=self.author, data=dict(PRODUCT), formulation_id=form.pk,
                                         session_auth_hash=stale),
            lambda stale: create_package(actor=self.author, data=dict(PACKAGE), product_id=product.pk,
                                         session_auth_hash=stale),
            lambda stale: revise_package(actor=self.editor, parent_id=package.pk,
                                         data={**PACKAGE, 'quantity': Decimal('20')}, change_reason=REASON,
                                         expected_graph_hash=digest(package_snapshot(package)), expected_review=0,
                                         session_auth_hash=stale),
            lambda stale: review_package(actor=self.reviewer, package_id=package.pk, decision='defer', reason=REASON,
                                         expected_review=0, expected_graph_hash=digest(package_snapshot(package)),
                                         session_auth_hash=stale),
        ]
        for stale in self.stale_hashes():
            for call in calls:
                with self.subTest(stale=type(stale).__name__, call=call.__name__ if hasattr(call, '__name__') else 'case'):
                    with self.assertRaises(PermissionDenied):
                        call(stale)
        self.assertEqual({model: model.objects.count() for model in before}, before)

    def test_password_changed_before_a_write_denies_the_previous_session_hash(self):
        previous = self.author.get_session_auth_hash()
        current = get_user_model().objects.get(pk=self.author.pk)
        current.set_password('synthetic-rotated')
        current.save(update_fields=['password'])
        with self.assertRaises(PermissionDenied):
            self.create_ingredient(actor=current, session_auth_hash=previous)
        self.assertFalse(IngredientDraft.objects.exists())
        self.assertEqual(self.create_ingredient(actor=current,
                                                session_auth_hash=current.get_session_auth_hash()).recorded_by_id,
                         current.pk)

    def test_writer_disabled_or_destaffed_before_a_write_is_denied_despite_stale_actor(self):
        for field in ('is_active', 'is_staff'):
            with self.subTest(field=field):
                stale_actor = get_user_model().objects.get(pk=self.author.pk)
                get_user_model().objects.filter(pk=self.author.pk).update(**{field: False})
                with self.assertRaises(PermissionDenied):
                    self.create_ingredient(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash())
                self.assertFalse(IngredientDraft.objects.exists())
                get_user_model().objects.filter(pk=self.author.pk).update(**{field: True})

    def test_add_permission_removed_before_a_write_is_denied_despite_stale_cache(self):
        stale_actor = get_user_model().objects.get(pk=self.editor.pk)
        self.assertTrue(stale_actor.has_perm('catalog.add_identityworkspace'))  # prime backend cache
        # Remove through a second instance so the request actor keeps its stale cache.
        other = get_user_model().objects.get(pk=self.editor.pk)
        other.user_permissions.remove(*Permission.objects.filter(content_type__app_label='catalog',
                                                                 codename='add_identityworkspace'))
        ingredient = self.create_ingredient()
        part = {'ingredient_id': ingredient.pk, 'numerator': Decimal('2.5'), 'numerator_unit': 'mg',
                'denominator': Decimal('1'), 'denominator_unit': 'tablet'}
        with self.assertRaises(PermissionDenied):
            create_ingredient(actor=stale_actor, data=dict(INGREDIENT),
                              session_auth_hash=stale_actor.get_session_auth_hash())
        with self.assertRaises(PermissionDenied):
            create_formulation(actor=stale_actor, data=dict(FORM), components=[part],
                               session_auth_hash=stale_actor.get_session_auth_hash())
        self.assertEqual(IngredientDraft.objects.count(), 1)

    def test_review_permission_removed_before_a_review_is_denied_despite_stale_cache(self):
        package = build(self.author)[-1]
        stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
        self.assertTrue(stale_actor.has_perm('catalog.review_identityworkspace'))  # prime backend cache
        other = get_user_model().objects.get(pk=self.reviewer.pk)
        other.user_permissions.remove(*Permission.objects.filter(content_type__app_label='catalog',
                                                                 codename='review_identityworkspace'))
        with self.assertRaises(PermissionDenied):
            review_package(actor=stale_actor, package_id=package.pk, decision='defer', reason=REASON,
                           expected_review=0, expected_graph_hash=digest(package_snapshot(package)),
                           session_auth_hash=stale_actor.get_session_auth_hash())
        self.assertFalse(IdentityPackageReview.objects.exists())

    def test_deleted_writer_is_denied_even_if_the_instance_still_looks_active(self):
        stale_actor = get_user_model().objects.get(pk=self.author.pk)
        self.assertTrue(stale_actor.has_perm('catalog.add_identityworkspace'))
        get_user_model().objects.filter(pk=self.author.pk).delete()
        with self.assertRaises(PermissionDenied):
            self.create_ingredient(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash())
        self.assertFalse(IngredientDraft.objects.exists())

    def test_password_changed_after_the_writer_recheck_can_still_race_the_write(self):
        # A remaining gap: the recheck is an unlocked point-in-time read, so a
        # credential change committed afterwards is not detected by this service.
        package = build(self.author)[-1]
        stale_actor = get_user_model().objects.get(pk=self.editor.pk)
        session_hash = stale_actor.get_session_auth_hash()
        # Compute the expected graph hash before parking the writer, so the patched
        # digest only fires inside the guarded transaction after the recheck.
        graph_hash = digest(package_snapshot(package))
        ready, resume = Event(), Event()

        def pause(*args, **kwargs):
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic identity writer did not resume')
            return digest(*args, **kwargs)

        def writer():
            close_old_connections()
            try:
                return revise_package(actor=stale_actor, parent_id=package.pk,
                                      data={**PACKAGE, 'quantity': Decimal('20')}, change_reason=REASON,
                                      expected_graph_hash=graph_hash, expected_review=0,
                                      session_auth_hash=session_hash)
            finally:
                close_old_connections()

        with patch('catalog.identity.digest', side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(writer)
                try:
                    self.assertTrue(ready.wait(10), 'Identity writer did not reach its graph digest')
                    current = get_user_model().objects.get(pk=self.editor.pk)
                    current.is_active = False
                    current.set_unusable_password()
                    current.save(update_fields=['is_active', 'password'])
                    get_user_model().objects.filter(pk=self.editor.pk).update(is_active=True)
                finally:
                    resume.set()
                child = future.result(timeout=20)
        self.assertEqual(child.recorded_by_id, self.editor.pk)
        self.assertEqual(IdentityPackageDraft.objects.count(), 2)
        self.assertFalse(get_user_model().objects.get(pk=self.editor.pk).has_usable_password())
