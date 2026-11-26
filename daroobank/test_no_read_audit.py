"""Nothing in this system records that a read happened.

ADR 0220 measured the write side of attribution: 19 of the project models name the account
that appended them, behind a protected foreign key and a creation timestamp. This suite
measures the other side, and the answer is that there is nothing to measure — no access log, no
audit table, no logger, no middleware that records a request, and no row created by reading.

That is stated here as a pinned absence rather than left implicit, because `settings.py` calls
audit one of the things the staff portal is waiting for, because a pharmacy-adjacent catalog
raises "who looked at this?" as a real question, and because an absence that nobody wrote down
is indistinguishable from an absence nobody noticed.

The measurements are: `LOGGING` is empty and no project module imports `logging`; the middleware
stack is exactly the thirteen entries that set headers, resolve sessions, guard staff state and
count reads for an opt-in limiter that is off by default; no table in the schema can hold an
access record, while the four revision tables that do exist
record writes; a sweep of every staff route with a fully permitted account, and of every public
route anonymously, creates no row in any of the 24 project tables and no session row; and, as a
positive control, the same counter does see an insert and does see the session a login creates.

This pins that reads are unrecorded. It does not judge whether that is acceptable, and it cannot
see recording that happens outside the process — a reverse proxy access log, a database log or a
host-level audit daemon would all be invisible here.
"""
import ast
import re
from collections import Counter
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.urls import get_resolver, reverse

from daroobank.authorization_review import route_names

ROOT = Path(__file__).resolve().parent.parent
PROJECT_APPS = ('catalog', 'clinical', 'daroobank', 'ingestion', 'pricing', 'sources',
                'staff_security')
SOURCE_APPS = ('catalog', 'clinical', 'ingestion', 'pricing', 'sources', 'staff_security')
MIDDLEWARE = (
    'daroobank.middleware.ContentSecurityPolicyMiddleware',
    'daroobank.middleware.HealthProbePrivacyHeadersMiddleware',
    'daroobank.middleware.EarlyRedirectPrivacyHeadersMiddleware',
    'daroobank.middleware.TrustedProxySchemeMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'daroobank.middleware.PublicReadPrivacyHeadersMiddleware',
    'daroobank.middleware.StaffPrivacyHeadersMiddleware',
    # Opt-in and off by default; it counts reads per keyed client and can refuse
    # one, but stores no path, route, query, agent or account (ADR 0228).
    'daroobank.middleware.PublicReadLimitMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'daroobank.middleware.StaffSessionGuardMiddleware',
)
RECORD_WORDS = ('access', 'audit', 'event', 'log', 'track', 'visit')
REVISION_TABLES = ('catalog_formulationrevision', 'catalog_identitypackagerevision',
                   'catalog_ingredientrevision', 'catalog_productrevision')
CAMEL = re.compile(r'[A-Z][a-z0-9]*')
SCHEMA_TABLES = (
    'auth_group', 'auth_group_permissions', 'auth_permission', 'auth_user', 'auth_user_groups',
    'auth_user_user_permissions', 'catalog_formulationcomponent', 'catalog_formulationdraft',
    'catalog_formulationrevision', 'catalog_identitypackagedraft', 'catalog_identitypackagereview',
    'catalog_identitypackagerevision', 'catalog_identityproductdraft', 'catalog_ingredientdraft',
    'catalog_ingredientrevision', 'catalog_productcandidate', 'catalog_productcandidatereview',
    'catalog_productpresentation', 'catalog_productrevision', 'clinical_clinicaldraft',
    'clinical_clinicaldraftreview', 'clinical_clinicalreferenceassertion', 'django_content_type',
    'django_migrations', 'django_session', 'ingestion_importreceipt',
    'ingestion_importreceiptitem', 'pricing_pricecandidate', 'pricing_pricecandidatereview',
    'sources_sourceclaim', 'sources_sourceclaimreview', 'staff_security_publicreadwindow',
    'staff_security_staffloginwindow',
)
MISSING_PK = 999_999_999
KIND = 'ingredient'
SESSION_TABLE = 'django_session'
# Pinned after measurement; a change here means the read surface changed shape.
STAFF_STATUSES = Counter({200: 19, 404: 18, 405: 6})
PUBLIC_STATUSES = Counter({200: 8, 404: 4})


def project_models():
    return {model._meta.label: model for app in SOURCE_APPS
            for model in apps.get_app_config(app).get_models()}


def camel_tokens(label):
    """The words of a model name, so `AccessLog` matches but `StaffLoginWindow` does not."""
    return [token.lower() for token in CAMEL.findall(label.split('.')[-1])]


def table_counts():
    return {label: model.objects.count() for label, model in sorted(project_models().items())}


def table_names():
    with connection.cursor() as cursor:
        cursor.execute("SELECT table_name FROM information_schema.tables "
                       "WHERE table_schema = 'public' ORDER BY table_name")
        return [row[0] for row in cursor.fetchall()]


def columns_of(table):
    with connection.cursor() as cursor:
        cursor.execute("SELECT column_name FROM information_schema.columns "
                       "WHERE table_schema = 'public' AND table_name = %s ORDER BY column_name", [table])
        return {row[0] for row in cursor.fetchall()}


def source_modules():
    return sorted(path for app in PROJECT_APPS for path in (ROOT / app).rglob('*.py')
                  if 'test' not in path.name and 'migrations' not in path.parts)


def modules_importing(package):
    """Project modules with an `import package` or `from package import ...` statement."""
    found = []
    for path in source_modules():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(name == package or name.startswith(f'{package}.') for name in names):
                found.append(str(path.relative_to(ROOT)))
                break
    return sorted(found)


