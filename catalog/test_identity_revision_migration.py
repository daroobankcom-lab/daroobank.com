"""Exercise the additive revision migration with pre-existing identity records."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class IdentityRevisionMigrationTests(TransactionTestCase):
    migrate_from = [('catalog', '0005_formulationdraft_identityproductdraft_and_more')]
    migrate_to = [('catalog', '0006_identitypackagerevision')]

    def setUp(self):
        super().setUp()
        # Register before changing schema: unittest runs this even if setup fails.
        self.addCleanup(self.restore_migrations)
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        apps = executor.loader.project_state(self.migrate_from).apps
        user = apps.get_model('auth', 'User').objects.create(username='revision-migration-synthetic', is_staff=True)
        common = {'source_name': 'منبع فرضی', 'source_url': 'https://example.org/source',
                  'recorded_by_id': user.pk, 'payload_sha256': 'a' * 64}
        ingredient = apps.get_model('catalog', 'IngredientDraft').objects.create(name_fa='ماده فرضی', **common)
        form = apps.get_model('catalog', 'FormulationDraft').objects.create(name='فرمول فرضی', dosage_form='قرص', route='خوراکی', **common)
        component = apps.get_model('catalog', 'FormulationComponent').objects.create(formulation_id=form.pk, ingredient_id=ingredient.pk,
            ingredient_sha256='a'*64, ordinal=1, numerator='2.5', numerator_unit='mg', denominator='1', denominator_unit='tablet')
        product = apps.get_model('catalog', 'IdentityProductDraft').objects.create(formulation_id=form.pk,
            formulation_sha256='a'*64, name='فرآورده فرضی', brand='', manufacturer='سازنده', **common)
        package = apps.get_model('catalog', 'IdentityPackageDraft').objects.create(product_id=product.pk,
            product_sha256='a'*64, description='بسته فرضی', quantity='10', quantity_unit='عدد', irc='001', **common)
        review = apps.get_model('catalog', 'IdentityPackageReview').objects.create(package_id=package.pk, reviewer_id=user.pk,
            decision='defer', reason='بازبینی ساختگی قبل از مهاجرت', graph_sha256='b'*64, graph_snapshot={'old': 'snapshot'})
        self.ids = user.pk, ingredient.pk, form.pk, component.pk, product.pk, package.pk, review.pk
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def restore_migrations(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_chain_and_review_preserved_without_backfill(self):
        user, ingredient, form, component, product, package, review = self.ids
        get = lambda model, pk: self.apps.get_model('catalog', model).objects.get(pk=pk)
        self.assertEqual(get('IngredientDraft', ingredient).recorded_by_id, user)
        self.assertEqual(get('FormulationComponent', component).formulation_id, form)
        self.assertEqual(get('FormulationComponent', component).ingredient_id, ingredient)
        self.assertEqual(get('IdentityProductDraft', product).formulation_id, form)
        self.assertEqual(get('IdentityPackageDraft', package).product_id, product)
        self.assertEqual(get('IdentityPackageDraft', package).irc, '001')
        self.assertEqual(get('IdentityPackageReview', review).package_id, package)
        self.assertEqual(get('IdentityPackageReview', review).graph_snapshot, {'old': 'snapshot'})
        self.assertFalse(self.apps.get_model('catalog', 'IdentityPackageRevision').objects.exists())
