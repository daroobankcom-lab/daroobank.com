"""Selected latest-review races with synthetic PostgreSQL data only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from queue import Queue
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import DatabaseError, close_old_connections, connection, transaction
from django.db.transaction import TransactionManagementError
from django.test import TransactionTestCase

from .identity import IdentityConflict, digest, package_snapshot, review_package, revise_package
from .models import IdentityPackageDraft, IdentityPackageReview, IdentityPackageRevision
from .identity_test_utils import assert_blocked_by_current_transaction, publish_backend_pid
from .test_identity import ALL, PACKAGE, build, user

REASON = 'دلیل ساختگی برای بررسی و اصلاح بسته'


class IdentityLatestReviewLockTests(TransactionTestCase):
    def setUp(self):
        self.author = user('latest-lock-author', *ALL)
        self.actor = user('latest-lock-actor', *ALL)
        self.package = build(self.author)[-1]
        self.graph_hash = digest(package_snapshot(self.package))
        self.latest = review_package(actor=self.actor, package_id=self.package.pk, decision='defer', reason=REASON,
                                     expected_review=0, expected_graph_hash=self.graph_hash)

    @contextmanager
    def lock_timeout(self):
        with self.assertRaises(DatabaseError) as caught:
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '300ms'")
                yield
        cause = caught.exception.__cause__
        self.assertEqual(getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None), '55P03')

    def write(self, kind, pid_queue=None):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '12s'")
                publish_backend_pid(cursor, pid_queue)
            actor = get_user_model().objects.get(pk=self.actor.pk)
            if kind == 'review':
                return review_package(actor=actor, package_id=self.package.pk, decision='defer', reason=REASON,
                    expected_review=self.latest.pk, expected_graph_hash=self.graph_hash)
            return revise_package(actor=actor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                change_reason=REASON, expected_review=self.latest.pk, expected_graph_hash=self.graph_hash)
        finally:
            connection.close()

    def test_correction_holds_latest_row_while_using_it(self):
        from .identity import review_is_consistent
        ready, resume = Event(), Event()
        def pause(review, package_id):
            result = review_is_consistent(review, package_id)
            ready.set()
            if not resume.wait(8): raise TimeoutError('Writer did not resume')
            return result
        with patch('catalog.identity.review_is_consistent', side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.write, 'revision')
                try:
                    self.assertTrue(ready.wait(8))
                    with self.lock_timeout():
                        IdentityPackageReview.objects.filter(pk=self.latest.pk).update(reason='متن تغییریافته ساختگی')
                finally:
                    resume.set()
                self.assertIsNotNone(future.result(timeout=10))
        self.assertEqual(IdentityPackageReview.objects.filter(pk=self.latest.pk).update(reason='متن تغییریافته ساختگی'), 1)

    def test_latest_helper_requires_atomic_and_selects_only_latest(self):
        from django.test.utils import CaptureQueriesContext
        from .identity import _lock_latest_package_review
        with self.assertRaises(TransactionManagementError):
            _lock_latest_package_review(self.package)
        other_package = build(self.author)[-1]
        with transaction.atomic(), CaptureQueriesContext(connection) as captured:
            self.assertIsNone(_lock_latest_package_review(other_package))
            latest = _lock_latest_package_review(self.package)
        self.assertEqual(latest.pk, self.latest.pk)
        self.assertEqual(len(captured), 2)
        for query in captured:
            sql = query['sql'].upper()
            self.assertIn('FOR UPDATE', sql)
            self.assertIn('ORDER BY', sql)
            self.assertIn('LIMIT 1', sql)

    def test_review_and_correction_hold_latest_row_against_update_and_delete(self):
        from .identity import _lock_latest_package_review
        for kind in ('review', 'revision'):
            for operation in ('update', 'delete'):
                with self.subTest(kind=kind, operation=operation):
                    IdentityPackageReview.objects.exclude(pk=self.latest.pk).delete()
                    ready, resume = Event(), Event()
                    def pause(package):
                        latest = _lock_latest_package_review(package)
                        ready.set()
                        if not resume.wait(8): raise TimeoutError('Writer did not resume')
                        return latest
                    with patch('catalog.identity._lock_latest_package_review', side_effect=pause):
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            future = pool.submit(self.write, kind)
                            try:
                                self.assertTrue(ready.wait(8))
                                with self.lock_timeout():
                                    queryset = IdentityPackageReview.objects.filter(pk=self.latest.pk)
                                    if operation == 'update':
                                        queryset.update(reason='متن تغییریافته ساختگی')
                                    else:
                                        queryset.delete()
                            finally:
                                resume.set()
                            self.assertIsNotNone(future.result(timeout=10))
                    self.assertEqual(IdentityPackageReview.objects.filter(pk=self.latest.pk).update(reason=REASON), 1)

    def test_prior_corrupting_update_is_reread_by_correction_but_review_uses_only_id(self):
        from .identity import _lock_latest_package_review
        for kind in ('revision', 'review'):
            with self.subTest(kind=kind):
                waiting, pids = Event(), Queue()
                def signal(package):
                    waiting.set()
                    return _lock_latest_package_review(package)
                with patch('catalog.identity._lock_latest_package_review', side_effect=signal):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with transaction.atomic():
                            IdentityPackageReview.objects.filter(pk=self.latest.pk).update(reason='bad')
                            future = pool.submit(self.write, kind, pids)
                            self.assertTrue(waiting.wait(8))
                            assert_blocked_by_current_transaction(self, pids.get(timeout=5))
                            self.assertFalse(future.done())
                        if kind == 'revision':
                            with self.assertRaises(IdentityConflict):
                                future.result(timeout=10)
                            self.assertFalse(IdentityPackageRevision.objects.exists())
                            self.assertEqual(IdentityPackageDraft.objects.count(), 1)
                        else:
                            self.assertIsNotNone(future.result(timeout=10))
                IdentityPackageReview.objects.exclude(pk=self.latest.pk).delete()
                IdentityPackageReview.objects.filter(pk=self.latest.pk).update(reason=REASON)

    def test_prior_deletion_of_latest_review_conflicts(self):
        from .identity import _lock_latest_package_review
        for kind in ('revision', 'review'):
            with self.subTest(kind=kind):
                waiting, pids = Event(), Queue()
                def signal(package):
                    waiting.set()
                    return _lock_latest_package_review(package)
                with patch('catalog.identity._lock_latest_package_review', side_effect=signal):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with transaction.atomic():
                            IdentityPackageReview.objects.filter(pk=self.latest.pk).delete()
                            future = pool.submit(self.write, kind, pids)
                            self.assertTrue(waiting.wait(8))
                            assert_blocked_by_current_transaction(self, pids.get(timeout=5))
                            self.assertFalse(future.done())
                        with self.assertRaises(IdentityConflict):
                            future.result(timeout=10)
                self.assertFalse(IdentityPackageRevision.objects.exists())
                IdentityPackageReview.objects.bulk_create([self.latest])

    def test_latest_lock_persists_until_outer_transaction_finishes(self):
        ready, resume = Event(), Event()
        def worker():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                with transaction.atomic():
                    child = revise_package(actor=actor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                        change_reason=REASON, expected_review=self.latest.pk, expected_graph_hash=self.graph_hash)
                    ready.set()
                    if not resume.wait(8): raise TimeoutError('Outer transaction did not finish')
                return child
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(worker)
            try:
                self.assertTrue(ready.wait(8))
                with self.lock_timeout():
                    IdentityPackageReview.objects.filter(pk=self.latest.pk).update(reason='متن تغییریافته ساختگی')
            finally:
                resume.set()
            self.assertIsNotNone(future.result(timeout=10))
        self.assertEqual(IdentityPackageReview.objects.filter(pk=self.latest.pk).update(reason=REASON), 1)

    def test_deferred_review_insert_can_commit_after_correction(self):
        from .identity import _lock_latest_package_review
        checked, resume_writer, inserted, resume_inserter = Event(), Event(), Event(), Event()
        def pause(package):
            latest = _lock_latest_package_review(package)
            checked.set()
            if not resume_writer.wait(8): raise TimeoutError('Writer did not resume')
            return latest
        def insert_later():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL statement_timeout = '12s'")
                        cursor.execute('SET CONSTRAINTS ALL DEFERRED')
                    review = IdentityPackageReview.objects.create(package_id=self.package.pk, reviewer_id=self.actor.pk,
                        decision='defer', reason=REASON, graph_sha256=self.graph_hash,
                        graph_snapshot=self.latest.graph_snapshot)
                    inserted.set()
                    if not resume_inserter.wait(8): raise TimeoutError('Inserter did not resume')
                return review
            finally:
                connection.close()
        with patch('catalog.identity._lock_latest_package_review', side_effect=pause):
            with ThreadPoolExecutor(max_workers=2) as pool:
                writer = pool.submit(self.write, 'revision')
                try:
                    self.assertTrue(checked.wait(8))
                    inserter = pool.submit(insert_later)
                    self.assertTrue(inserted.wait(8))
                    resume_writer.set()
                    child = writer.result(timeout=10)
                    resume_inserter.set()
                    new_review = inserter.result(timeout=10)
                finally:
                    resume_writer.set()
                    resume_inserter.set()
        self.assertTrue(IdentityPackageRevision.objects.filter(child=child).exists())
        self.assertGreater(new_review.pk, self.latest.pk)
        self.assertEqual(IdentityPackageReview.objects.filter(package_id=self.package.pk).order_by('-pk').first().pk,
                         new_review.pk)

    def test_older_review_is_not_locked_by_correction(self):
        from .identity import _lock_latest_package_review
        older = self.latest
        newest = review_package(actor=self.actor, package_id=self.package.pk, decision='defer', reason=REASON,
            expected_review=older.pk, expected_graph_hash=self.graph_hash)
        self.latest = newest
        ready, resume = Event(), Event()
        def pause(package):
            latest = _lock_latest_package_review(package)
            ready.set()
            if not resume.wait(8): raise TimeoutError('Writer did not resume')
            return latest
        with patch('catalog.identity._lock_latest_package_review', side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.write, 'revision')
                try:
                    self.assertTrue(ready.wait(8))
                    with transaction.atomic():
                        with connection.cursor() as cursor:
                            cursor.execute("SET LOCAL lock_timeout = '300ms'")
                        self.assertEqual(IdentityPackageReview.objects.filter(pk=older.pk).update(reason='قدیمی ساختگی'), 1)
                finally:
                    resume.set()
                self.assertIsNotNone(future.result(timeout=10))

    def test_same_transaction_bypass_can_mutate_latest_after_lock(self):
        from .identity import _lock_latest_package_review
        def mutate(package):
            latest = _lock_latest_package_review(package)
            IdentityPackageReview.objects.filter(pk=latest.pk).update(reason='bad')
            return latest
        with patch('catalog.identity._lock_latest_package_review', side_effect=mutate):
            child = revise_package(actor=self.actor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                change_reason=REASON, expected_review=self.latest.pk, expected_graph_hash=self.graph_hash)
        self.assertTrue(IdentityPackageRevision.objects.filter(child=child).exists())
        self.assertEqual(IdentityPackageReview.objects.get(pk=self.latest.pk).reason, 'bad')

    def test_immediate_review_insert_waits_for_parent_lock(self):
        from .identity import _lock_latest_package_review
        ready, resume = Event(), Event()
        def pause(package):
            latest = _lock_latest_package_review(package)
            ready.set()
            if not resume.wait(8): raise TimeoutError('Writer did not resume')
            return latest
        with patch('catalog.identity._lock_latest_package_review', side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(self.write, 'revision')
                try:
                    self.assertTrue(ready.wait(8))
                    with self.lock_timeout():
                        with connection.cursor() as cursor:
                            cursor.execute('SET CONSTRAINTS ALL IMMEDIATE')
                        IdentityPackageReview.objects.create(package_id=self.package.pk, reviewer_id=self.actor.pk,
                            decision='defer', reason=REASON, graph_sha256=self.graph_hash,
                            graph_snapshot=self.latest.graph_snapshot)
                finally:
                    resume.set()
                self.assertIsNotNone(future.result(timeout=10))
        self.assertEqual(IdentityPackageReview.objects.count(), 1)

    def test_review_moved_to_another_package_before_lock_conflicts(self):
        from .identity import _lock_latest_package_review
        other = build(self.author)[-1]
        for kind in ('revision', 'review'):
            with self.subTest(kind=kind):
                waiting, pids = Event(), Queue()
                def signal(package):
                    waiting.set()
                    return _lock_latest_package_review(package)
                with patch('catalog.identity._lock_latest_package_review', side_effect=signal):
                    with ThreadPoolExecutor(max_workers=1) as pool:
                        with transaction.atomic():
                            IdentityPackageReview.objects.filter(pk=self.latest.pk).update(package_id=other.pk)
                            future = pool.submit(self.write, kind, pids)
                            self.assertTrue(waiting.wait(8))
                            assert_blocked_by_current_transaction(self, pids.get(timeout=5))
                        with self.assertRaises(IdentityConflict):
                            future.result(timeout=10)
                self.assertFalse(IdentityPackageRevision.objects.exists())
                IdentityPackageReview.objects.filter(pk=self.latest.pk).update(package_id=self.package.pk)

    def test_deferred_first_review_can_commit_after_zero_token_correction(self):
        from .identity import _lock_latest_package_review
        original_graph = self.latest.graph_snapshot
        IdentityPackageReview.objects.filter(pk=self.latest.pk).delete()
        checked, resume_writer, inserted, resume_insert = Event(), Event(), Event(), Event()
        def pause(package):
            latest = _lock_latest_package_review(package)
            self.assertIsNone(latest)
            checked.set()
            if not resume_writer.wait(8): raise TimeoutError('Writer did not resume')
            return latest
        def writer():
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actor.pk)
                return revise_package(actor=actor, parent_id=self.package.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                    change_reason=REASON, expected_review=0, expected_graph_hash=self.graph_hash)
            finally:
                connection.close()
        def insert_later():
            close_old_connections()
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL statement_timeout = '12s'")
                        cursor.execute('SET CONSTRAINTS ALL DEFERRED')
                    review = IdentityPackageReview.objects.create(package_id=self.package.pk, reviewer_id=self.actor.pk,
                        decision='defer', reason=REASON, graph_sha256=self.graph_hash, graph_snapshot=original_graph)
                    inserted.set()
                    if not resume_insert.wait(8): raise TimeoutError('Inserter did not resume')
                return review
            finally:
                connection.close()
        with patch('catalog.identity._lock_latest_package_review', side_effect=pause):
            with ThreadPoolExecutor(max_workers=2) as pool:
                writing = pool.submit(writer)
                try:
                    self.assertTrue(checked.wait(8))
                    inserting = pool.submit(insert_later)
                    self.assertTrue(inserted.wait(8))
                    resume_writer.set()
                    child = writing.result(timeout=10)
                    resume_insert.set()
                    review = inserting.result(timeout=10)
                finally:
                    resume_writer.set()
                    resume_insert.set()
        self.assertTrue(IdentityPackageRevision.objects.filter(child_id=child.pk).exists())
        self.assertEqual(IdentityPackageReview.objects.filter(package_id=self.package.pk).get().pk, review.pk)