def read_paths(names):
    """Reverse each route name once, with a missing primary key and a valid identity kind."""
    resolver = get_resolver()
    paths = []
    for name in sorted(names):
        possibilities = resolver.reverse_dict[name][0]
        for _format_string, argument_names in possibilities[:1]:
            kwargs = {key: (KIND if key == 'kind' else MISSING_PK) for key in argument_names}
            paths.append((name, reverse(name, kwargs=kwargs)))
    return paths


class ReadAuditAbsenceTests(SimpleTestCase):
    def test_logging_is_not_configured_and_nothing_imports_it(self):
        self.assertEqual(settings.LOGGING, {}, 'an application logging configuration appeared')
        self.assertEqual(modules_importing('logging'), [],
                         'a project module now imports logging; where its output goes is a documented event')
        # Positive control: the same scan does find a package the project really uses.
        self.assertIn('catalog/intake.py', modules_importing('json'))

    def test_the_middleware_stack_records_nothing(self):
        self.assertEqual(tuple(settings.MIDDLEWARE), MIDDLEWARE)
        for entry in MIDDLEWARE:
            with self.subTest(middleware=entry):
                self.assertEqual([word for word in RECORD_WORDS if word in entry.lower()], [])
        project_entries = tuple(entry for entry in MIDDLEWARE if entry.startswith('daroobank.'))
        self.assertEqual(len(project_entries), 8)
        # Two project middleware act on a request rather than only setting headers: the
        # session guard, which ends a session, and the opt-in read limiter, which counts
        # reads and can refuse one. Neither records what was read (ADR 0228).
        self.assertIn('daroobank.middleware.StaffSessionGuardMiddleware', project_entries)
        self.assertIn('daroobank.middleware.PublicReadLimitMiddleware', project_entries)
        self.assertFalse(settings.PUBLIC_READ_LIMIT_ENABLED,
                         'the synthetic environment enabled the read limiter')


class ReadAuditSchemaTests(TestCase):
    def test_no_project_model_is_named_like_an_access_record(self):
        self.assertEqual(len(project_models()), 24)
        matched = sorted({label for label in project_models()
                          for word in RECORD_WORDS if word in camel_tokens(label)})
        self.assertEqual(matched, [], 'a model appeared whose name suggests it records access')

    def test_no_table_can_hold_an_access_record(self):
        names = table_names()
        self.assertEqual(tuple(sorted(names)), SCHEMA_TABLES,
                         'a table appeared or disappeared; the schema inventory ADRs 0216 and 0218 pin changed')

    def test_the_tables_that_record_changes_record_writes_only(self):
        for table in REVISION_TABLES:
            with self.subTest(table=table):
                self.assertIn(table, table_names())
                self.assertIn('recorded_by_id', columns_of(table),
                              'a revision table lost the column that names who appended it')
                self.assertIn('created_at', columns_of(table))
        self.assertNotIn('django_admin_log', table_names())


class ReadSweepTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        account = get_user_model().objects.create_user('read-sweep', password='synthetic-only',
                                                       is_staff=True)
        account.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=SOURCE_APPS))
        cls.account = account

    def sweep(self, client, names):
        paths = read_paths(names)
        statuses = Counter()
        for _name, path in paths:
            statuses[client.get(path).status_code] += 1
        return paths, statuses

    def test_a_staff_read_sweep_creates_no_row_anywhere(self):
        names = {name for name in route_names() if name.startswith('staff_')}
        before = table_counts()
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM {SESSION_TABLE}')
            sessions_before = cursor.fetchone()[0]

        self.client.force_login(self.account)
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM {SESSION_TABLE}')
            sessions_after_login = cursor.fetchone()[0]
        paths, statuses = self.sweep(self.client, names)

        self.assertEqual(len(paths), 43, 'the staff read surface changed size')
        self.assertEqual(statuses, STAFF_STATUSES)
        self.assertEqual(statuses[403], 0, 'a fully permitted account was denied a read; the sweep proves nothing')
        self.assertEqual(table_counts(), before, 'reading a staff route wrote a row')
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM {SESSION_TABLE}')
            sessions_after = cursor.fetchone()[0]
        self.assertEqual(sessions_after, sessions_after_login, 'reading a staff route wrote a session row')
        self.assertEqual(sessions_after_login, sessions_before + 1,
                         'the login itself did not create a session row, so the counter cannot see writes')

    def test_a_public_read_sweep_creates_no_row_and_no_session(self):
        names = {name for name in route_names() if not name.startswith('staff_')}
        before = table_counts()
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM {SESSION_TABLE}')
            sessions_before = cursor.fetchone()[0]

        paths, statuses = self.sweep(self.client, names)

        self.assertEqual(len(paths), 12, 'the public read surface changed size')
        self.assertEqual(statuses, PUBLIC_STATUSES)
        self.assertEqual(statuses[403], 0)
        self.assertEqual(table_counts(), before, 'reading a public route wrote a row')
        with connection.cursor() as cursor:
            cursor.execute(f'SELECT count(*) FROM {SESSION_TABLE}')
            self.assertEqual(cursor.fetchone()[0], sessions_before,
                             'an anonymous read created a session row')

    def test_the_row_counter_sees_a_write(self):
        from catalog.models import ProductPresentation
        before = table_counts()
        row = ProductPresentation.objects.create(
            name_fa='شمارنده ساختگی', manufacturer='شرکت نمونه', strength='۵ میلی‌گرم',
            dosage_form='قرص', package_description='۱۰ عدد',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic')
        seen = table_counts()
        self.assertEqual(seen['catalog.ProductPresentation'], before['catalog.ProductPresentation'] + 1,
                         'the counter used by the sweeps cannot see an insert')
        row.delete()
        self.assertEqual(table_counts(), before)
