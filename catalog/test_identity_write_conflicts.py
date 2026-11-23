"""Lock-error handling for selected private identity writers on synthetic PostgreSQL."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from queue import Queue
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.test import Client, TransactionTestCase
from django.urls import reverse

from .identity import (IdentityConflict, create_formulation, create_package, create_product, digest,
                       formulation_snapshot, ingredient_snapshot, package_snapshot, product_snapshot,
                       review_package, revise_identity, revise_package)
from .models import (FormulationDraft, IdentityPackageDraft, IdentityPackageReview, IdentityPackageRevision,
                     IdentityProductDraft, IngredientDraft, IngredientRevision, FormulationRevision, ProductRevision)
from .test_identity import ALL, FORM, INGREDIENT, PACKAGE, PRODUCT, build, user
from .identity_test_utils import assert_blocked_by_backend

REASON = 'دلیل ساختگی برای بررسی و اصلاح بسته'


class IdentityWriteConflictTests(TransactionTestCase):
    def setUp(self):
        self.author = user('timeout-author', *ALL)
        self.actor = user('timeout-actor', *ALL)
        self.ingredient, self.part, self.form, self.product, self.package = build(self.author)
        self.hashes = {'ingredient': digest(ingredient_snapshot(self.ingredient)),
                       'formulation': digest(formulation_snapshot(self.form)),
                       'product': digest(product_snapshot(self.product)),
                       'package': digest(package_snapshot(self.package))}

    def writer(self, kind, outer=False):
        close_old_connections()
        try:
            actor = get_user_model().objects.get(pk=self.actor.pk)
            operations = {
                'create_formulation': lambda: create_formulation(actor=actor, data=FORM, components=[self.part]),
                'create_product': lambda: create_product(actor=actor, data=PRODUCT, formulation_id=self.form.pk),
                'create_package': lambda: create_package(actor=actor, data=PACKAGE, product_id=self.product.pk),
                'revise_ingredient': lambda: revise_identity(actor=actor, kind='ingredient', parent_id=self.ingredient.pk,
                    data={**INGREDIENT, 'name_fa': 'ماده اصلاحی ساختگی'}, change_reason=REASON,
                    expected_graph_hash=self.hashes['ingredient']),
                'revise_formulation': lambda: revise_identity(actor=actor, kind='formulation', parent_id=self.form.pk,
                    data={**FORM, 'name': 'فرمول اصلاحی ساختگی'}, components=[self.part], change_reason=REASON,
                    expected_graph_hash=self.hashes['formulation']),
                'revise_product': lambda: revise_identity(actor=actor, kind='product', parent_id=self.product.pk,
                    data={**PRODUCT, 'name': 'فرآورده اصلاحی ساختگی'}, change_reason=REASON,
                    expected_graph_hash=self.hashes['product']),
                'revise_package': lambda: revise_package(actor=actor, parent_id=self.package.pk,
                    data={**PACKAGE, 'quantity': Decimal('20')}, change_reason=REASON, expected_review=0,
                    expected_graph_hash=self.hashes['package']),
                'review_package': lambda: review_package(actor=actor, package_id=self.package.pk, decision='defer',
                    reason=REASON, expected_review=0, expected_graph_hash=self.hashes['package']),
            }
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '300ms'")
                cursor.execute("SET statement_timeout = '8s'")
            if outer:
                with transaction.atomic():
                    try:
                        operations[kind]()
                    except IdentityConflict as exc:
                        # The failed inner savepoint must not poison the enclosing transaction.
                        return str(exc), IngredientDraft.objects.count()
                    raise AssertionError('Expected a conflict')
            return operations[kind]()
        finally:
            connection.close()

    def test_selected_writers_translate_actual_lock_timeout_without_writes(self):
        locks = [('create_formulation', IngredientDraft, self.ingredient.pk),
                 ('create_product', FormulationDraft, self.form.pk),
                 ('create_package', IdentityProductDraft, self.product.pk),
                 ('revise_ingredient', IngredientDraft, self.ingredient.pk),
                 ('revise_formulation', FormulationDraft, self.form.pk),
                 ('revise_product', IdentityProductDraft, self.product.pk),
                 ('revise_package', IdentityPackageDraft, self.package.pk),
                 ('review_package', IdentityPackageDraft, self.package.pk)]
        models = (IngredientDraft, FormulationDraft, IdentityProductDraft, IdentityPackageDraft,
                  IngredientRevision, FormulationRevision, ProductRevision, IdentityPackageRevision, IdentityPackageReview)
        before = tuple(model.objects.count() for model in models)
        for kind, model, pk in locks:
            with self.subTest(kind=kind):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with transaction.atomic():
                        model.objects.select_for_update().get(pk=pk)
                        future = pool.submit(self.writer, kind)
                        with self.assertRaises(IdentityConflict):
                            future.result(timeout=10)
                self.assertEqual(tuple(model.objects.count() for model in models), before)

    def test_timeout_rolls_back_inner_savepoint_and_outer_transaction_remains_usable(self):
        with ThreadPoolExecutor(max_workers=1) as pool:
            with transaction.atomic():
                IdentityPackageDraft.objects.select_for_update().get(pk=self.package.pk)
                message, count = pool.submit(self.writer, 'review_package', True).result(timeout=10)
                self.assertTrue(message)
                self.assertEqual(count, 1)
        self.assertFalse(IdentityPackageReview.objects.exists())

    def test_unknown_database_error_is_not_misreported_as_conflict(self):
        failure = DatabaseError('unexpected synthetic database failure')
        with patch('catalog.identity._lock_formulation_components', side_effect=failure):
            with self.assertRaises(DatabaseError) as result:
                create_product(actor=self.actor, data=PRODUCT, formulation_id=self.form.pk)
        self.assertIs(result.exception, failure)
        self.assertEqual(IdentityProductDraft.objects.count(), 1)

    def test_selected_sqlstates_translate_only_after_rollback(self):
        class DriverFailure(Exception):
            def __init__(self, code):
                self.sqlstate = code
        for code in ('55P03', '40P01', '40001'):
            with self.subTest(code=code):
                def fail_after_write(_form):
                    IngredientDraft.objects.filter(pk=self.ingredient.pk).update(name_fa='تغییر موقتی ساختگی')
                    try:
                        raise DriverFailure(code)
                    except DriverFailure as exc:
                        raise DatabaseError('synthetic database detail') from exc
                with patch('catalog.identity._lock_formulation_components', side_effect=fail_after_write):
                    with self.assertRaises(IdentityConflict) as raised:
                        create_product(actor=self.actor, data=PRODUCT, formulation_id=self.form.pk)
                self.assertNotIn('synthetic database detail', str(raised.exception))
                self.assertEqual(IngredientDraft.objects.get(pk=self.ingredient.pk).name_fa, self.ingredient.name_fa)
                self.assertEqual(IdentityProductDraft.objects.count(), 1)

    def test_other_sqlstate_is_not_translated(self):
        class DriverFailure(Exception):
            sqlstate = '57014'  # Statement cancellation is not necessarily a lock conflict.
        def fail(_form):
            try:
                raise DriverFailure('synthetic cancellation')
            except DriverFailure as exc:
                raise DatabaseError('synthetic cancellation') from exc
        with patch('catalog.identity._lock_formulation_components', side_effect=fail):
            with self.assertRaises(DatabaseError):
                create_product(actor=self.actor, data=PRODUCT, formulation_id=self.form.pk)

    def test_private_http_writers_report_lock_timeout_as_conflict(self):
        client = Client()
        client.force_login(self.actor)
        cases = [
            ('create_formulation', IngredientDraft, self.ingredient.pk,
             reverse('staff_identity_create', args=['formulation']),
             {**FORM, 'synthetic_ack': 'on', 'parts-TOTAL_FORMS': '5', 'parts-INITIAL_FORMS': '0',
              **{f'parts-0-{key}': str(value) for key, value in self.part.items()}}),
            ('create_product', FormulationDraft, self.form.pk, reverse('staff_identity_create', args=['product']),
             {**PRODUCT, 'formulation_id': self.form.pk, 'synthetic_ack': 'on'}),
            ('create_package', IdentityProductDraft, self.product.pk, reverse('staff_identity_create', args=['package']),
             {**PACKAGE, 'product_id': self.product.pk, 'synthetic_ack': 'on'}),
            ('revise_ingredient', IngredientDraft, self.ingredient.pk,
             reverse('staff_identity_revise_component', args=['ingredient', self.ingredient.pk]),
             {**INGREDIENT, 'name_fa': 'ماده اصلاحی ساختگی', 'synthetic_ack': 'on', 'change_reason': REASON,
              'expected_graph_hash': self.hashes['ingredient']}),
            ('revise_formulation', FormulationDraft, self.form.pk,
             reverse('staff_identity_revise_component', args=['formulation', self.form.pk]),
             {**FORM, 'name': 'فرمول اصلاحی ساختگی', 'synthetic_ack': 'on', 'change_reason': REASON,
              'expected_graph_hash': self.hashes['formulation'], 'parts-TOTAL_FORMS': '5', 'parts-INITIAL_FORMS': '1',
              **{f'parts-0-{key}': str(value) for key, value in self.part.items()}}),
            ('revise_product', IdentityProductDraft, self.product.pk,
             reverse('staff_identity_revise_component', args=['product', self.product.pk]),
             {**PRODUCT, 'name': 'فرآورده اصلاحی ساختگی', 'synthetic_ack': 'on', 'change_reason': REASON,
              'expected_graph_hash': self.hashes['product']}),
            ('revise_package', IdentityPackageDraft, self.package.pk,
             reverse('staff_identity_revise', args=[self.package.pk]),
             {**PACKAGE, 'quantity': '20', 'synthetic_ack': 'on', 'change_reason': REASON,
              'expected_review': 0, 'expected_graph_hash': self.hashes['package']}),
            ('review_package', IdentityPackageDraft, self.package.pk,
             reverse('staff_identity_review', args=[self.package.pk]),
             {'decision': 'defer', 'reason': REASON, 'expected_review': 0, 'expected_graph_hash': self.hashes['package']}),
        ]
        def post(path, payload):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '300ms'")
                    cursor.execute("SET statement_timeout = '8s'")
                return client.post(path, payload)
            finally:
                connection.close()
        for kind, model, pk, path, payload in cases:
            with self.subTest(kind=kind):
                with ThreadPoolExecutor(max_workers=1) as pool:
                    with transaction.atomic():
                        model.objects.select_for_update().get(pk=pk)
                        response = pool.submit(post, path, payload).result(timeout=10)
                self.assertEqual(response.status_code, 409, response.content.decode())
                self.assertIn('no-store', response['Cache-Control'])
                self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
                self.assertEqual(response['Referrer-Policy'], 'same-origin')
                self.assertNotContains(response, 'canceling statement', status_code=409)
        self.assertFalse(IdentityPackageReview.objects.exists())
        self.assertFalse(IdentityPackageRevision.objects.exists())
        self.assertFalse(IngredientRevision.objects.exists())
        self.assertFalse(FormulationRevision.objects.exists())
        self.assertFalse(ProductRevision.objects.exists())

    def test_actual_postgresql_deadlock_is_reported_as_conflict(self):
        """Arrange the service wait first so its backend detects this selected cycle."""
        from .identity import _lock_latest_package_review
        latest = review_package(actor=self.actor, package_id=self.package.pk, decision='defer', reason=REASON,
            expected_review=0, expected_graph_hash=self.hashes['package'])
        row_locked, service_waiting, start_cycle = Event(), Event(), Event()
        manual_pid, service_pid = Queue(), Queue()
        def manual_worker():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                        cursor.execute("SET LOCAL statement_timeout = '8s'")
                        cursor.execute('SELECT pg_backend_pid()')
                        manual_pid.put(cursor.fetchone()[0])
                    IdentityPackageReview.objects.select_for_update().get(pk=latest.pk)
                    row_locked.set()
                    if not start_cycle.wait(6): raise TimeoutError('Cycle not started')
                    IdentityPackageDraft.objects.select_for_update().get(pk=self.package.pk)
            finally:
                connection.close()
        def signal(package):
            service_waiting.set()
            return _lock_latest_package_review(package)
        def service_worker():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '8s'")
                    cursor.execute('SELECT pg_backend_pid()')
                    service_pid.put(cursor.fetchone()[0])
                actor = get_user_model().objects.get(pk=self.actor.pk)
                return review_package(actor=actor, package_id=self.package.pk, decision='defer', reason=REASON,
                    expected_review=latest.pk, expected_graph_hash=self.hashes['package'])
            finally:
                connection.close()
        with patch('catalog.identity._lock_latest_package_review', side_effect=signal):
            with ThreadPoolExecutor(max_workers=2) as pool:
                manual = pool.submit(manual_worker)
                try:
                    self.assertTrue(row_locked.wait(5))
                    service = pool.submit(service_worker)
                    self.assertTrue(service_waiting.wait(5))
                    assert_blocked_by_backend(self, service_pid.get(timeout=5), manual_pid.get(timeout=5))
                    start_cycle.set()
                    with self.assertRaises(IdentityConflict) as raised:
                        service.result(timeout=10)
                    db_error = raised.exception.__cause__
                    driver_error = db_error.__cause__
                    self.assertEqual(getattr(driver_error, 'sqlstate', None) or getattr(driver_error, 'pgcode', None), '40P01')
                    manual.result(timeout=10)
                finally:
                    start_cycle.set()
        self.assertEqual(IdentityPackageReview.objects.count(), 1)

    def test_actual_serialization_failure_is_reported_inside_writer_boundary(self):
        ready, resume = Event(), Event()
        def worker():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                        cursor.execute("SET LOCAL statement_timeout = '8s'")
                    IdentityPackageDraft.objects.get(pk=self.package.pk)
                    ready.set()
                    if not resume.wait(6): raise TimeoutError('Serialization test did not resume')
                    try:
                        review_package(actor=actor, package_id=self.package.pk, decision='defer', reason=REASON,
                            expected_review=0, expected_graph_hash=self.hashes['package'])
                    except IdentityConflict as exc:
                        driver = exc.__cause__.__cause__
                        code = getattr(driver, 'sqlstate', None) or getattr(driver, 'pgcode', None)
                        transaction.set_rollback(True)  # Restart the entire enclosing transaction, not just the write.
                        return code
                    raise AssertionError('Expected serialization conflict')
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            try:
                self.assertTrue(ready.wait(5))
                IdentityPackageDraft.objects.filter(pk=self.package.pk).update(description='تغییر هم‌زمان ساختگی')
            finally:
                resume.set()
            self.assertEqual(future.result(timeout=10), '40001')
        self.assertFalse(IdentityPackageReview.objects.exists())
