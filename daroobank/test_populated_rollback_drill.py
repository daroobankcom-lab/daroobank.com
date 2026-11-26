"""What a migration rollback does to a database that has data in it.

ADR 0216 measured the rollback *direction*: which migrations unapply, which tables disappear,
which foreign keys are left behind, and that a full rollback plus reapply reproduces the same
schema. Every one of those measurements ran against an empty database, and the record says so —
which means the question an operator actually has before a destructive step is still open: what
happens to the rows?

This drill answers it on a throwaway PostgreSQL database that the test populates itself, one row
or more in each of the 23 project tables plus one staff account, and then rolls back:

* rolling one app back destroys the rows of every table the cascade removes, and leaves a receipt
  whose items are gone — a history that is internally inconsistent rather than merely shorter;
* rolling everything back destroys every project row while the account that wrote them survives,
  because `auth_user` belongs to Django and no project migration touches it;
* reapplying the migrations returns an identical schema and **zero rows**: nothing in Django's
  rollback preserves contents, and the drill quantifies the loss rather than asserting it;
* the only thing that brings rows back is a copy taken before the rollback, and this drill
  round-trips one to show what such a copy has to contain, in which order it must be replayed, and
  which identity sequence has to be advanced before the restored table accepts a new row;
* a rollback attempted while a second session holds one row lock fails on the lock timeout and
  leaves the database **half undone**: the migrations that already committed stay undone and
  their rows stay destroyed, and migrating forward repairs the schema without restoring a row.

Everything here is synthetic and stays inside a database the test creates and drops. It is not a
backup, not a recovery objective, and not a staging plan; it is the measurement a staging plan has
to be written against.
"""
from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg
from django.contrib.auth import get_user_model
from django.db import DatabaseError, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone as django_timezone

from catalog.models import (FormulationComponent, FormulationDraft, FormulationRevision,
                            IdentityPackageDraft, IdentityPackageReview, IdentityPackageRevision,
                            IdentityProductDraft, IngredientDraft, IngredientRevision,
                            ProductCandidate, ProductCandidateReview, ProductPresentation,
                            ProductRevision)
from clinical.models import ClinicalDraft, ClinicalDraftReview, ClinicalReferenceAssertion
from ingestion.models import ImportReceipt, ImportReceiptItem
from pricing.models import PriceCandidate, PriceCandidateReview
from sources.models import SourceClaim, SourceClaimReview
from staff_security.models import StaffLoginWindow

from .test_migration_reversibility import (PROJECT_APPS, applied, foreign_keys, inspect, inventory,
                                           migrate, project_tables, rows, tables,
                                           throwaway_database)

ZERO = '0' * 64
ONE = '1' * 64
SOURCE = 'https://example.org/synthetic'
# Rows the drill creates, by table. Pinned so a change in the fixture is a deliberate act.
POPULATED = {
    'catalog_formulationcomponent': 1,
    'catalog_formulationdraft': 2,
    'catalog_formulationrevision': 1,
    'catalog_identitypackagedraft': 2,
    'catalog_identitypackagereview': 1,
    'catalog_identitypackagerevision': 1,
    'catalog_identityproductdraft': 2,
    'catalog_ingredientdraft': 2,
    'catalog_ingredientrevision': 1,
    'catalog_productcandidate': 1,
    'catalog_productcandidatereview': 1,
    'catalog_productpresentation': 2,
    'catalog_productrevision': 1,
    'clinical_clinicaldraft': 1,
    'clinical_clinicaldraftreview': 1,
    'clinical_clinicalreferenceassertion': 1,
    'ingestion_importreceipt': 1,
    'ingestion_importreceiptitem': 2,
    'pricing_pricecandidate': 2,
    'pricing_pricecandidatereview': 1,
    'sources_sourceclaim': 1,
    'sources_sourceclaimreview': 1,
    'staff_security_staffloginwindow': 1,
}
CATALOG_CASCADE_TABLES = ('catalog_', 'pricing_', 'ingestion_importreceiptitem')
LOCK_TIMEOUT = '2s'


