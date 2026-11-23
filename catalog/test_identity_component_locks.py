"""Bounded identity package graph row-lock tests on synthetic PostgreSQL data."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.transaction import TransactionManagementError
from django.test import TransactionTestCase
from django.test.utils import CaptureQueriesContext

from .identity import (IdentityConflict, MAX_COMPONENTS, create_formulation, create_ingredient, create_package,
                       create_product, digest, formulation_snapshot, package_snapshot, product_snapshot, review_package,
                       revise_identity, revise_package)
from .models import (FormulationComponent, FormulationDraft, IdentityPackageDraft, IdentityPackageReview,
                     IdentityPackageRevision, IngredientDraft)
from .test_identity import ALL, FORM, INGREDIENT, PACKAGE, PRODUCT, build, user

REASON = 'دلیل ساختگی برای بررسی و اصلاح بسته'


class IdentityComponentLockTests(TransactionTestCase):
    def setUp(self):
        self.author = user('component-lock-author', *ALL)
        self.actor = user('component-lock-reviewer', *ALL)
        self.ingredient, self.part, self.form, self.product, self.package = build(self.author)
        self.component = FormulationComponent.objects.get(formulation=self.form)
        self.graph_hash = digest(package_snapshot(self.package))

    @contextmanager
    def assert_lock_timeout(self):
        with self.assertRaises(DatabaseError) as caught:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '300ms'")
                yield
        cause = caught.exception.__cause__
        self.assertEqual(getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None), '55P03')

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

    def test_component_and_ingredient_updates_wait_for_both_writers(self):
        from .identity import _require_creator_accounts
        for kind in ('review', 'revision'):
            for model, pk, change in [(FormulationComponent, self.component.pk, {'numerator': Decimal('4')}),
                                      (IngredientDraft, self.ingredient.pk, {'name_fa': 'ماده تغییر یافته ساختگی'})]:
                with self.subTest(kind=kind, model=model.__name__):
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
                                with self.assert_lock_timeout():
                                    model.objects.filter(pk=pk).update(**change)
                            finally:
                                resume.set()
                            self.assertIsNotNone(future.result(timeout=10))
                    self.assertEqual(model.objects.filter(pk=pk).update(**change), 1)
                    original = {'numerator': self.part['numerator']} if model is FormulationComponent else {'name_fa': self.ingredient.name_fa}
                    model.objects.filter(pk=pk).update(**original)

    def test_locked_preexisting_update_is_reread_and_conflicts(self):
        from .identity import _lock_formulation_components
        for kind in ('review', 'revision'):
            for model, pk, change in [(FormulationComponent, self.component.pk, {'numerator': Decimal('4')}),
                                      (IngredientDraft, self.ingredient.pk, {'name_fa': 'ماده تغییر یافته ساختگی'})]:
                with self.subTest(kind=kind, model=model.__name__):
                    waiting = Event()
                    def signal(form):
                        waiting.set()
                        return _lock_formulation_components(form)
                    with patch('catalog.identity._lock_formulation_components', side_effect=signal):
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            with transaction.atomic():
                                model.objects.filter(pk=pk).update(**change)
                                future = pool.submit(self.run_writer, kind)
                                self.assertTrue(waiting.wait(8))
                                self.assertFalse(future.done())
                            with self.assertRaises(IdentityConflict):
                                future.result(timeout=10)
                    self.assertFalse(IdentityPackageReview.objects.exists())
                    self.assertFalse(IdentityPackageRevision.objects.exists())
                    self.assertEqual(IdentityPackageDraft.objects.count(), 1)
                    original = {'numerator': self.part['numerator']} if model is FormulationComponent else {'name_fa': self.ingredient.name_fa}
                    model.objects.filter(pk=pk).update(**original)

    def dependent_writer(self, kind):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '12s'")
            actor = get_user_model().objects.get(pk=self.actor.pk)
            if kind == 'create_product':
                return create_product(actor=actor, data=PRODUCT, formulation_id=self.form.pk)
            if kind == 'create_package':
                return create_package(actor=actor, data=PACKAGE, product_id=self.product.pk)
            if kind == 'revise_formulation':
                return revise_identity(actor=actor, kind='formulation', parent_id=self.form.pk,
                    data={**FORM, 'name': 'اصلاح فرمول ساختگی'}, components=[self.part], change_reason=REASON,
                    expected_graph_hash=digest(formulation_snapshot(self.form)))
            return revise_identity(actor=actor, kind='product', parent_id=self.product.pk,
                data={**PRODUCT, 'name': 'اصلاح فرآورده ساختگی'}, change_reason=REASON,
                expected_graph_hash=digest(product_snapshot(self.product)))
        finally:
            connection.close()

    def test_other_dependent_writers_hold_component_and_ingredient_locks(self):
        from .identity import _require_creator_accounts
        kinds = ('create_product', 'create_package', 'revise_formulation', 'revise_product')
        for kind in kinds:
            for model, pk, change in [(FormulationComponent, self.component.pk, {'numerator': Decimal('4')}),
                                      (IngredientDraft, self.ingredient.pk, {'name_fa': 'ماده تغییر یافته ساختگی'})]:
                with self.subTest(kind=kind, model=model.__name__):
                    ready, resume = Event(), Event()
                    def pause(ids, *, using):
                        _require_creator_accounts(ids, using=using)
                        ready.set()
                        if not resume.wait(8): raise TimeoutError('Writer did not resume')
                    with patch('catalog.identity._require_creator_accounts', side_effect=pause):
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            future = pool.submit(self.dependent_writer, kind)
                            try:
                                self.assertTrue(ready.wait(8))
                                with self.assert_lock_timeout():
                                    model.objects.filter(pk=pk).update(**change)
                            finally:
                                resume.set()
                            self.assertIsNotNone(future.result(timeout=10))
                    self.assertEqual(model.objects.filter(pk=pk).update(**change), 1)
                    original = {'numerator': self.part['numerator']} if model is FormulationComponent else {'name_fa': self.ingredient.name_fa}
                    model.objects.filter(pk=pk).update(**original)

    def test_other_dependent_writers_hold_formulation_lock(self):
        from .identity import _require_creator_accounts
        for kind in ('create_product', 'create_package', 'revise_formulation', 'revise_product'):
            with self.subTest(kind=kind):
                ready, resume = Event(), Event()
                def pause(ids, *, using):
                    _require_creator_accounts(ids, using=using)
                    ready.set()
                    if not resume.wait(8): raise TimeoutError('Writer did not resume')
                with patch('catalog.identity._require_creator_accounts', side_effect=pause):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        future = pool.submit(self.dependent_writer, kind)
                        try:
                            self.assertTrue(ready.wait(8))
                            with self.assert_lock_timeout():
                                FormulationDraft.objects.filter(pk=self.form.pk).update(name='فرمول ساختگی تازه')
                        finally:
                            resume.set()
                        self.assertIsNotNone(future.result(timeout=10))
                self.assertEqual(FormulationDraft.objects.filter(pk=self.form.pk).update(name='فرمول ساختگی تازه'), 1)
                FormulationDraft.objects.filter(pk=self.form.pk).update(name=self.form.name)

    def test_other_dependent_writers_reread_updates_completed_before_locks(self):
        from .identity import _lock_formulation_components
        for kind in ('create_product', 'create_package', 'revise_formulation', 'revise_product'):
            for model, pk, change in [(FormulationComponent, self.component.pk, {'numerator': Decimal('4')}),
                                      (IngredientDraft, self.ingredient.pk, {'name_fa': 'ماده تغییر یافته ساختگی'})]:
                with self.subTest(kind=kind, model=model.__name__):
                    waiting = Event()
                    def signal(form):
                        waiting.set()
                        return _lock_formulation_components(form)
                    with patch('catalog.identity._lock_formulation_components', side_effect=signal):
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            with transaction.atomic():
                                model.objects.filter(pk=pk).update(**change)
                                future = pool.submit(self.dependent_writer, kind)
                                self.assertTrue(waiting.wait(8))
                                self.assertFalse(future.done())
                            with self.assertRaises(IdentityConflict):
                                future.result(timeout=10)
                    original = {'numerator': self.part['numerator']} if model is FormulationComponent else {'name_fa': self.ingredient.name_fa}
                    model.objects.filter(pk=pk).update(**original)

    def test_helper_requires_atomic_and_handles_missing_ingredient(self):
        from .identity import _lock_formulation_components
        with self.assertRaises(TransactionManagementError):
            _lock_formulation_components(self.form)
        with transaction.atomic():
            FormulationComponent.objects.filter(pk=self.component.pk).update(ingredient_id=2_147_483_000)
            with self.assertRaises(IdentityConflict):
                review_package(actor=self.actor, package_id=self.package.pk, decision='defer', reason=REASON,
                               expected_review=0, expected_graph_hash=self.graph_hash)
            with self.assertRaises(IdentityConflict):
                revise_package(actor=self.actor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                    change_reason=REASON, expected_graph_hash=self.graph_hash, expected_review=0)
            self.assertFalse(IdentityPackageReview.objects.exists())
            self.assertFalse(IdentityPackageRevision.objects.exists())
            FormulationComponent.objects.filter(pk=self.component.pk).update(ingredient_id=self.ingredient.pk)

    def test_component_and_ingredient_locks_persist_until_outer_commit(self):
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
                for model, pk, change in [(FormulationComponent, self.component.pk, {'numerator': Decimal('4')}),
                                          (IngredientDraft, self.ingredient.pk, {'name_fa': 'تغییر ساختگی'})]:
                    with self.assert_lock_timeout():
                        model.objects.filter(pk=pk).update(**change)
            finally:
                resume.set()
            self.assertIsNotNone(future.result(timeout=10))

    def test_locks_use_bounded_component_selection_and_ordered_ingredient_ids(self):
        ingredients = [self.ingredient] + [create_ingredient(actor=self.author,
            data={**INGREDIENT, 'name_fa': f'ماده ساختگی {index}'}) for index in range(4)]
        parts = [{**self.part, 'ingredient_id': item.pk} for item in reversed(ingredients)]
        form = create_formulation(actor=self.author, data=FORM, components=parts)
        product = create_product(actor=self.author, data=PRODUCT, formulation_id=form.pk)
        package = create_package(actor=self.author, data=PACKAGE, product_id=product.pk)
        from .identity import _lock_formulation_components
        with transaction.atomic(), CaptureQueriesContext(connection) as captured:
            rows = _lock_formulation_components(form)
        self.assertEqual(len(rows), MAX_COMPONENTS)
        self.assertEqual(len(captured), 2)
        sql = [q['sql'].upper() for q in captured]
        self.assertIn('FOR UPDATE', sql[0]); self.assertIn('LIMIT 6', sql[0]); self.assertIn('ORDER BY', sql[0])
        self.assertIn('FOR UPDATE', sql[1]); self.assertIn('ORDER BY', sql[1])

    def test_other_dependent_writers_reject_missing_ingredient_without_writes(self):
        from .models import FormulationDraft, IdentityProductDraft, FormulationRevision, ProductRevision
        initial = tuple(model.objects.count() for model in (FormulationDraft, IdentityProductDraft,
            IdentityPackageDraft, FormulationRevision, ProductRevision))
        with transaction.atomic():
            FormulationComponent.objects.filter(pk=self.component.pk).update(ingredient_id=2_147_483_000)
            operations = [
                lambda: create_product(actor=self.actor, data=PRODUCT, formulation_id=self.form.pk),
                lambda: create_package(actor=self.actor, data=PACKAGE, product_id=self.product.pk),
                lambda: revise_identity(actor=self.actor, kind='formulation', parent_id=self.form.pk,
                    data={**FORM, 'name': 'فرمول اصلاحی ساختگی'}, components=[self.part], change_reason=REASON,
                    expected_graph_hash='a' * 64),
                lambda: revise_identity(actor=self.actor, kind='product', parent_id=self.product.pk,
                    data={**PRODUCT, 'name': 'فرآورده اصلاحی ساختگی'}, change_reason=REASON,
                    expected_graph_hash='a' * 64),
            ]
            for operation in operations:
                with self.assertRaises(IdentityConflict):
                    operation()
            self.assertEqual(tuple(model.objects.count() for model in (FormulationDraft, IdentityProductDraft,
                IdentityPackageDraft, FormulationRevision, ProductRevision)), initial)
            FormulationComponent.objects.filter(pk=self.component.pk).update(ingredient_id=self.ingredient.pk)

    def test_shared_ingredients_in_reverse_order_complete_selected_parallel_reviews(self):
        other = create_ingredient(actor=self.author, data={**INGREDIENT, 'name_fa': 'ماده مشترک دوم'})
        parts = [self.part, {**self.part, 'ingredient_id': other.pk}]
        packages = []
        for ordered_parts in (parts, list(reversed(parts))):
            form = create_formulation(actor=self.author, data=FORM, components=ordered_parts)
            product = create_product(actor=self.author, data=PRODUCT, formulation_id=form.pk)
            packages.append(create_package(actor=self.author, data=PACKAGE, product_id=product.pk))
        hashes = [digest(package_snapshot(package)) for package in packages]
        barrier = Barrier(2, timeout=8)
        def worker(index):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '12s'")
                actor = get_user_model().objects.get(pk=self.actor.pk)
                barrier.wait()
                return review_package(actor=actor, package_id=packages[index].pk, decision='defer', reason=REASON,
                    expected_review=0, expected_graph_hash=hashes[index])
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            events = list(pool.map(worker, range(2)))
        self.assertEqual({event.package_id for event in events}, {package.pk for package in packages})
        self.assertEqual(IdentityPackageReview.objects.count(), 2)

    def test_missing_component_fails_closed(self):
        FormulationComponent.objects.filter(pk=self.component.pk).delete()
        for kind in ('review', 'revision'):
            with self.subTest(kind=kind), self.assertRaises(IdentityConflict):
                if kind == 'review':
                    review_package(actor=self.actor, package_id=self.package.pk, decision='defer', reason=REASON,
                                   expected_review=0, expected_graph_hash=self.graph_hash)
                else:
                    revise_package(actor=self.actor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                                   change_reason=REASON, expected_review=0, expected_graph_hash=self.graph_hash)
        self.assertFalse(IdentityPackageReview.objects.exists())
        self.assertFalse(IdentityPackageRevision.objects.exists())

    def test_deleting_only_component_before_lock_makes_selected_writers_conflict(self):
        from .identity import _lock_formulation_components
        for kind in ('review', 'revision', 'create_product', 'create_package', 'revise_formulation', 'revise_product'):
            with self.subTest(kind=kind):
                waiting = Event()
                def signal(form):
                    waiting.set()
                    return _lock_formulation_components(form)
                with patch('catalog.identity._lock_formulation_components', side_effect=signal):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with transaction.atomic():
                            FormulationComponent.objects.filter(pk=self.component.pk).delete()
                            target = self.run_writer if kind in ('review', 'revision') else self.dependent_writer
                            future = pool.submit(target, kind)
                            self.assertTrue(waiting.wait(8))
                            self.assertFalse(future.done())
                        with self.assertRaises(IdentityConflict):
                            future.result(timeout=10)
                self.assertFalse(IdentityPackageReview.objects.exists())
                self.assertFalse(IdentityPackageRevision.objects.exists())
                FormulationComponent.objects.bulk_create([self.component])

    def test_immediate_concurrent_component_insert_waits_for_formulation(self):
        from .identity import _require_creator_accounts
        other = create_ingredient(actor=self.author, data={**INGREDIENT, 'name_fa': 'ماده دیگر ساختگی'})
        checked, resume = Event(), Event()
        def pause(ids, *, using):
            _require_creator_accounts(ids, using=using)
            checked.set()
            if not resume.wait(8): raise TimeoutError('Review did not resume')
        with patch('catalog.identity._require_creator_accounts', side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                writer = pool.submit(self.run_writer, 'review')
                try:
                    self.assertTrue(checked.wait(8))
                    with self.assert_lock_timeout():
                        with connection.cursor() as cursor:
                            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                        FormulationComponent.objects.create(formulation_id=self.form.pk, ingredient_id=other.pk,
                            ingredient_sha256=other.payload_sha256, ordinal=2, numerator=Decimal('2'), numerator_unit='mg',
                            denominator=Decimal('1'), denominator_unit='tablet')
                finally:
                    resume.set()
                self.assertIsNotNone(writer.result(timeout=10))
        self.assertEqual(FormulationComponent.objects.filter(formulation=self.form).count(), 1)

    def test_deferred_concurrent_component_insert_can_commit_after_review(self):
        from .identity import _require_creator_accounts
        other = create_ingredient(actor=self.author, data={**INGREDIENT, 'name_fa': 'ماده دیگر ساختگی'})
        checked, resume_review, inserted, resume_insert = Event(), Event(), Event(), Event()
        def pause(ids, *, using):
            _require_creator_accounts(ids, using=using)
            checked.set()
            if not resume_review.wait(8): raise TimeoutError('Review did not resume')
        def insert_later():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL statement_timeout = '12s'")
                        cursor.execute('SET CONSTRAINTS ALL DEFERRED')
                    FormulationComponent.objects.create(formulation_id=self.form.pk, ingredient_id=other.pk,
                        ingredient_sha256=other.payload_sha256, ordinal=2, numerator=Decimal('2'), numerator_unit='mg',
                        denominator=Decimal('1'), denominator_unit='tablet')
                    inserted.set()
                    if not resume_insert.wait(8): raise TimeoutError('Insert did not resume')
            finally:
                connection.close()
        with patch('catalog.identity._require_creator_accounts', side_effect=pause):
            with ThreadPoolExecutor(max_workers=2) as pool:
                writer = pool.submit(self.run_writer, 'review')
                try:
                    self.assertTrue(checked.wait(8))
                    inserter = pool.submit(insert_later)
                    self.assertTrue(inserted.wait(8))
                    resume_review.set()
                    event = writer.result(timeout=10)
                    resume_insert.set()
                    inserter.result(timeout=10)
                finally:
                    resume_review.set()
                    resume_insert.set()
        self.assertEqual(len(event.graph_snapshot['product']['formulation']['components']), 1)
        self.assertEqual(FormulationComponent.objects.filter(formulation=self.form).count(), 2)
