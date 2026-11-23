"""Selected PostgreSQL races for package review/correction formulation locking."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from queue import Queue
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.transaction import TransactionManagementError
from django.test import TransactionTestCase

from .identity import IdentityConflict, create_ingredient, digest, package_snapshot, review_package, revise_package
from .models import (FormulationComponent, FormulationDraft, IdentityPackageDraft, IdentityPackageReview,
                     IdentityPackageRevision, IdentityProductDraft)
from .identity_test_utils import assert_blocked_by_current_transaction, publish_backend_pid
from .test_identity import ALL, INGREDIENT, PACKAGE, build, user

REASON = 'دلیل ساختگی برای بررسی یا اصلاح بسته'


class IdentityFormulationLockTests(TransactionTestCase):
    def setUp(self):
        self.author = user('form-lock-identity-author', *ALL)
        self.actor = user('form-lock-identity-actor', *ALL)
        self.ingredient, self.part, self.form, self.product, self.package = build(self.author)
        self.graph_hash = digest(package_snapshot(self.package))

    def run_writer(self, kind, pid_queue=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '12s'")
                publish_backend_pid(cursor, pid_queue)
            actor = get_user_model().objects.get(pk=self.actor.pk)
            if kind == 'review':
                return review_package(actor=actor, package_id=self.package.pk, decision='defer', reason=REASON,
                                      expected_review=0, expected_graph_hash=self.graph_hash)
            return revise_package(actor=actor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                change_reason=REASON, expected_graph_hash=self.graph_hash, expected_review=0)
        finally:
            connection.close()

    def test_formulation_update_waits_for_both_writers_then_succeeds(self):
        from .identity import _require_creator_accounts
        for kind in ('review', 'revision'):
            with self.subTest(kind=kind):
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
                                FormulationDraft.objects.filter(pk=self.form.pk).update(name='تغییر ساختگی')
                        finally:
                            resume.set()
                        self.assertIsNotNone(future.result(timeout=10))
                self.assertEqual(FormulationDraft.objects.filter(pk=self.form.pk).update(name='تغییر ساختگی'), 1)
                FormulationDraft.objects.filter(pk=self.form.pk).update(name=self.form.name)

    def test_formulation_changed_before_lock_is_reread_and_conflicts(self):
        from .identity import _lock_product_formulation
        for kind in ('review', 'revision'):
            with self.subTest(kind=kind):
                waiting, pids = Event(), Queue()
                def signal(product):
                    waiting.set()
                    return _lock_product_formulation(product)
                with patch('catalog.identity._lock_product_formulation', side_effect=signal):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with transaction.atomic():
                            FormulationDraft.objects.filter(pk=self.form.pk).update(name='تغییر هم‌زمان ساختگی')
                            future = pool.submit(self.run_writer, kind, pids)
                            self.assertTrue(waiting.wait(8))
                            assert_blocked_by_current_transaction(self, pids.get(timeout=5))
                            self.assertFalse(future.done())
                        with self.assertRaises(IdentityConflict):
                            future.result(timeout=10)
                self.assertFalse(IdentityPackageReview.objects.exists())
                self.assertFalse(IdentityPackageRevision.objects.exists())
                self.assertEqual(IdentityPackageDraft.objects.count(), 1)
                FormulationDraft.objects.filter(pk=self.form.pk).update(name=self.form.name)

    def test_helper_requires_transaction_and_replaces_cached_formulation(self):
        from .identity import _lock_product_formulation
        product = IdentityProductDraft.objects.select_related('formulation').get(pk=self.product.pk)
        self.assertEqual(product.formulation.name, self.form.name)
        with self.assertRaises(TransactionManagementError):
            _lock_product_formulation(product)
        with transaction.atomic():
            FormulationDraft.objects.filter(pk=self.form.pk).update(name='نام تازه ساختگی')
            self.assertEqual(product.formulation.name, self.form.name)
            _lock_product_formulation(product)
            self.assertEqual(product.formulation.name, 'نام تازه ساختگی')
            transaction.set_rollback(True)

    def test_dangling_formulation_conflicts_without_write(self):
        with transaction.atomic():
            IdentityProductDraft.objects.filter(pk=self.product.pk).update(formulation_id=2_147_483_000)
            with self.assertRaises(IdentityConflict):
                review_package(actor=self.actor, package_id=self.package.pk, decision='defer', reason=REASON,
                               expected_review=0, expected_graph_hash=self.graph_hash)
            with self.assertRaises(IdentityConflict):
                revise_package(actor=self.actor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                    change_reason=REASON, expected_graph_hash=self.graph_hash, expected_review=0)
            self.assertFalse(IdentityPackageReview.objects.exists())
            self.assertFalse(IdentityPackageRevision.objects.exists())
            IdentityProductDraft.objects.filter(pk=self.product.pk).update(formulation_id=self.form.pk)

    def test_formulation_lock_lasts_until_outer_transaction_ends(self):
        ready, resume = Event(), Event()
        def worker():
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
            future = pool.submit(worker)
            try:
                self.assertTrue(ready.wait(8))
                with self.assertRaises(DatabaseError), transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '300ms'")
                    FormulationDraft.objects.filter(pk=self.form.pk).update(name='تغییر ساختگی')
            finally:
                resume.set()
            self.assertIsNotNone(future.result(timeout=10))
        self.assertEqual(FormulationDraft.objects.filter(pk=self.form.pk).update(name='تغییر ساختگی'), 1)

    def test_same_transaction_bypass_can_change_component_after_snapshot(self):
        from .identity import _require_creator_accounts
        def mutate(ids, *, using):
            _require_creator_accounts(ids, using=using)
            FormulationComponent.objects.filter(formulation=self.form).update(numerator=Decimal('4'))
        try:
            with patch('catalog.identity._require_creator_accounts', side_effect=mutate):
                event = review_package(actor=self.actor, package_id=self.package.pk, decision='defer', reason=REASON,
                    expected_review=0, expected_graph_hash=self.graph_hash)
            self.assertEqual(event.graph_snapshot['product']['formulation']['components'][0]['numerator'], '2.5000')
            self.assertEqual(FormulationComponent.objects.get(formulation=self.form).numerator, Decimal('4'))
        finally:
            FormulationComponent.objects.filter(formulation=self.form).update(numerator=self.part['numerator'])

    def test_same_transaction_can_insert_component_after_graph_read(self):
        from .identity import _require_creator_accounts
        other = create_ingredient(actor=self.author, data={**INGREDIENT, 'name_fa': 'ماده دوم ساختگی'})
        def insert_after_read(ids, *, using):
            _require_creator_accounts(ids, using=using)
            FormulationComponent.objects.create(formulation_id=self.form.pk, ingredient_id=other.pk,
                ingredient_sha256=other.payload_sha256, ordinal=2, numerator=Decimal('2'), numerator_unit='mg',
                denominator=Decimal('1'), denominator_unit='tablet')
        with patch('catalog.identity._require_creator_accounts', side_effect=insert_after_read):
            event = review_package(actor=self.actor, package_id=self.package.pk, decision='defer', reason=REASON,
                expected_review=0, expected_graph_hash=self.graph_hash)
        self.assertEqual(len(event.graph_snapshot['product']['formulation']['components']), 1)
        self.assertEqual(FormulationComponent.objects.filter(formulation=self.form).count(), 2)
