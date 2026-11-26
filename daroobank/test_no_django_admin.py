"""`django.contrib.admin` is not installed, and nothing may add it silently.

The whole administrative surface of this project is the hand-built staff portal, whose 43
routes are measured across ADRs 0199–0217: authorization, denial parity, identifier and
method parity, query parity, the CSRF gate, session lifecycle, the header inventory,
redirect targets, durable session invalidation and the generated review document.
`django.contrib.admin` would add a second, much larger surface with its own permission
model, its own login path, its own `django_admin_log` writes and none of that measurement.

So its absence is a decision, and this suite is the drift guard for it: the app must not be
installed, no admin path may resolve or answer anything but a plain 404 for any account
shape, no admin table may exist, no project module may import it, the resolver must hold no
third surface beyond the staff portal and the twelve public routes, and the operational
commands that replace admin's everyday role must still be there.

This pins an absence. It does not make the staff portal adequate, and it is not a review of
what an admin surface would need if one were ever proposed.
"""
import ast
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import get_commands
from django.db import connection
from django.test import Client, TestCase
from django.urls import Resolver404, resolve

from .authorization_review import public_rows, route_names
from .test_public_route_privacy_matrix import PUBLIC_ROUTES

APP_LABELS = ('auth', 'contenttypes', 'sessions', 'staticfiles', 'catalog', 'pricing', 'sources',
              'ingestion', 'clinical', 'staff_security', 'daroobank')
ADMIN_PATHS = ('/admin/', '/admin', '/admin/login/', '/admin/logout/', '/admin/auth/user/',
               '/admin/catalog/productcandidate/', '/admin/password_change/')
PROJECT_PACKAGES = ('catalog', 'pricing', 'sources', 'ingestion', 'clinical', 'staff_security', 'daroobank')
OPERATIONAL_COMMANDS = ('check_deployment_readiness', 'cleanup_staff_login_windows', 'inspect_postgresql_schema',
                        'list_staff_sessions', 'revoke_staff_sessions')
ROOT = Path(__file__).resolve().parent.parent


class NoDjangoAdminTests(TestCase):
    def test_the_admin_app_is_not_installed(self):
        self.assertNotIn('django.contrib.admin', settings.INSTALLED_APPS)
        self.assertEqual([config.label for config in apps.get_app_configs()], list(APP_LABELS),
                         'an app was added or removed; the staff portal is the only administrative surface')
        self.assertEqual([config.label for config in apps.get_app_configs() if 'admin' in config.label], [])
        self.assertEqual([config.name for config in apps.get_app_configs() if config.name.endswith('admin')], [])

    def test_no_admin_path_resolves(self):
        for path in ADMIN_PATHS:
            with self.subTest(path=path):
                with self.assertRaises(Resolver404):
                    resolve(path)
        # The positive control: the resolver works, so the 404s above are not a blanket result.
        self.assertEqual(resolve('/staff/login/').url_name, 'staff_login')

    def test_an_admin_request_is_a_plain_not_found_for_every_account_shape(self):
        anonymous = self.client.get('/admin/')
        self.assertEqual(anonymous.status_code, 404)
        superuser = get_user_model().objects.create_superuser('admin-probe', password='synthetic-only')
        client = Client()
        client.force_login(superuser)
        privileged = client.get('/admin/')
        self.assertEqual(privileged.status_code, 404)
        self.assertEqual(privileged.content, anonymous.content,
                         'a superuser sees a different admin answer than an anonymous caller')
        for marker in (b'administrator', b'Django admin', b'Log in', b'csrfmiddlewaretoken', b'username'):
            with self.subTest(marker=marker):
                self.assertNotIn(marker, anonymous.content, 'the 404 advertises an administrative login')
        self.assertEqual(len(anonymous.content), 179, 'the not-found page changed shape')

    def test_no_admin_table_exists(self):
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name LIKE 'django\\_%' ORDER BY 1""")
            django_tables = [row[0] for row in cursor.fetchall()]
            cursor.execute("""
                SELECT count(*) FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name LIKE '%admin%'""")
            admin_tables = cursor.fetchone()[0]
            cursor.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
            total = cursor.fetchone()[0]
        self.assertEqual(django_tables, ['django_content_type', 'django_migrations', 'django_session'],
                         'django_admin_log appeared, so the admin app was installed and migrated')
        self.assertEqual(admin_tables, 0)
        self.assertEqual(total, 32, 'the table inventory ADR 0216 pins changed')

    def test_no_project_module_imports_the_admin(self):
        # Parsed imports rather than a text search, so this file's own prose about the
        # admin does not count as importing it.
        importing = []
        for package in PROJECT_PACKAGES:
            for path in sorted((ROOT / package).rglob('*.py')):
                tree = ast.parse(path.read_text(encoding='utf-8'))
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        # Both `from django.contrib.admin import site` and
                        # `from django.contrib import admin` count as importing it.
                        modules = [node.module or '']
                        if (node.module or '') == 'django.contrib':
                            modules += [f'django.contrib.{alias.name}' for alias in node.names]
                    elif isinstance(node, ast.Import):
                        modules = [alias.name for alias in node.names]
                    else:
                        continue
                    if any(module == 'django.contrib.admin' or module.startswith('django.contrib.admin.')
                           for module in modules):
                        importing.append(f'{path.relative_to(ROOT)}:{node.lineno}')
        self.assertEqual(importing, [], 'a project module now imports the Django admin')
        # The positive control: the scan does find imports of another contrib app.
        found = []
        for path in sorted((ROOT / 'daroobank').rglob('*.py')):
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and (node.module or '').startswith('django.contrib.sessions'):
                    found.append(path.name)
        self.assertTrue(found, 'the import scan found nothing at all, so its negative result means nothing')

    def test_the_resolver_holds_no_third_surface(self):
        # The review's inventory walks included resolvers, which is where a mounted admin
        # would hide; `.name` on the top-level patterns alone would not see it.
        names = route_names()
        # The public set comes from the probe matrix, not from the walked inventory, or a
        # newly mounted surface would define itself as public and the check would pass.
        public = {name for _label, name, _kwargs, _query, _status in PUBLIC_ROUTES}
        self.assertEqual(len(public), 12)
        self.assertEqual({row['name'] for row in public_rows()}, public,
                         'the review lists a non-staff route the privacy matrix does not probe')
        staff = {name for name in names if name.startswith('staff_')}
        self.assertEqual(len(staff), 43)
        self.assertEqual(names - staff - public, set(),
                         'a route appeared that is neither a staff portal route nor a public one')
        self.assertEqual(staff & public, set())

    def test_the_commands_that_replace_admin_still_exist(self):
        commands = get_commands()
        for name in OPERATIONAL_COMMANDS:
            with self.subTest(command=name):
                self.assertIn(name, commands, 'an operational command that replaces an admin screen is gone')
        self.assertEqual({name: commands[name] for name in OPERATIONAL_COMMANDS},
                         {'check_deployment_readiness': 'daroobank',
                          'cleanup_staff_login_windows': 'staff_security',
                          'inspect_postgresql_schema': 'catalog',
                          'list_staff_sessions': 'staff_security',
                          'revoke_staff_sessions': 'staff_security'})
