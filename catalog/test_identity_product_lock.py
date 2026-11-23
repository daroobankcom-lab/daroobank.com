"""Selected PostgreSQL concurrency checks for identity package/product writes."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.transaction import TransactionManagementError
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .identity import (IdentityConflict, digest, package_snapshot, review_package, revise_package)
from .models import (IngredientDraft, IdentityPackageDraft, IdentityPackageReview,
                     IdentityPackageRevision, IdentityProductDraft)
from .test_identity import ALL, PACKAGE, build, user

REASON = 'دلیل ساختگی برای بررسی یا اصلاح بسته'


@override_settings(STAFF_PORTAL_ENABLED=True)
class IdentityReviewInputTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = user('input-identity-author', *ALL)
        cls.reviewer = user('input-identity-reviewer', 'view_identityworkspace', 'review_identityworkspace')
        cls.viewer = user('input-identity-viewer', 'view_identityworkspace')
        cls.package = build(cls.author)[-1]
        cls.fingerprint = digest(package_snapshot(cls.package))

    def args(self, **kwargs):
        return {'actor': self.reviewer, 'package_id': self.package.pk, 'decision': 'defer', 'reason': REASON,
                'expected_review': 0, 'expected_graph_hash': self.fingerprint, **kwargs}

    def test_invalid_direct_inputs_conflict_without_writes(self):
        for field, values in [('decision', [None, True, [], {}, 1, 'unknown']),
                              ('package_id', [False, 0, -1, '1', 2**63]),
                              ('expected_review', [False, -1, '0', 2**63]),
                              ('expected_graph_hash', [None, [], 'a'*63, 'z'*64]),
                              ('reason', [None, [], 'short'])]:
            for value in values:
                with self.subTest(field=field, value=value), self.assertRaises(IdentityConflict):
                    review_package(**self.args(**{field: value}))
        self.assertFalse(IdentityPackageReview.objects.exists())

    def test_invalid_web_form_returns_private_400_without_write(self):
        self.client.force_login(self.reviewer)
        for field, value in [('decision', 'unknown'), ('expected_review', str(2**63)),
                             ('expected_graph_hash', 'g'*64)]:
            data = {'decision': 'defer', 'reason': REASON, 'expected_review': '0', 'expected_graph_hash': self.fingerprint}
            data[field] = value
            response = self.client.post(reverse('staff_identity_review', args=[self.package.pk]), data)
            self.assertEqual(response.status_code, 400)
            self.assertIn('no-store', response['Cache-Control'])
            self.assertEqual(response['Referrer-Policy'], 'same-origin')
            self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
            self.assertFalse(IdentityPackageReview.objects.exists())

    def test_permission_is_checked_before_invalid_arguments(self):
        with self.assertRaises(PermissionDenied):
            review_package(**self.args(actor=self.viewer, decision=[]))


class IdentityProductLockTests(TransactionTestCase):
    def setUp(self):
        self.author = user('lock-identity-author', *ALL)
        self.actor = user('lock-identity-actor', *ALL)
        self.ingredient, self.part, self.form, self.product, self.package = build(self.author)
        self.graph_hash = digest(package_snapshot(self.package))

    def run_writer(self, kind):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '12s'")
            actor = get_user_model().objects.get(pk=self.actor.pk)
            if kind == 'review':
                return review_package(actor=actor, package_id=self.package.pk, decision='defer', reason=REASON,
                                      expected_review=0, expected_graph_hash=self.graph_hash)
            return revise_package(actor=actor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                change_reason=REASON, expected_graph_hash=self.graph_hash, expected_review=0)
        finally:
            connection.close()

    def test_helper_requires_transaction_and_replaces_cached_product(self):
        from .identity import _lock_package_product
        package = IdentityPackageDraft.objects.select_related('product').get(pk=self.package.pk)
        self.assertEqual(package.product.name, self.product.name)
        with self.assertRaises(TransactionManagementError):
            _lock_package_product(package)
        with transaction.atomic():
            IdentityProductDraft.objects.filter(pk=self.product.pk).update(name='نام تازه ساختگی')
            self.assertEqual(package.product.name, self.product.name)
            _lock_package_product(package)
            self.assertEqual(package.product.name, 'نام تازه ساختگی')
            transaction.set_rollback(True)

    def test_dangling_product_fails_closed_for_both_writers(self):
        with transaction.atomic():
            IdentityPackageDraft.objects.filter(pk=self.package.pk).update(product_id=2_147_483_000)
            with self.assertRaises(IdentityConflict):
                review_package(actor=self.actor, package_id=self.package.pk, decision='defer', reason=REASON,
                               expected_review=0, expected_graph_hash=self.graph_hash)
            with self.assertRaises(IdentityConflict):
                revise_package(actor=self.actor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                    change_reason=REASON, expected_graph_hash=self.graph_hash, expected_review=0)
            self.assertFalse(IdentityPackageReview.objects.exists())
            self.assertFalse(IdentityPackageRevision.objects.exists())
            IdentityPackageDraft.objects.filter(pk=self.package.pk).update(product_id=self.product.pk)

    def test_lock_is_held_until_outer_transaction_finishes(self):
        ready, resume = Event(), Event()
        def outer_worker():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                with transaction.atomic():
                    event = review_package(actor=actor, package_id=self.package.pk, decision='defer', reason=REASON,
                        expected_review=0, expected_graph_hash=self.graph_hash)
                    ready.set()
                    if not resume.wait(8): raise TimeoutError('Outer transaction did not finish')
                return event
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(outer_worker)
            try:
                self.assertTrue(ready.wait(8))
                with self.assertRaises(DatabaseError), transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '300ms'")
                    IdentityProductDraft.objects.filter(pk=self.product.pk).update(name='تغییر ساختگی')
            finally:
                resume.set()
            self.assertIsNotNone(future.result(timeout=10))
        self.assertEqual(IdentityProductDraft.objects.filter(pk=self.product.pk).update(name='تغییر ساختگی'), 1)

    def test_same_transaction_bypass_can_change_ingredient_after_snapshot(self):
        from .identity import _require_creator_accounts
        def mutate(ids, *, using):
            _require_creator_accounts(ids, using=using)
            IngredientDraft.objects.filter(pk=self.ingredient.pk).update(name_fa='ماده تغییر یافته ساختگی')
        try:
            with patch('catalog.identity._require_creator_accounts', side_effect=mutate):
                event = review_package(actor=self.actor, package_id=self.package.pk, decision='defer', reason=REASON,
                    expected_review=0, expected_graph_hash=self.graph_hash)
            self.assertEqual(event.graph_snapshot['product']['formulation']['ingredients'][0]['name_fa'], self.ingredient.name_fa)
            self.assertEqual(IngredientDraft.objects.get(pk=self.ingredient.pk).name_fa, 'ماده تغییر یافته ساختگی')
        finally:
            IngredientDraft.objects.filter(pk=self.ingredient.pk).update(name_fa=self.ingredient.name_fa)

    def test_product_update_waits_for_each_writer_and_can_proceed_after_commit(self):
        from .identity import _require_creator_accounts
        for kind in ('review', 'revision'):
            with self.subTest(kind=kind):
                # Keep scenarios independent, including expected review version.
                if kind == 'revision':
                    IdentityPackageReview.objects.all().delete()
                ready, resume = Event(), Event()
                def pause(ids, *, using):
                    _require_creator_accounts(ids, using=using)
                    ready.set()
                    if not resume.wait(8): raise TimeoutError('Writer did not resume')
                with patch('catalog.identity._require_creator_accounts', side_effect=pause):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(self.run_writer, kind)
                        try:
                            self.assertTrue(ready.wait(8))
                            with self.assertRaises(DatabaseError), transaction.atomic():
                                with connection.cursor() as cursor:
                                    cursor.execute("SET LOCAL lock_timeout = '300ms'")
                                IdentityProductDraft.objects.filter(pk=self.product.pk).update(name='تغییر ساختگی')
                        finally:
                            resume.set()
                        self.assertIsNotNone(future.result(timeout=10))
                IdentityProductDraft.objects.filter(pk=self.product.pk).update(name='تغییر ساختگی')
                IdentityProductDraft.objects.filter(pk=self.product.pk).update(name=self.product.name)

    def test_product_changed_before_lock_is_reread_and_conflicts(self):
        from .identity import _lock_package_product
        for kind in ('review', 'revision'):
            with self.subTest(kind=kind):
                waiting = Event()
                def signal(package):
                    waiting.set()
                    return _lock_package_product(package)
                with patch('catalog.identity._lock_package_product', side_effect=signal):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with transaction.atomic():
                            IdentityProductDraft.objects.filter(pk=self.product.pk).update(name='تغییر هم‌زمان ساختگی')
                            future = pool.submit(self.run_writer, kind)
                            self.assertTrue(waiting.wait(8))
                            self.assertFalse(future.done())
                        with self.assertRaises(IdentityConflict):
                            future.result(timeout=10)
                self.assertFalse(IdentityPackageReview.objects.exists())
                self.assertFalse(IdentityPackageRevision.objects.exists())
                self.assertEqual(IdentityPackageDraft.objects.count(), 1)
                IdentityProductDraft.objects.filter(pk=self.product.pk).update(name=self.product.name)
