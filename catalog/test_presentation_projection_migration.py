"""Historical presentation projection upgrade on a disposable test database only."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class PresentationProjectionMigrationTests(TransactionTestCase):
    before = [('catalog', '0001_initial')]
    after = [('catalog', '0002_productpresentation_irc_normalized')]

    def setUp(self):
        super().setUp()
        # This test rolls back schema; restore all leaves even when setup fails.
        self.addCleanup(self.restore_graph)
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        apps = executor.loader.project_state(self.before).apps
        Product = apps.get_model('catalog', 'ProductPresentation')
        self.expected = {}
        examples = [
            ('۰۰۱۲۳۴', '001234'),
            (' ك\u200cي  ۱۲ ', 'ک ی 12'),
            ('ﬃ' * 40, ''),  # NFKC expansion must not be truncated to a false match.
            ('', ''),
        ]
        for number, (raw, normalized) in enumerate(examples):
            item = Product.objects.create(
                name_fa=f'ساختگی {number}', name_en='Synthetic', manufacturer='Synthetic',
                strength='1 mg', dosage_form='tablet', package_description='box',
                irc=raw, source_name='Synthetic', source_url='https://example.org',
                search_text=f'legacy projection {number}', published=bool(number % 2),
            )
            self.expected[item.pk] = (Product.objects.values().get(pk=item.pk), normalized)
        executor = MigrationExecutor(connection)
        executor.migrate(self.after)
        self.apps = executor.loader.project_state(self.after).apps

    def restore_graph(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_legacy_fields_survive_and_projection_is_backfilled_without_truncation(self):
        Product = self.apps.get_model('catalog', 'ProductPresentation')
        for pk, (before, normalized) in self.expected.items():
            with self.subTest(pk=pk):
                after = Product.objects.values().get(pk=pk)
                self.assertEqual(after.pop('irc_normalized'), normalized)
                self.assertEqual(after, before)
        self.assertEqual(Product.objects.count(), len(self.expected))
