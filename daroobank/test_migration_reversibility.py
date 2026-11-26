"""Migration drift, reversibility and rollback round trips on synthetic PostgreSQL.

The Phase 1 data-model gate asks for a staging upgrade and rollback plan against a
representative schema, and for migration compatibility. The plan itself is a document that
needs an owner; what is measurable here is the behavior such a plan has to describe:

* no model change is missing a migration;
* every project app's migrations form one linear chain from its initial migration;
* every data operation declares an explicit reverse, and the two whose reverse is a no-op
  are named, because a no-op reverse means the rollback does not undo the backfill;
* a freshly migrated database matches the model-derived expectations that
  `inspect_postgresql_schema` already applies to the development database;
* rolling one app back cascades to exactly the migrations the graph says depend on it, and
  leaves no foreign key pointing at a table that is gone;
* rolling all six project apps back to zero leaves only Django's own tables, and
  reapplying produces a schema whose column, index and constraint inventory is identical.

Each measurement runs in its own throwaway database on the synthetic PostgreSQL server,
created and dropped by the test. Nothing here touches the suite's own database, and no
data of any kind is written: this is a schema exercise on an empty database.
"""
import uuid
from contextlib import contextmanager
from unittest import mock

from django.core.management import call_command
from django.db import connections
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.operations.special import RunPython, RunSQL
from django.test import TransactionTestCase

from . import postgresql_inspection

PROJECT_APPS = ('catalog', 'clinical', 'ingestion', 'pricing', 'sources', 'staff_security')
MIGRATION_COUNTS = {'catalog': 8, 'clinical': 2, 'ingestion': 2, 'pricing': 2, 'sources': 1, 'staff_security': 1}
# Data migrations whose declared reverse is a no-op: Django will not raise on rollback,
# but the rows the forward direction wrote are not removed by it.
NOOP_REVERSES = {('catalog', '0002_productpresentation_irc_normalized'),
                 ('catalog', '0004_productcandidate_irc_normalized')}
# Rolling one app back is not confined to that app; this is the measured cascade.
CATALOG_CASCADE = {'catalog': 8, 'pricing': 2, 'ingestion': 1}
PROBE_PREFIX = 'daroobank_migration_probe_'


@contextmanager
def throwaway_database():
    """Create an isolated PostgreSQL database, register it, and drop it again.

    The connection is registered dynamically rather than added to ``DATABASES``: a test
    case may only reach aliases it declares, and Django deliberately allows connections
    created at runtime, so a throwaway alias needs no change to the settings and is not
    picked up by the suite's own fixture teardown.
    """
    name = PROBE_PREFIX + uuid.uuid4().hex[:12]
    alias = 'migration_probe'
    default = connections['default']
    settings_dict = {**default.settings_dict, 'NAME': name, 'TEST': {'NAME': name}}
    with default.cursor() as cursor:
        cursor.execute(f'CREATE DATABASE {default.ops.quote_name(name)}')
    connections[alias] = type(default)(settings_dict, alias)
    try:
        yield alias
    finally:
        probe = connections[alias]
        probe.close()
        del connections[alias]
        with default.cursor() as cursor:
            cursor.execute(f'DROP DATABASE IF EXISTS {default.ops.quote_name(name)} WITH (FORCE)')


def rows(alias, sql):
    with connections[alias].cursor() as cursor:
        cursor.execute(sql)
        return cursor.fetchall()


def tables(alias):
    return [name for (name,) in rows(alias, """
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = 'public' ORDER BY 1""")]


def applied(alias):
    return {(app, name) for app, name in rows(alias, 'SELECT app, name FROM django_migrations')}


def inventory(alias):
    """A comparable inventory of every column, index and constraint in the public schema."""
    return {
        'columns': rows(alias, """
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns WHERE table_schema = 'public' ORDER BY 1, 2"""),
        'indexes': rows(alias, """
            SELECT tablename, indexname, indexdef FROM pg_indexes
            WHERE schemaname = 'public' ORDER BY 1, 2"""),
        'constraints': rows(alias, """
            SELECT conrelid::regclass::text, conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint WHERE connamespace = 'public'::regnamespace ORDER BY 1, 2"""),
    }


