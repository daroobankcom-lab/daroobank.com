"""Verify the additive identity migration preserves pre-existing catalog data."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class IdentityMigrationTests(TransactionTestCase):
    migrate_from = [('catalog', '0004_productcandidate_irc_normalized')]
    migrate_to = [('catalog', '0005_formulationdraft_identityproductdraft_and_more')]

    def setUp(self):
        super().setUp()
        # Register before changing schema: unittest runs this even if setup fails.
        self.addCleanup(self.restore_migrations)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        user = apps.get_model('auth', 'User').objects.create(username='synthetic-migration-user', is_staff=True)
        presentation = apps.get_model('catalog', 'ProductPresentation').objects.create(
            name_fa='رکورد ساختگی', name_en='', manufacturer='سازنده', strength='۱', dosage_form='قرص',
            package_description='بسته', irc='۰۰۱', irc_normalized='001', source_name='منبع ساختگی',
            source_url='https://example.org/source', search_text='رکورد ساختگی', published=False)
        candidate = apps.get_model('catalog', 'ProductCandidate').objects.create(
            source_name='منبع ساختگی', source_url='https://example.org/source', source_record_id='synthetic-1',
            source_fields={'irc': '۰۰۱', 'name_fa': 'رکورد ساختگی'}, irc_normalized='001',
            payload_sha256='a' * 64, staged_by_id=user.pk, source_rights_attested=True)
        review = apps.get_model('catalog', 'ProductCandidateReview').objects.create(
            candidate_id=candidate.pk, reviewer_id=user.pk, decision='defer', reason='بررسی ساختگی پیش از مهاجرت',
            candidate_payload_sha256='a' * 64, review_snapshot={'synthetic': True})
        self.ids = user.pk, presentation.pk, candidate.pk, review.pk
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def restore_migrations(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_upgrade_preserves_existing_catalog_and_starts_empty(self):
        user_id, presentation_id, candidate_id, review_id = self.ids
        user = self.apps.get_model('auth', 'User').objects.get(pk=user_id)
        self.assertEqual(user.username, 'synthetic-migration-user')
        presentation = self.apps.get_model('catalog', 'ProductPresentation').objects.get(pk=presentation_id)
        self.assertEqual((presentation.name_fa, presentation.irc, presentation.irc_normalized, presentation.published),
                         ('رکورد ساختگی', '۰۰۱', '001', False))
        candidate = self.apps.get_model('catalog', 'ProductCandidate').objects.get(pk=candidate_id)
        self.assertEqual((candidate.staged_by_id, candidate.irc_normalized, candidate.source_fields['irc']),
                         (user_id, '001', '۰۰۱'))
        review = self.apps.get_model('catalog', 'ProductCandidateReview').objects.get(pk=review_id)
        self.assertEqual((review.candidate_id, review.reviewer_id, review.review_snapshot),
                         (candidate_id, user_id, {'synthetic': True}))
        for model in ('IngredientDraft', 'FormulationDraft', 'FormulationComponent',
                      'IdentityProductDraft', 'IdentityPackageDraft', 'IdentityPackageReview'):
            self.assertFalse(self.apps.get_model('catalog', model).objects.exists())
