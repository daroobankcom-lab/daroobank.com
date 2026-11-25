"""Selected synthetic missing graph creators; temporary deletion is rolled back."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from daroobank.account_checks import current_accounts
from .identity import (IdentityConflict, create_ingredient, create_formulation, create_product, create_package,
                       ingredient_snapshot, formulation_snapshot, product_snapshot, package_snapshot,
                       review_package, revise_identity, revise_package, digest)
from .models import (IngredientDraft, FormulationDraft, FormulationComponent, IdentityProductDraft,
                     IdentityPackageDraft, IdentityPackageReview, IdentityPackageRevision,
                     IngredientRevision, FormulationRevision, ProductRevision)
from .test_identity import ALL, INGREDIENT, FORM, PRODUCT, PACKAGE, user

REASON = 'دلیل ساختگی برای بررسی و اصلاح هویت'


def build_chain():
    authors = {kind: user(f'creator-{kind}', *ALL) for kind in ('ingredient', 'ingredient2', 'formulation', 'product', 'package')}
    editor = user('creator-editor', *ALL)
    viewer = user('creator-viewer', 'view_identityworkspace')
    ingredients = [create_ingredient(actor=authors[kind], data={**INGREDIENT, 'name_fa': f'ماده فرضی {kind}'})
                   for kind in ('ingredient', 'ingredient2')]
    parts = [{'ingredient_id': item.pk, 'numerator': Decimal('2'), 'numerator_unit': 'mg',
              'denominator': Decimal('1'), 'denominator_unit': 'tablet'} for item in ingredients]
    form = create_formulation(actor=authors['formulation'], data=FORM, components=parts)
    product = create_product(actor=authors['product'], data=PRODUCT, formulation_id=form.pk)
    package = create_package(actor=authors['package'], data=PACKAGE, product_id=product.pk)
    return authors, editor, viewer, ingredients, parts, form, product, package


def delete_account_temporarily(actor):
    # Direct SQL intentionally bypasses PROTECT; FK checks are deferred by PostgreSQL.
    table = connection.ops.quote_name(get_user_model()._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(f'DELETE FROM {table} WHERE id = %s', [actor.pk])
        assert cursor.rowcount == 1


@override_settings(STAFF_PORTAL_ENABLED=True)
class IdentityMissingCreatorTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        (cls.authors, cls.editor, cls.viewer, cls.ingredients, cls.parts,
         cls.form, cls.product, cls.package) = build_chain()

    def operations(self):
        return [
            ('create formulation', ('ingredient', 'ingredient2'), lambda: create_formulation(actor=self.editor, data=FORM, components=self.parts)),
            ('create product', ('ingredient', 'ingredient2', 'formulation'), lambda: create_product(actor=self.editor, data=PRODUCT, formulation_id=self.form.pk)),
            ('create package', ('ingredient', 'ingredient2', 'formulation', 'product'), lambda: create_package(actor=self.editor, data=PACKAGE, product_id=self.product.pk)),
            ('review package', tuple(self.authors), lambda: review_package(actor=self.editor, package_id=self.package.pk,
                decision='defer', reason=REASON, expected_review=0, expected_graph_hash=digest(package_snapshot(self.package)))),
            ('revise ingredient', ('ingredient',), lambda: revise_identity(actor=self.editor, kind='ingredient', parent_id=self.ingredients[0].pk,
                data={**INGREDIENT, 'name_fa': 'ماده اصلاحی ساختگی'}, change_reason=REASON,
                expected_graph_hash=digest(ingredient_snapshot(self.ingredients[0])))),
            ('revise formulation', ('ingredient', 'ingredient2', 'formulation'), lambda: revise_identity(actor=self.editor,
                kind='formulation', parent_id=self.form.pk, data={**FORM, 'name': 'فرمول اصلاحی ساختگی'},
                components=self.parts, change_reason=REASON, expected_graph_hash=digest(formulation_snapshot(self.form)))),
            ('revise product', ('ingredient', 'ingredient2', 'formulation', 'product'), lambda: revise_identity(actor=self.editor,
                kind='product', parent_id=self.product.pk, data={**PRODUCT, 'name': 'فرآورده اصلاحی ساختگی'},
                change_reason=REASON, expected_graph_hash=digest(product_snapshot(self.product)))),
            ('revise package', tuple(self.authors), lambda: revise_package(actor=self.editor, parent_id=self.package.pk,
                data={**PACKAGE, 'quantity': Decimal('20')}, change_reason=REASON, expected_review=0,
                expected_graph_hash=digest(package_snapshot(self.package)))),
        ]

    def counts(self):
        return tuple(model.objects.count() for model in (IngredientDraft, FormulationDraft, FormulationComponent,
            IdentityProductDraft, IdentityPackageDraft, IdentityPackageReview, IdentityPackageRevision,
            IngredientRevision, FormulationRevision, ProductRevision))

    def test_selected_writers_reject_each_missing_graph_creator_without_writes(self):
        before = self.counts()
        for label, affected, operation in self.operations():
            for kind in affected:
                with self.subTest(operation=label, missing=kind), transaction.atomic():
                    delete_account_temporarily(self.authors[kind])
                    with self.assertRaisesMessage(IdentityConflict, 'حساب ثبت‌کننده زنجیره در دسترس نیست'):
                        operation()
                    self.assertEqual(self.counts(), before)
                    transaction.set_rollback(True)

    def test_selected_writers_still_succeed_for_existing_creators(self):
        before = self.counts()
        for label, _, operation in self.operations():
            with self.subTest(operation=label), transaction.atomic():
                self.assertIsNotNone(operation())
                self.assertNotEqual(self.counts(), before)
                transaction.set_rollback(True)

    def test_all_package_review_decisions_conflict_for_missing_creator(self):
        graph_hash = digest(package_snapshot(self.package))
        with transaction.atomic():
            delete_account_temporarily(self.authors['ingredient2'])
            for decision in ('defer', 'reject', 'further_review'):
                with self.subTest(decision=decision), self.assertRaises(IdentityConflict):
                    review_package(actor=self.editor, package_id=self.package.pk, decision=decision,
                        reason=REASON, expected_review=0, expected_graph_hash=graph_hash)
            self.assertFalse(IdentityPackageReview.objects.exists())
            transaction.set_rollback(True)

    def test_review_permission_and_self_review_still_take_precedence(self):
        graph_hash = digest(package_snapshot(self.package))
        with transaction.atomic():
            delete_account_temporarily(self.authors['ingredient2'])
            for actor in (self.viewer, self.authors['package']):
                with self.subTest(actor=actor.pk), self.assertRaises(PermissionDenied):
                    review_package(actor=actor, package_id=self.package.pk, decision='defer', reason=REASON,
                        expected_review=0, expected_graph_hash=graph_hash)
            transaction.set_rollback(True)

    def test_http_conflicts_and_views_remain_private(self):
        graph_hash = digest(package_snapshot(self.package))
        payload = {'decision': 'defer', 'reason': REASON, 'expected_review': 0, 'expected_graph_hash': graph_hash}
        with transaction.atomic():
            delete_account_temporarily(self.authors['ingredient2'])
            self.client.force_login(self.editor)
            before = self.counts()
            response = self.client.post(reverse('staff_identity_review', args=[self.package.pk]), payload)
            self.assertEqual(response.status_code, 409)
            self.assertIn('no-store', response['Cache-Control'])
            self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
            self.assertEqual(response['Referrer-Policy'], 'same-origin')
            self.assertNotContains(response, 'name="expected_review"', status_code=409)
            self.assertContains(response, 'حساب ثبت‌کننده‌ای در دسترس نباشد', status_code=409)
            create = self.client.post(reverse('staff_identity_create', args=['product']),
                {**PRODUCT, 'synthetic_ack': 'on', 'formulation_id': self.form.pk})
            self.assertEqual(create.status_code, 409)
            self.assertContains(create, 'حساب ثبت‌کننده زنجیره در دسترس نیست', status_code=409)
            self.assertEqual(self.counts(), before)
            transaction.set_rollback(True)

    def test_existing_inactive_account_is_not_a_qualification_check(self):
        get_user_model().objects.filter(pk__in=[a.pk for a in self.authors.values()]).update(is_active=False, is_staff=False)
        event = review_package(actor=self.editor, package_id=self.package.pk, decision='defer', reason=REASON,
            expected_review=0, expected_graph_hash=digest(package_snapshot(self.package)))
        self.assertEqual(event.reviewer_id, self.editor.pk)

    def test_lookup_checks_distinct_bounded_graph_accounts_once(self):
        with patch('catalog.identity.current_accounts', wraps=current_accounts) as lookup:
            review_package(actor=self.editor, package_id=self.package.pk, decision='defer', reason=REASON,
                expected_review=0, expected_graph_hash=digest(package_snapshot(self.package)))
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(set(lookup.call_args.args[0]), {item.pk for item in self.authors.values()})
        self.assertEqual(lookup.call_args.kwargs['using'], self.package._state.db)

    def test_five_ingredient_graph_checks_at_most_eight_distinct_accounts(self):
        ingredients = list(self.ingredients)
        authors = list(self.authors.values())
        for index in range(3):
            creator = user(f'creator-extra-{index}', *ALL)
            authors.append(creator)
            ingredients.append(create_ingredient(actor=creator, data={**INGREDIENT, 'name_fa': f'ماده اضافی ساختگی {index}'}))
        parts = [{**self.parts[0], 'ingredient_id': item.pk} for item in ingredients]
        form = create_formulation(actor=self.authors['formulation'], data=FORM, components=parts)
        product = create_product(actor=self.authors['product'], data=PRODUCT, formulation_id=form.pk)
        package = create_package(actor=self.authors['package'], data=PACKAGE, product_id=product.pk)
        with patch('catalog.identity.current_accounts', wraps=current_accounts) as lookup:
            review_package(actor=self.editor, package_id=package.pk, decision='defer', reason=REASON,
                expected_review=0, expected_graph_hash=digest(package_snapshot(package)))
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(len(set(lookup.call_args.args[0])), 8)
        self.assertEqual(set(lookup.call_args.args[0]), {item.pk for item in authors})

    def test_same_transaction_bypass_can_change_account_id_after_read(self):
        missing = 2_147_483_000
        def mutate(ids, *, using):
            accounts = current_accounts(ids, using=using)
            IdentityPackageDraft.objects.filter(pk=self.package.pk).update(recorded_by_id=missing)
            return accounts
        try:
            with patch('catalog.identity.current_accounts', side_effect=mutate):
                event = review_package(actor=self.editor, package_id=self.package.pk, decision='defer', reason=REASON,
                    expected_review=0, expected_graph_hash=digest(package_snapshot(self.package)))
            self.assertEqual(event.graph_snapshot['recorded_by_id'], self.authors['package'].pk)
            self.assertEqual(IdentityPackageDraft.objects.get(pk=self.package.pk).recorded_by_id, missing)
        finally:
            IdentityPackageDraft.objects.filter(pk=self.package.pk).update(recorded_by_id=self.authors['package'].pk)


class IdentityCreatorConcurrencyTests(TransactionTestCase):
    def setUp(self):
        (self.authors, self.editor, self.viewer, self.ingredients, self.parts,
         self.form, self.product, self.package) = build_chain()

    def test_review_does_not_lock_creator_accounts(self):
        ready, resume = Event(), Event()
        def pause(ids, *, using):
            result = current_accounts(ids, using=using)
            ready.set()
            if not resume.wait(8):
                raise TimeoutError('Synthetic review did not resume')
            return result
        def worker():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '2s'")
                    cursor.execute("SET statement_timeout = '12s'")
                actor = get_user_model().objects.get(pk=self.editor.pk)
                package = IdentityPackageDraft.objects.get(pk=self.package.pk)
                return review_package(actor=actor, package_id=package.pk, decision='defer', reason=REASON,
                    expected_review=0, expected_graph_hash=digest(package_snapshot(package)))
            finally:
                connection.close()
        with patch('catalog.identity.current_accounts', side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(worker)
                try:
                    self.assertTrue(ready.wait(8))
                    self.assertEqual(get_user_model().objects.filter(pk=self.authors['ingredient'].pk).update(is_active=False), 1)
                finally:
                    resume.set()
                self.assertIsNotNone(future.result(timeout=10))
