"""Synthetic PostgreSQL migration check for pre-existing clinical draft history."""
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ClinicalReferenceMigrationTests(TransactionTestCase):
    migrate_from = [('clinical', '0001_initial')]
    migrate_to = [('clinical', '0002_clinicalreferenceassertion')]

    def setUp(self):
        super().setUp()
        self.addCleanup(self.restore_migrations)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps
        User = old_apps.get_model('auth', 'User')
        author = User.objects.create(username='synthetic-reference-author')
        reviewer = User.objects.create(username='synthetic-reference-reviewer')
        Draft = old_apps.get_model('clinical', 'ClinicalDraft')
        Review = old_apps.get_model('clinical', 'ClinicalDraftReview')
        common = dict(subject='موضوع فرضی', audience='patient', title='عنوان فرضی',
                      statement='متن ساختگی آزمایش.', reference_title='منبع ساختگی',
                      reference_url='https://example.org/synthetic', reference_location='بخش آزمایشی',
                      reference_author='', reference_version='', author_id=author.pk)
        self.parent = Draft.objects.create(**common, payload_sha256='a' * 64)
        self.child = Draft.objects.create(**common, payload_sha256='b' * 64, parent_id=self.parent.pk,
                                          parent_payload_sha256='a' * 64, change_reason='اصلاح ساختگی آزمایش')
        self.review = Review.objects.create(draft_id=self.parent.pk, reviewer_id=reviewer.pk, decision='defer',
            reason='بازبینی ساختگی آزمایش', draft_payload_sha256='a' * 64,
            review_snapshot={'legacy_marker': 'synthetic'})
        self.before_drafts = {r['id']: r for r in Draft.objects.values().order_by('id')}
        self.before_review = Review.objects.values().get(pk=self.review.pk)
        self.author_id = author.pk
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def restore_migrations(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_draft_chain_and_review_remain_unchanged_without_backfill(self):
        Draft = self.apps.get_model('clinical', 'ClinicalDraft')
        Review = self.apps.get_model('clinical', 'ClinicalDraftReview')
        Reference = self.apps.get_model('clinical', 'ClinicalReferenceAssertion')
        self.assertEqual({r['id']: r for r in Draft.objects.values().order_by('id')}, self.before_drafts)
        self.assertEqual(Review.objects.values().get(pk=self.review.pk), self.before_review)
        self.assertEqual(Draft.objects.get(pk=self.child.pk).parent_id, self.parent.pk)
        self.assertEqual(Reference.objects.count(), 0)

    def test_new_reference_relation_constraint_rejects_unrecognized_value(self):
        Reference = self.apps.get_model('clinical', 'ClinicalReferenceAssertion')
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reference.objects.create(draft_id=self.parent.pk, recorded_by_id=self.author_id,
                draft_payload_sha256='a' * 64, reference_title='مرجع ساختگی',
                reference_url='https://example.org/synthetic', reference_location='بخش آزمایشی',
                reference_author='', reference_version='', relation='invalid', payload_sha256='c' * 64)
        self.assertFalse(Reference.objects.exists())
        with connection.cursor() as cursor:
            constraints = connection.introspection.get_constraints(cursor, Reference._meta.db_table)
        self.assertIn('clinical_reference_valid_relation', constraints)
        self.assertIn('unique_clinical_reference_assertion', constraints)
