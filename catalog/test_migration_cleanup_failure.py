"""Failed historical test setups must restore the disposable test schema."""
import unittest
from unittest.mock import patch

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.recorder import MigrationRecorder
from django.test import TransactionTestCase

from . import (test_candidate_migration, test_identity_component_revision_migration,
               test_identity_migration, test_identity_revision_migration, test_published_date_migration)


class HistoricalMigrationCleanupTests(TransactionTestCase):
    def restore_graph(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_setup_failure_restores_graph_before_django_flush(self):
        self.addCleanup(self.restore_graph)
        examples = (
            (test_candidate_migration, test_candidate_migration.CandidateIndexMigrationTests),
            (test_identity_migration, test_identity_migration.IdentityMigrationTests),
            (test_identity_revision_migration, test_identity_revision_migration.IdentityRevisionMigrationTests),
            (test_identity_component_revision_migration,
             test_identity_component_revision_migration.ComponentRevisionMigrationTests),
            (test_published_date_migration, test_published_date_migration.PublishedDateMigrationTests),
        )
        for module, base in examples:
            with self.subTest(test_class=base.__name__):
                try:
                    self.check_failed_setup(module, base)
                finally:
                    self.restore_graph()

    def test_invalid_fixture_inserted_before_setup_failure_is_cleaned_for_graph_restore(self):
        self.addCleanup(self.restore_graph)
        observed = []

        class Probe(test_published_date_migration.PublishedDateMigrationTests):
            def setUp(self):
                super().setUp()
                self.fixture(published=True, verified_at=None)
                raise RuntimeError('synthetic failure after invalid fixture insert')

            def _post_teardown(self):
                applied = MigrationRecorder(connection).applied_migrations()
                leaves = MigrationExecutor(connection).loader.graph.leaf_nodes()
                observed.append(all(node in applied for node in leaves))
                super()._post_teardown()

        result = unittest.TestResult()
        Probe('test_valid_legacy_records_survive_unchanged')(result)
        self.assertEqual(len(result.errors), 1, result.errors)
        self.assertIn('synthetic failure after invalid fixture insert', result.errors[0][1])
        self.assertFalse(result.failures)
        self.assertEqual(observed, [True])

    def check_failed_setup(self, module, base):
        observed = []
        real_executor = MigrationExecutor
        executor_calls = 0

        def fail_first_migration_after_rollback(*args, **kwargs):
            nonlocal executor_calls
            executor_calls += 1
            executor = real_executor(*args, **kwargs)
            if executor_calls == 1:
                migrate = executor.migrate

                def fail_after_rollback(targets):
                    migrate(targets)
                    raise RuntimeError('synthetic failure after migration rollback')
                executor.migrate = fail_after_rollback
            return executor

        class Probe(base):
            def _post_teardown(self):
                applied = MigrationRecorder(connection).applied_migrations()
                leaf_nodes = real_executor(connection).loader.graph.leaf_nodes()
                observed.append(all(node in applied for node in leaf_nodes))
                super()._post_teardown()

        result = unittest.TestResult()
        method = unittest.TestLoader().getTestCaseNames(base)[0]
        with patch(f'{module.__name__}.MigrationExecutor', side_effect=fail_first_migration_after_rollback):
            Probe(method)(result)
        self.assertEqual(len(result.errors), 1, result.errors)
        self.assertIn('synthetic failure after migration rollback', result.errors[0][1])
        self.assertFalse(result.failures)
        self.assertEqual(observed, [True], 'Schema graph was not restored before Django flush')
        self.assertGreaterEqual(executor_calls, 2)
