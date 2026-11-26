"""Permission-scoped navigation tests with synthetic accounts and no business data."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.auth.forms import AuthenticationForm
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

    @override_settings(APPEND_SLASH=True, SECURE_SSL_REDIRECT=False)
    def test_slashless_staff_root_is_private_and_disabled_before_redirect(self):
        for enabled in (False, True):
            with self.settings(STAFF_PORTAL_ENABLED=enabled):
                for method in (self.client.get, self.client.head):
                    with self.subTest(enabled=enabled, method=method.__name__), self.assertNumQueries(0):
                        response = method('/staff', {'next': 'synthetic-canary'})
                        self.assertEqual(response.status_code, 301 if enabled else 404)
                        if enabled:
                            self.assertEqual(response['Location'], '/staff/?next=synthetic-canary')
                        self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                        self.assertEqual(response['Referrer-Policy'], 'same-origin')
                        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        with self.settings(STAFF_PORTAL_ENABLED=False):
            csrf_client = Client(enforce_csrf_checks=True)
            with self.assertNumQueries(0):
                response = csrf_client.post('/staff', {'synthetic': 'canary'})
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
            self.assertNotIn(b'canary', response.content)
        # A prefix lookalike is neither a staff endpoint nor hidden by the gate.
        with self.settings(STAFF_PORTAL_ENABLED=False):
            response = self.client.get('/staffing')
            self.assertEqual(response.status_code, 404)
            self.assertNotEqual(response.get('Cache-Control'), 'private, no-store, max-age=0')

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

    def test_pending_shortcuts_use_existing_filters_and_permissions(self):
        mappings = [
            ('catalog', 'view_productcandidate', 'staff_products', 'status=pending', 'status'),
            ('pricing', 'view_pricecandidate', 'staff_prices', 'review=pending', 'review_status'),
            ('sources', 'view_sourceclaim', 'staff_sources', 'status=pending', 'status'),
            ('clinical', 'view_clinicaldraft', 'staff_clinical_drafts', 'status=pending', 'status'),
        ]
        for index, (app, permission, route, query, context_key) in enumerate(mappings):
            with self.subTest(permission=permission):
                user = get_user_model().objects.create_user(f'pending-{index}', is_staff=True)
                user.user_permissions.add(self.permission(app, permission))
                self.client.force_login(user)
                workspace = self.client.get(reverse('staff_workspace'))
                expected = reverse(route) + '?' + query
                self.assertContains(workspace, f'href="{expected}"')
                pending = [link for link in workspace.context['links'] if link.get('pending_filter')]
                self.assertEqual([(link['route'], link['pending_filter']) for link in pending], [(route, query)])
                queue = self.client.get(expected)
                self.assertEqual(queue.status_code, 200)
                self.assertEqual(queue.context[context_key], 'pending')
                for _, _, other_route, other_query, _ in mappings:
                    if other_route != route:
                        self.assertNotContains(workspace, f'href="{reverse(other_route)}?{other_query}"')
                        self.assertEqual(self.client.get(reverse(other_route) + '?' + other_query).status_code, 403)

    def test_public_and_staff_skip_target_is_programmatically_focusable(self):
        for name in ('home', 'about', 'staff_login'):
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertContains(response, '<main id="main" tabindex="-1">')
                self.assertContains(response, 'class="skip-link" href="#main"')

    def test_login_does_not_steal_initial_focus_even_after_invalid_post(self):
        login = reverse('staff_login')
        for response in (self.client.get(login), self.client.post(login, {
                'username': 'workspace-staff', 'password': 'incorrect-synthetic-password'})):
            with self.subTest(method=response.wsgi_request.method):
                self.assertEqual(response.status_code, 200)
                self.assertNotIn('autofocus', response.context['form'].fields['username'].widget.attrs)
                self.assertNotContains(response, 'autofocus')
                self.assertContains(response, 'href="#main"')
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                self.assertContains(response, 'name="csrfmiddlewaretoken"')
        # The portal customizes only its own form instance, not Django's base form.
        self.assertTrue(AuthenticationForm().fields['username'].widget.attrs['autofocus'])

    def test_default_login_landing_and_safe_next(self):
        # Even an active staff account with no view permission gets the empty workspace.
        credentials = {'username': self.user.username, 'password': 'synthetic-passphrase'}
        workspace = reverse('staff_workspace')
        for next_url, expected in [('', workspace), ('https://evil.example/path', workspace),
                                   ('//evil.example/path', workspace), ('javascript:alert(1)', workspace),
                                   (reverse('staff_identity_list') + '?kind=package',
                                    reverse('staff_identity_list') + '?kind=package')]:
            with self.subTest(next_url=next_url):
                self.client.logout()
                response = self.client.post(reverse('staff_login'), {**credentials, 'next': next_url})
                self.assertRedirects(response, expected, fetch_redirect_response=False)
                if next_url.startswith('/staff/catalog/identity/'):
                    # A safe next URL does not confer destination permissions.
                    self.assertEqual(self.client.get(expected).status_code, 403)
                else:
                    self.assertContains(self.client.get(expected), 'بخشی برای این حساب قابل نمایش نیست')

    def test_revoked_permission_removes_link_and_destination_access(self):
        perm = self.permission('catalog', 'view_identityworkspace')
        self.user.user_permissions.add(perm)
        self.client.force_login(self.user)
        self.assertContains(self.client.get(reverse('staff_workspace')), f'href="{reverse("staff_identity_list")}"')
        self.user.user_permissions.remove(perm)
        # Removing the permission ends the session rather than only hiding the link: the
        # workspace and the destination both answer an anonymous caller, so the revoked
        # access cannot come back if the permission is granted again.
        login = reverse('staff_login')
        for name in ('staff_workspace', 'staff_identity_list'):
            with self.subTest(route=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertTrue(response['Location'].startswith(login), response['Location'])
        self.assertNotIn('_auth_user_id', self.client.session)
        # A fresh login with the permission still removed shows neither link nor access.
        self.client.force_login(get_user_model().objects.get(pk=self.user.pk))
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

    def test_shortcuts_only_include_records_with_no_review_event(self):
        # Synthetic rows created directly to exercise existing filters, not to
        # imply that these assertions or review snapshots are valid or approved.
        from catalog.models import ProductCandidate, ProductCandidateReview
        from clinical.models import ClinicalDraft, ClinicalDraftReview
        from pricing.models import PriceCandidate, PriceCandidateReview
        from sources.models import SourceClaim, SourceClaimReview

        admin = get_user_model().objects.create_superuser('queue-admin', 'queue@example.org', 'synthetic-passphrase')
        common = {'source_name': 'ساختگی', 'source_url': 'https://example.org', 'payload_sha256': 'a' * 64}
        rows = {}
        for i, label in enumerate(('unreviewed', 'deferred')):
            product = ProductCandidate.objects.create(**common, source_record_id=label, source_fields={}, staged_by=admin)
            price = PriceCandidate.objects.create(**common, source_record_id=label, source_fields={}, staged_by=admin,
                original_amount='1', original_currency='RIAL', amount_rial=1, price_category='retail',
                unit='package', match_status='unmatched')
            claim = SourceClaim.objects.create(**{**common, 'source_url': f'https://example.org/{label}'},
                owner='مالک ساختگی', evidence_url='https://example.org/evidence', claims_collection=True, recorded_by=admin)
            draft = ClinicalDraft.objects.create(subject='موضوع ساختگی', audience='patient', title=label,
                statement='متن ساختگی', reference_title='ارجاع ساختگی', reference_url='https://example.org',
                reference_location='بخش ساختگی', payload_sha256='a' * 64, author=admin)
            rows[label] = (product, price, claim, draft)
            if i:
                ProductCandidateReview.objects.create(candidate=product, reviewer=admin, decision='defer',
                    reason='ساختگی', candidate_payload_sha256='a' * 64, review_snapshot={})
                PriceCandidateReview.objects.create(candidate=price, reviewer=admin, decision='defer',
                    reason='ساختگی', candidate_payload_sha256='a' * 64, review_snapshot={})
                SourceClaimReview.objects.create(claim=claim, reviewer=admin, decision='defer',
                    reason='ساختگی', claim_payload_sha256='a' * 64, review_snapshot={})
                ClinicalDraftReview.objects.create(draft=draft, reviewer=admin, decision='defer',
                    reason='ساختگی', draft_payload_sha256='a' * 64, review_snapshot={})
        self.client.force_login(admin)
        workspace = self.client.get(reverse('staff_workspace'))
        pending_links = {item['route']: item['pending_filter'] for item in workspace.context['links'] if item.get('pending_filter')}
        routes = ('staff_products', 'staff_prices', 'staff_sources', 'staff_clinical_drafts')
        for index, route in enumerate(routes):
            with self.subTest(route=route):
                response = self.client.get(reverse(route) + '?' + pending_links[route])
                self.assertEqual(response.status_code, 200)
                self.assertEqual([item.pk for item in response.context['page']], [rows['unreviewed'][index].pk])