def foreign_keys(alias):
    return rows(alias, """
        SELECT conrelid::regclass::text, conname, confrelid::regclass::text
        FROM pg_constraint
        WHERE connamespace = 'public'::regnamespace AND contype = 'f' ORDER BY 1, 2""")


def project_tables(alias):
    names = tables(alias)
    return {app: [name for name in names if name.startswith(app + '_')] for app in PROJECT_APPS}


def inspect(alias):
    """Run the existing model-derived schema inspection against the throwaway database."""
    with mock.patch.object(postgresql_inspection, 'connection', connections[alias]):
        return postgresql_inspection.inspect_schema(
            postgresql_inspection.expected_tables(),
            postgresql_inspection.expected_foreign_keys(),
            postgresql_inspection.expected_unique_keys(),
            postgresql_inspection.expected_check_constraints(),
            postgresql_inspection.expected_columns(),
            postgresql_inspection.expected_field_indexes(),
            postgresql_inspection.expected_named_indexes(),
            postgresql_inspection.unsupported_unique_constraints(),
            postgresql_inspection.expected_auto_fields())


def migrate(alias, *args):
    call_command('migrate', *args, database=alias, interactive=False, verbosity=0)


class MigrationReversibilityTests(TransactionTestCase):
    def test_no_model_change_is_missing_a_migration(self):
        # CI runs `manage.py makemigrations --check --dry-run` as a step; this puts the
        # same check inside the suite so a local run catches it too.
        try:
            call_command('makemigrations', check=True, dry_run=True, verbosity=0)
        except SystemExit as exit_code:
            self.fail(f'model changes have no migration (makemigrations --check exited '
                      f'{exit_code.code}); run makemigrations and review the result')

    def test_each_project_app_has_one_linear_migration_chain(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        for app in PROJECT_APPS:
            with self.subTest(app=app):
                names = sorted(name for (label, name) in loader.disk_migrations if label == app)
                self.assertEqual(len(names), MIGRATION_COUNTS[app], 'the migration inventory changed')
                self.assertEqual(names[0], '0001_initial')
                for previous, current in zip(names, names[1:]):
                    dependencies = [key for key in loader.disk_migrations[(app, current)].dependencies
                                    if key[0] == app]
                    self.assertEqual(dependencies, [(app, previous)],
                                     f'{app}.{current} does not depend on exactly its predecessor')
        self.assertEqual(sum(MIGRATION_COUNTS.values()),
                         len([key for key in loader.disk_migrations if key[0] in PROJECT_APPS]))

    def test_every_data_operation_declares_an_explicit_reverse(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        noop = set()
        data_operations = 0
        for (app, name), migration in sorted(loader.disk_migrations.items()):
            if app not in PROJECT_APPS:
                continue
            for operation in migration.operations:
                if isinstance(operation, RunPython):
                    data_operations += 1
                    self.assertIsNotNone(operation.reverse_code,
                                         f'{app}.{name} has a RunPython with no reverse')
                    if operation.reverse_code is RunPython.noop:
                        noop.add((app, name))
                elif isinstance(operation, RunSQL):
                    data_operations += 1
                    self.assertIsNotNone(operation.reverse_sql,
                                         f'{app}.{name} has a RunSQL with no reverse')
                    if operation.reverse_sql is RunSQL.noop:
                        noop.add((app, name))
        self.assertEqual(data_operations, 2, 'a data operation appeared or disappeared')
        self.assertEqual(noop, NOOP_REVERSES,
                         'the set of no-op reverses changed; a rollback no longer undoes what it did')

    def test_a_freshly_migrated_database_matches_the_model_expectations(self):
        with throwaway_database() as alias:
            migrate(alias)
            report = inspect(alias)
            self.assertEqual(report['status'], 'no_selected_issues',
                             f"a fresh database does not match the models: {sorted(k for k, v in report.items() if v)}")
            self.assertEqual(report['unresolved_tables'], 0)
            per_app = project_tables(alias)
            self.assertEqual({app: len(names) for app, names in per_app.items()},
                             {'catalog': 13, 'clinical': 3, 'ingestion': 2, 'pricing': 2,
                              'sources': 2, 'staff_security': 1})
            self.assertEqual(len(applied(alias)), 31, 'the applied migration count changed')
            self.assertEqual(len(foreign_keys(alias)), 50, 'the foreign key count changed')
            self.assertEqual(len(tables(alias)), 32)
            self.assertEqual({kind: len(value) for kind, value in inventory(alias).items()},
                             {'columns': 276, 'indexes': 108, 'constraints': 136},
                             'the representative schema this rollback plan is measured against changed')

    def test_rolling_back_one_app_cascades_to_exactly_its_dependents(self):
        with throwaway_database() as alias:
            migrate(alias)
            before = applied(alias)
            loader = MigrationLoader(connections[alias], ignore_no_migrations=True)
            # Nothing depends on catalog's leaf, so the cascade has to be derived from
            # every catalog migration, not just the last one.
            expected = set()
            for name in sorted(key[1] for key in loader.disk_migrations if key[0] == 'catalog'):
                expected |= set(loader.graph.backwards_plan(('catalog', name)))
            migrate(alias, 'catalog', 'zero')
            after = applied(alias)
            self.assertEqual(before - after, expected,
                             'the migrations Django unapplied are not the ones the graph says depend on catalog')
            self.assertEqual({app: len([key for key in expected if key[0] == app])
                              for app in sorted({key[0] for key in expected})}, CATALOG_CASCADE)
            per_app = project_tables(alias)
            self.assertEqual({app: len(names) for app, names in per_app.items()},
                             {'catalog': 0, 'clinical': 3, 'ingestion': 1, 'pricing': 0,
                              'sources': 2, 'staff_security': 1},
                             'dependents kept their tables after the app they depend on was rolled back')
            self.assertEqual(len(tables(alias)), 16)
            self.assertEqual(len(foreign_keys(alias)), 17)
            # Nothing may be left pointing at a table that no longer exists.
            remaining = set(tables(alias))
            dangling = [(source, constraint, target) for source, constraint, target in foreign_keys(alias)
                        if target not in remaining]
            self.assertEqual(dangling, [], 'the rollback left a foreign key without its target table')
            rolled_back = inspect(alias)
            self.assertEqual(rolled_back['status'], 'attention')
            self.assertGreater(rolled_back['unresolved_tables'], 0,
                               'the inspection should see the tables the rollback removed')

    def test_a_full_rollback_and_reapply_lands_on_the_same_schema(self):
        with throwaway_database() as alias:
            migrate(alias)
            first = inventory(alias)
            for app in reversed(PROJECT_APPS):
                migrate(alias, app, 'zero')
            left = set(tables(alias))
            self.assertEqual([name for name in left if name.startswith(PROJECT_APPS)], [],
                             'project tables survived a rollback to zero')
            self.assertEqual({app: names for app, names in project_tables(alias).items() if names}, {})
            self.assertEqual({key[0] for key in applied(alias)} & set(PROJECT_APPS), set(),
                             'django_migrations still records a project app as applied')
            self.assertIn('django_migrations', left)
            self.assertTrue({'auth_user', 'django_content_type', 'django_session'} <= left,
                            "Django's own tables should be untouched by a project rollback")
            self.assertEqual(inspect(alias)['status'], 'attention')
            migrate(alias)
            second = inventory(alias)
            self.assertEqual(second, first,
                             'reapplying the migrations did not reproduce the original schema')
            self.assertEqual(inspect(alias)['status'], 'no_selected_issues')

    def test_the_throwaway_database_is_dropped_again(self):
        with throwaway_database() as alias:
            migrate(alias, 'staff_security')
            self.assertTrue([name for name in tables(alias) if name.startswith('staff_security_')])
        with connections['default'].cursor() as cursor:
            cursor.execute('SELECT datname FROM pg_database WHERE datname LIKE %s', [PROBE_PREFIX + '%'])
            left = [row[0] for row in cursor.fetchall()]
        self.assertEqual(left, [], 'a throwaway migration database was left behind')