def row_counts(alias, names=None):
    """`{table: rows}` for every project table that currently exists."""
    existing = [name for app in PROJECT_APPS for name in project_tables(alias)[app]]
    counts = {}
    for name in sorted(names if names is not None else existing):
        if name in existing:
            counts[name] = rows(alias, f'SELECT count(*) FROM {name}')[0][0]
    return counts


def total(alias):
    return sum(row_counts(alias).values())


def staff_account(alias):
    account = get_user_model()(username='drill-staff', is_staff=True)
    account.set_password('synthetic-only')
    account.save(using=alias)
    return account


def populate(alias):
    """One row or more in every project table, plus one staff account that wrote them."""
    user = staff_account(alias)
    verified = datetime(2026, 1, 1, tzinfo=timezone.utc)
    published = ProductPresentation.objects.using(alias).create(
        name_fa='محصول ساختگی', name_en='Synthetic', manufacturer='شرکت نمونه', strength='۵ میلی‌گرم',
        dosage_form='قرص', package_description='۱۰ عدد', irc='001234', source_name='منبع ساختگی',
        source_url=SOURCE, verified_at=verified, published=True)
    ProductPresentation.objects.using(alias).create(
        name_fa='محصول منتشرنشده', manufacturer='شرکت نمونه', strength='۵ میلی‌گرم', dosage_form='قرص',
        package_description='۱۰ عدد', irc='001235', source_name='منبع ساختگی',
        source_url='https://example.org/synthetic-2')

    candidate = ProductCandidate.objects.using(alias).create(
        source_name='منبع ساختگی', source_url=SOURCE, source_record_id='product-1',
        source_fields={'name': 'synthetic'}, payload_sha256=ZERO, staged_by=user)
    ProductCandidateReview.objects.using(alias).create(
        candidate=candidate, reviewer=user, decision='defer', reason='synthetic drill',
        candidate_payload_sha256=ZERO, review_snapshot={'drill': True})

    ingredients = [IngredientDraft.objects.using(alias).create(
        source_name='منبع ساختگی', source_url=SOURCE, payload_sha256=ZERO, recorded_by=user,
        name_fa=f'ماده ساختگی {index}') for index in (1, 2)]
    formulations = [FormulationDraft.objects.using(alias).create(
        source_name='منبع ساختگی', source_url=SOURCE, payload_sha256=ZERO, recorded_by=user,
        name=f'فرمول ساختگی {index}', dosage_form='قرص', route='oral') for index in (1, 2)]
    FormulationComponent.objects.using(alias).create(
        formulation=formulations[0], ingredient=ingredients[0], ingredient_sha256=ZERO, ordinal=1,
        numerator=Decimal('1'), numerator_unit='mg', denominator=Decimal('1'), denominator_unit='tablet')

    products = [IdentityProductDraft.objects.using(alias).create(
        source_name='منبع ساختگی', source_url=SOURCE, payload_sha256=ZERO, recorded_by=user,
        formulation=formulation, formulation_sha256=ZERO, name=f'محصول هویتی {index}',
        manufacturer='شرکت نمونه') for index, formulation in enumerate(formulations, 1)]
    packages = [IdentityPackageDraft.objects.using(alias).create(
        source_name='منبع ساختگی', source_url=SOURCE, payload_sha256=ZERO, recorded_by=user,
        product=product, product_sha256=ZERO, description=f'بسته ساختگی {index}',
        quantity=Decimal('10'), quantity_unit='عدد') for index, product in enumerate(products, 1)]
    IdentityPackageReview.objects.using(alias).create(
        package=packages[0], reviewer=user, decision='defer', reason='synthetic drill',
        graph_sha256=ZERO, graph_snapshot={'drill': True})
    IdentityPackageRevision.objects.using(alias).create(
        parent=packages[0], child=packages[1], recorded_by=user, change_reason='synthetic drill',
        parent_graph_sha256=ZERO, child_graph_sha256=ONE, payload_sha256=ZERO)
    IngredientRevision.objects.using(alias).create(
        parent=ingredients[0], child=ingredients[1], recorded_by=user, change_reason='synthetic drill',
        parent_graph_sha256=ZERO, child_graph_sha256=ONE, payload_sha256=ZERO)
    FormulationRevision.objects.using(alias).create(
        parent=formulations[0], child=formulations[1], recorded_by=user, change_reason='synthetic drill',
        parent_graph_sha256=ZERO, child_graph_sha256=ONE, payload_sha256=ZERO)
    ProductRevision.objects.using(alias).create(
        parent=products[0], child=products[1], recorded_by=user, change_reason='synthetic drill',
        parent_graph_sha256=ZERO, child_graph_sha256=ONE, payload_sha256=ZERO)

    prices = [PriceCandidate.objects.using(alias).create(
        source_name='منبع ساختگی', source_url=SOURCE, source_record_id=f'price-{index}',
        payload_sha256=ZERO, source_fields={'amount': '۱۰۰'}, original_amount='۱۰۰',
        original_currency='TOMAN', amount_rial=10000, price_category='official_consumer',
        unit='package', match_status='suggested', staged_by=stager, suggested_product=published)
        for index, stager in enumerate([user, None], 1)]
    PriceCandidateReview.objects.using(alias).create(
        candidate=prices[0], reviewer=user, decision='defer', reason='synthetic drill',
        candidate_payload_sha256=ZERO, review_snapshot={'drill': True})

    claim = SourceClaim.objects.using(alias).create(
        source_name='منبع ساختگی', source_url=SOURCE, owner='دارنده ساختگی',
        evidence_url='https://example.org/evidence', claims_collection=True,
        starts_on=date(2026, 1, 1), expires_on=date(2026, 12, 31),
        payload_sha256=ZERO, recorded_by=user)
    SourceClaimReview.objects.using(alias).create(
        claim=claim, reviewer=user, decision='defer', reason='synthetic drill',
        claim_payload_sha256=ZERO, review_snapshot={'drill': True})

    receipt = ImportReceipt.objects.using(alias).create(
        kind='price', source_name='منبع ساختگی', source_url=SOURCE, actor=user, rows=2, created=2,
        duplicates=0, suggested=2, ambiguous=0, unmatched=0)
    for index, price in enumerate(prices, 1):
        ImportReceiptItem.objects.using(alias).create(
            receipt=receipt, ordinal=index, source_record_id=price.source_record_id,
            match_status=price.match_status, payload_sha256=ZERO, was_created=True,
            price_candidate=price)

    draft = ClinicalDraft.objects.using(alias).create(
        subject='موضوع ساختگی', audience='professional', title='عنوان ساختگی',
        statement='متن ساختگی برای تمرین بازگشت.', reference_title='مرجع ساختگی',
        reference_url='https://example.org/reference', reference_location='صفحه ۱',
        payload_sha256=ZERO, author=user)
    ClinicalDraftReview.objects.using(alias).create(
        draft=draft, reviewer=user, decision='defer', reason='synthetic drill',
        draft_payload_sha256=ZERO, review_snapshot={'drill': True})
    ClinicalReferenceAssertion.objects.using(alias).create(
        draft=draft, draft_payload_sha256=ZERO, reference_title='مرجع دوم',
        reference_url='https://example.org/reference-2', reference_location='صفحه ۲',
        relation='supports', payload_sha256=ONE, recorded_by=user)

    StaffLoginWindow.objects.using(alias).create(
        client_key='a' * 64, started_at=django_timezone.now(), attempts=1)
    return user, published, candidate


