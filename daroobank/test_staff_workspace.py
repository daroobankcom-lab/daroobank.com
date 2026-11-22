"""Permission-scoped navigation tests with synthetic accounts and no business data."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffWorkspaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user('workspace-staff', password='synthetic-passphrase', is_staff=True)

    def permission(self, app, codename):
        return Permission.objects.get(content_type__app_label=app, codename=codename)

    def test_anonymous_nonstaff_disabled_and_methods(self):
        url = reverse('staff_workspace')
        response = self.client.get(url)
        self.assertRedirects(response, reverse('staff_login') + '?next=' + url)
        normal = get_user_model().objects.create_user('not-staff', is_staff=False)
        self.client.force_login(normal)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.user)
        self.assertEqual(self.client.head(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.put(url).status_code, 405)
        with self.settings(STAFF_PORTAL_ENABLED=False):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
            self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
            self.assertNotContains(self.client.get(reverse('home')), url)
        inactive = get_user_model().objects.create_user('inactive-workspace', is_staff=True, is_active=False)
        self.client.force_login(inactive)
        self.assertNotEqual(self.client.get(url).status_code, 200)

    def test_no_permission_is_empty_private_and_no_business_reads(self):
        self.client.force_login(self.user)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('staff_workspace'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'بخشی برای این حساب قابل نمایش نیست')
        self.assertEqual(response.context['links'], [])
        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        for query in queries:
            self.assertNotIn('catalog_', query['sql'].lower())
            self.assertNotIn('pricing_', query['sql'].lower())
            self.assertNotIn('clinical_', query['sql'].lower())
            self.assertNotIn('sources_', query['sql'].lower())
            self.assertNotIn('ingestion_', query['sql'].lower())
        self.assertNotContains(self.client.get(reverse('home')), f'href="{reverse("staff_workspace")}"')

    def test_each_permission_exposes_only_authorized_destinations(self):
        cases = [
            ('catalog', 'view_productcandidate', {'staff_products', 'staff_import_receipts', 'staff_ingestion_window'}),
            ('pricing', 'view_pricecandidate', {'staff_prices', 'staff_import_receipts', 'staff_ingestion_window'}),
            ('sources', 'view_sourceclaim', {'staff_sources', 'staff_ingestion_window'}),
            ('clinical', 'view_clinicaldraft', {'staff_clinical_drafts'}),
            ('catalog', 'view_identityworkspace', {'staff_identity_list'}),
            ('catalog', 'view_productpresentation', {'staff_catalog_quality'}),
        ]
        for index, (app, codename, expected) in enumerate(cases):
            with self.subTest(permission=codename):
                user = get_user_model().objects.create_user(f'workspace-{index}', is_staff=True)
                # Exercise both direct and group-granted permissions.
                if index == 0:
                    group = Group.objects.create(name='workspace-group')
                    group.permissions.add(self.permission(app, codename))
                    user.groups.add(group)
                else:
                    user.user_permissions.add(self.permission(app, codename))
                self.client.force_login(user)
                response = self.client.get(reverse('staff_workspace'))
                self.assertEqual({entry['route'] for entry in response.context['links']}, expected)
                for route in expected:
                    self.assertContains(response, f'href="{reverse(route)}"')
                    destination = self.client.get(reverse(route))
                    self.assertEqual(destination.status_code, 200, route)
                    self.assertContains(destination, f'href="{reverse("staff_workspace")}"')
                if 'staff_import_receipts' not in expected:
                    self.assertEqual(self.client.get(reverse('staff_import_receipts')).status_code, 403)
                if 'staff_identity_list' not in expected:
                    self.assertEqual(self.client.get(reverse('staff_identity_list')).status_code, 403)

    def test_revoked_permission_removes_link_and_destination_access(self):
        perm = self.permission('catalog', 'view_identityworkspace')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('staff_workspace')), f'href="{reverse("staff_identity_list")}"')
        self.user.user_permissions.remove(perm)
        self.assertNotContains(self.client.get(reverse('staff_workspace')), f'href="{reverse("staff_identity_list")}"')
        self.assertEqual(self.client.get(reverse('staff_identity_list')).status_code, 403)

    def test_superuser_all_links_and_csrf_logout(self):
        user = get_user_model().objects.create_superuser('workspace-admin', 'admin@example.org', 'synthetic-passphrase')
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        response = client.get(reverse('staff_workspace'))
        self.assertEqual(len(response.context['links']), 8)
        self.assertEqual(client.post(reverse('staff_logout')).status_code, 403)
        token = client.cookies['csrftoken'].value
        self.assertRedirects(client.post(reverse('staff_logout'), {'csrfmiddlewaretoken': token}), reverse('home'))
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 302)
