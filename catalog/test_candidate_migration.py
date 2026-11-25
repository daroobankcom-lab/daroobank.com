from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class CandidateIndexMigrationTests(TransactionTestCase):
    """Exercise the upgrade against historical models with preexisting data."""
    migrate_from = [('catalog', '0003_productcandidate_productcandidatereview_and_more')]
    migrate_to = [('catalog', '0004_productcandidate_irc_normalized')]

    def setUp(self):
        super().setUp()
        # Register before changing schema: unittest runs this even if setup fails.
        self.addCleanup(self.restore_migrations)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        User = old_apps.get_model('auth', 'User')
        Candidate = old_apps.get_model('catalog', 'ProductCandidate')
        user = User.objects.create(username='migration-synthetic', is_staff=True)
        self.ids = []
        for i, fields in enumerate([{'irc': '۰۰۱۲۳۴'}, {'irc': 'ﬃ' * 40}, {'irc': None}, []]):
            item = Candidate.objects.create(source_name='synthetic', source_url='https://example.org',
                source_record_id=f'synthetic-{i}', source_fields=fields, payload_sha256='a' * 64,
                staged_by_id=user.pk, source_rights_attested=True)
            self.ids.append(item.pk)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.new_apps = executor.loader.project_state(self.migrate_to).apps

    def restore_migrations(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_rows_are_backfilled_and_invalid_inputs_fail_closed(self):
        Candidate = self.new_apps.get_model('catalog', 'ProductCandidate')
        values = [Candidate.objects.get(pk=pk).irc_normalized for pk in self.ids]
        self.assertEqual(values, ['001234', '', '', ''])