def rollback_plan(alias, app):
    """The migrations `migrate <app> zero` would run, in order, as `(app, name)` labels."""
    executor = MigrationExecutor(connections[alias])
    executor.loader.build_graph()
    return [(migration.app_label, migration.name) for migration, backwards
            in executor.migration_plan([(app, None)]) if backwards]


def dump(alias, table):
    """`(column names, rows)` for one table, in column order, so a copy can be replayed."""
    with connections[alias].cursor() as cursor:
        cursor.execute(f'SELECT * FROM {table} ORDER BY id')
        return [column.name for column in cursor.description], cursor.fetchall()


def second_session(alias):
    """An independent PostgreSQL session on the same throwaway database."""
    settings_dict = connections[alias].settings_dict
    return psycopg.connect(host=settings_dict['HOST'], port=settings_dict['PORT'],
                           dbname=settings_dict['NAME'], user=settings_dict['USER'],
                           password=settings_dict['PASSWORD'], autocommit=False)


class PopulatedRollbackDrillTests(TransactionTestCase):
    def test_the_drill_populates_every_project_table(self):
        with throwaway_database() as alias:
            migrate(alias)
            populate(alias)
            counts = row_counts(alias)
            self.assertEqual(counts, POPULATED, 'the drill fixture no longer fills the schema it measures')
            self.assertEqual(len(counts), 23)
            self.assertEqual(total(alias), sum(POPULATED.values()))
            self.assertEqual(inspect(alias)['status'], 'no_selected_issues',
                             'the populated database does not match the models')

    def test_rolling_one_app_back_destroys_rows_and_orphans_a_receipt(self):
        with throwaway_database() as alias:
            migrate(alias)
            populate(alias)
            before = row_counts(alias)
            destroyed = sum(count for table, count in before.items()
                            if table.startswith(CATALOG_CASCADE_TABLES))
            self.assertEqual(len(applied(alias)), 31)

            migrate(alias, 'catalog', 'zero')

            after = row_counts(alias)
            self.assertEqual(len(applied(alias)), 20, 'the cascade ADR 0216 measures changed')
            gone = sorted(set(before) - set(after))
            self.assertEqual([name for name in gone if not name.startswith(CATALOG_CASCADE_TABLES)], [],
                             'a table outside the cascade disappeared')
            self.assertEqual(len(gone), 16, 'catalog, pricing and one ingestion table should be gone')
            self.assertEqual(sum(after.values()), sum(before.values()) - destroyed,
                             'rows outside the cascade were destroyed too')
            self.assertEqual(after['ingestion_importreceipt'], 1,
                             'the receipt survived')
            self.assertNotIn('ingestion_importreceiptitem', after,
                             "the receipt's items were dropped with the cascade")
            self.assertEqual(after['sources_sourceclaim'], 1)
            self.assertEqual(after['clinical_clinicaldraft'], 1)
            self.assertEqual(after['staff_security_staffloginwindow'], 1)
            self.assertEqual(len(tables(alias)), 16)
            self.assertEqual(len(foreign_keys(alias)), 17)
            self.assertEqual(inspect(alias)['status'], 'attention')

    def test_a_full_rollback_destroys_every_project_row_and_keeps_the_account(self):
        with throwaway_database() as alias:
            migrate(alias)
            user, _published, _candidate = populate(alias)
            before = total(alias)
            self.assertEqual(before, sum(POPULATED.values()))

            for app in reversed(PROJECT_APPS):
                migrate(alias, app, 'zero')

            self.assertEqual(row_counts(alias), {}, 'a project table survived the rollback')
            self.assertEqual(total(alias), 0)
            self.assertEqual(rows(alias, 'SELECT count(*) FROM auth_user')[0][0], 1,
                             'the account that wrote every row should outlive them')
            self.assertEqual(rows(alias, 'SELECT count(*) FROM auth_user WHERE id = %s' % user.pk)[0][0], 1)
            self.assertIn('django_session', tables(alias))

    def test_reapplying_returns_the_schema_and_no_rows(self):
        with throwaway_database() as alias:
            migrate(alias)
            populate(alias)
            first = inventory(alias)
            before = total(alias)

            for app in reversed(PROJECT_APPS):
                migrate(alias, app, 'zero')
            migrate(alias)

            self.assertEqual(inventory(alias), first, 'the schema did not come back identical')
            self.assertEqual(inspect(alias)['status'], 'no_selected_issues')
            self.assertEqual(row_counts(alias), {table: 0 for table in POPULATED},
                             'a table came back with rows in it')
            self.assertEqual(total(alias), 0, 'reapplying migrations restored data')
            self.assertEqual(before, sum(POPULATED.values()),
                             'the drill should quantify what was lost, and it lost nothing to count')

    def test_only_a_copy_taken_beforehand_brings_rows_back(self):
        with throwaway_database() as alias:
            migrate(alias)
            user, published, candidate = populate(alias)
            # What a backup has to hold for these three tables: every column, in insert order.
            order = ('catalog_productpresentation', 'catalog_productcandidate',
                     'catalog_productcandidatereview')
            copy = {table: dump(alias, table) for table in order}
            original = row_counts(alias, list(order))
            self.assertEqual(sum(original.values()), 4)

            for app in reversed(PROJECT_APPS):
                migrate(alias, app, 'zero')
            migrate(alias)
            self.assertEqual(row_counts(alias, list(order)), {table: 0 for table in order})

            # Replay in foreign-key order; the account still exists, so the actor columns resolve.
            for table in order:
                columns, values = copy[table]
                placeholders = ', '.join(['%s'] * len(columns))
                for row in values:
                    with connections[alias].cursor() as cursor:
                        cursor.execute(f'INSERT INTO {table} ({", ".join(columns)}) '
                                       f'VALUES ({placeholders})', row)
            self.assertEqual(row_counts(alias, list(order)), original,
                             'the copy did not reproduce the rows it held')
            self.assertEqual(rows(alias, 'SELECT count(*) FROM catalog_productcandidate '
                                         'WHERE staged_by_id = %s' % user.pk)[0][0], 1)
            self.assertEqual(ProductPresentation.objects.using(alias).get(pk=published.pk).name_fa,
                             'محصول ساختگی')
            self.assertEqual(ProductCandidate.objects.using(alias).get(pk=candidate.pk).source_record_id,
                             'product-1')

            # Restoring rows is not the whole procedure: the identity sequences still point at the
            # ids the copy reused, so the next insert collides until they are advanced.
            with self.assertRaises(DatabaseError):
                ProductPresentation.objects.using(alias).create(
                    name_fa='ردیف بعدی', manufacturer='شرکت نمونه', strength='۵ میلی‌گرم',
                    dosage_form='قرص', package_description='۱۰ عدد', source_name='منبع ساختگی',
                    source_url='https://example.org/synthetic-3')
            with connections[alias].cursor() as cursor:
                cursor.execute("SELECT setval(pg_get_serial_sequence('catalog_productpresentation', 'id'),"
                               " (SELECT max(id) FROM catalog_productpresentation))")
            ProductPresentation.objects.using(alias).create(
                name_fa='ردیف بعدی', manufacturer='شرکت نمونه', strength='۵ میلی‌گرم',
                dosage_form='قرص', package_description='۱۰ عدد', source_name='منبع ساختگی',
                source_url='https://example.org/synthetic-3')
            self.assertEqual(row_counts(alias, ['catalog_productpresentation'])['catalog_productpresentation'], 3)

    def test_a_blocked_rollback_leaves_the_database_half_undone(self):
        """One locked row stops the plan, and whatever it already undid stays undone."""
        with throwaway_database() as alias:
            migrate(alias)
            _user, published, _candidate = populate(alias)
            before = row_counts(alias)
            schema_before = inventory(alias)
            plan = rollback_plan(alias, 'catalog')
            self.assertEqual(len(plan), 11, 'the cascade ADR 0216 measured changed length')
            # The plan is not ordered by app: ingestion goes first, then pricing, then catalog.
            self.assertEqual(plan[:3], [('ingestion', '0002_importreceiptitem_importreceipt_'
                                                      'manifest_version_and_more'),
                                        ('pricing', '0002_alter_pricecandidate_options_and_more'),
                                        ('pricing', '0001_initial')])
            self.assertEqual(plan[-1], ('catalog', '0001_initial'))

            holder = second_session(alias)
            try:
                with holder.cursor() as cursor:
                    cursor.execute('SELECT id FROM catalog_productpresentation WHERE id = %s FOR UPDATE',
                                   (published.pk,))
                with connections[alias].cursor() as cursor:
                    cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
                with self.assertRaises(DatabaseError) as caught:
                    migrate(alias, 'catalog', 'zero')
                self.assertIn('lock timeout', str(caught.exception))
            finally:
                with connections[alias].cursor() as cursor:
                    cursor.execute('SET lock_timeout = 0')
                holder.rollback()
                holder.close()

            # Step one had already committed; step two died dropping a table whose foreign key
            # points at the locked row, because dropping a child table locks its parent too.
            self.assertEqual(len(applied(alias)), 30, 'a blocked rollback unapplied nothing')
            self.assertEqual(sorted(set(plan) - set(applied(alias))), [plan[0]],
                             'the blocked plan should have undone only its first migration')
            self.assertNotIn('ingestion_importreceiptitem', tables(alias))
            self.assertIn('catalog_productpresentation', tables(alias))
            self.assertEqual(len(tables(alias)), 31)
            self.assertEqual(len(foreign_keys(alias)), 47)
            after = row_counts(alias)
            self.assertEqual(sum(after.values()), sum(before.values()) - 2,
                             'the blocked rollback destroyed something other than the receipt items')
            self.assertEqual(after['catalog_productpresentation'], 2)
            self.assertEqual(after['pricing_pricecandidate'], 2)
            # The receipt survives, and its own counters now contradict the database.
            self.assertEqual(rows(alias, 'SELECT rows, created, duplicates FROM ingestion_importreceipt'),
                             [(2, 2, 0)])
            self.assertEqual(inspect(alias)['status'], 'attention',
                             'a half-rolled-back database still matches the models')
            self.assertNotEqual(inventory(alias), schema_before)

            # The same command completes once nothing holds the lock.
            migrate(alias, 'catalog', 'zero')
            self.assertEqual(len(applied(alias)), 20)
            self.assertEqual(len(tables(alias)), 16)

    def test_migrating_forward_repairs_the_schema_and_not_the_rows(self):
        with throwaway_database() as alias:
            migrate(alias)
            _user, published, _candidate = populate(alias)
            schema_before = inventory(alias)
            before = row_counts(alias)

            holder = second_session(alias)
            try:
                with holder.cursor() as cursor:
                    cursor.execute('SELECT id FROM catalog_productpresentation WHERE id = %s FOR UPDATE',
                                   (published.pk,))
                with connections[alias].cursor() as cursor:
                    cursor.execute(f"SET lock_timeout = '{LOCK_TIMEOUT}'")
                with self.assertRaises(DatabaseError):
                    migrate(alias, 'catalog', 'zero')
            finally:
                with connections[alias].cursor() as cursor:
                    cursor.execute('SET lock_timeout = 0')
                holder.rollback()
                holder.close()
            self.assertNotIn('ingestion_importreceiptitem', tables(alias))

            migrate(alias)

            self.assertEqual(len(applied(alias)), 31)
            self.assertEqual(inventory(alias), schema_before, 'forward migrate did not restore the schema')
            self.assertEqual(inspect(alias)['status'], 'no_selected_issues')
            after = row_counts(alias)
            self.assertEqual(after['ingestion_importreceiptitem'], 0,
                             'the dropped rows came back with the table')
            self.assertEqual(sum(after.values()), sum(before.values()) - 2)
            self.assertEqual(rows(alias, 'SELECT rows, created, duplicates FROM ingestion_importreceipt'),
                             [(2, 2, 0)], 'the receipt still counts items that no longer exist')
