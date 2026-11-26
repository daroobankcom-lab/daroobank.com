"""Selected in-flight revision write boundaries; not global revocation."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from catalog.identity import digest, ingredient_snapshot, package_snapshot, require_staff as identity_require_staff
from catalog.models import IdentityPackageDraft, IngredientDraft
from catalog.test_identity import INGREDIENT, PACKAGE, build, user
from clinical.models import ClinicalDraft
from clinical.services import create_draft, draft_data, require_staff as clinical_require_staff

DRAFT = {'subject': 'موضوع فرضی', 'audience': 'patient', 'title': 'عنوان ساختگی',
         'statement': 'گزاره ساختگی صرفاً برای آزمون', 'reference_title': 'ارجاع فرضی',
         'reference_url': 'https://example.org/reference', 'reference_location': 'بخش فرضی',
         'reference_author': '', 'reference_version': '', 'reference_published_on': None,
         'reference_accessed_on': None}
REASON = 'دلیل ساختگی برای ایجاد نسخه جدید'


def posted(value):
    """Render a service value the way the staff forms post it."""
    if value is None:
        return ''
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


@override_settings(STAFF_PORTAL_ENABLED=True,
                   AUTHENTICATION_BACKENDS=['django.contrib.auth.backends.ModelBackend'],
                   SESSION_ENGINE='django.contrib.sessions.backends.db')
class StaffInflightRevisionWriteTests(TransactionTestCase):
    def setUp(self):
        self.author = user('synthetic-revision-author', 'view_identityworkspace', 'add_identityworkspace')
        self.editor = user('synthetic-revision-editor', 'view_identityworkspace', 'add_identityworkspace')
        self.ingredient, _part, _form, _product, self.package = build(self.author)
        self.writer = get_user_model().objects.create_user('synthetic-revision-clinical-writer', password='synthetic-only',
                                                           is_staff=True)
        from django.contrib.auth.models import Permission
        self.writer.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical'))
        self.draft = create_draft(actor=self.writer, data=dict(DRAFT))

    def client_for(self, account):
        client = Client(enforce_csrf_checks=True)
        client.force_login(account)
        return client

    def token(self, client):
        return client.cookies['csrftoken'].value

    def _paused_post(self, client, path, payload, target, original, change_account, unchanged):
        """Park one CSRF-valid revision POST at its service entry."""
        ready, resume = Event(), Event()

        def paused(*args, **kwargs):
            # The view's own permission checks have already passed.
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic in-flight revision did not resume')
            return original(*args, **kwargs)

        def post_write():
            close_old_connections()
            try:
                return client.post(path, payload, HTTP_X_CSRFTOKEN=self.token(client))
            finally:
                close_old_connections()

        with patch(target, side_effect=paused):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(post_write)
                try:
                    self.assertTrue(ready.wait(10), f'Synthetic revision did not reach {target}')
                    change_account()
                    for model, count in unchanged:
                        self.assertEqual(model.objects.count(), count)
                finally:
                    resume.set()
                return future.result(timeout=20)

    def invalidate_and_reactivate(self, account):
        def change():
            current = get_user_model().objects.get(pk=account.pk)
            current.is_active = False
            current.set_unusable_password()
            current.save(update_fields=['is_active', 'password'])
            get_user_model().objects.filter(pk=account.pk).update(is_active=True)
        return change

    def disable_then_reactivate(self, account):
        def change():
            current = get_user_model().objects.get(pk=account.pk)
            current.is_active = False
            current.save(update_fields=['is_active'])
            get_user_model().objects.filter(pk=account.pk).update(is_active=True)
        return change

    def clinical_payload(self):
        return {**{key: posted(value) for key, value in draft_data(self.draft).items()},
                'expected_parent_hash': self.draft.payload_sha256, 'change_reason': REASON, 'synthetic_ack': 'on'}

    def test_password_invalidation_before_clinical_revise_guard_denies_inflight_revision(self):
        client = self.client_for(self.writer)
        path = reverse('staff_clinical_revise', args=[self.draft.pk])
        payload = self.clinical_payload()
        drafts = ClinicalDraft.objects.count()
        self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(client.post(path, payload).status_code, 403)  # CSRF negative control
        self.assertEqual(ClinicalDraft.objects.count(), drafts)
        response = self._paused_post(client, path, payload, 'clinical.services.require_staff', clinical_require_staff,
                                     self.invalidate_and_reactivate(self.writer), [(ClinicalDraft, drafts)])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ClinicalDraft.objects.count(), drafts)
        fresh = client.post(path, payload, HTTP_X_CSRFTOKEN=self.token(client))
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertEqual(ClinicalDraft.objects.count(), drafts)

    def test_flag_only_reactivation_before_clinical_revise_guard_can_still_allow_inflight_revision(self):
        client = self.client_for(self.writer)
        path = reverse('staff_clinical_revise', args=[self.draft.pk])
        drafts = ClinicalDraft.objects.count()
        self.assertEqual(client.get(path).status_code, 200)
        response = self._paused_post(client, path, self.clinical_payload(), 'clinical.services.require_staff',
                                     clinical_require_staff, self.disable_then_reactivate(self.writer),
                                     [(ClinicalDraft, drafts)])
        revision = ClinicalDraft.objects.order_by('-pk').first()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_clinical_detail', args=[revision.pk]))
        self.assertEqual(revision.parent_id, self.draft.pk)
        self.assertEqual(ClinicalDraft.objects.count(), drafts + 1)

    def package_payload(self):
        # A revision must actually change the assertion; an identical payload is
        # rejected as a no-op before any actor recheck matters.
        changed = {**PACKAGE, 'quantity': Decimal('20')}
        return {**{key: posted(value) for key, value in changed.items()}, 'synthetic_ack': 'on',
                'change_reason': REASON, 'expected_graph_hash': digest(package_snapshot(self.package)),
                'expected_review': '0'}

    def test_password_invalidation_before_package_revise_guard_denies_inflight_revision(self):
        client = self.client_for(self.editor)
        path = reverse('staff_identity_revise', args=[self.package.pk])
        payload = self.package_payload()
        packages = IdentityPackageDraft.objects.count()
        self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(client.post(path, payload).status_code, 403)  # CSRF negative control
        self.assertEqual(IdentityPackageDraft.objects.count(), packages)
        response = self._paused_post(client, path, payload, 'catalog.identity.require_staff', identity_require_staff,
                                     self.invalidate_and_reactivate(self.editor), [(IdentityPackageDraft, packages)])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(IdentityPackageDraft.objects.count(), packages)
        fresh = client.post(path, payload, HTTP_X_CSRFTOKEN=self.token(client))
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertEqual(IdentityPackageDraft.objects.count(), packages)

    def test_flag_only_reactivation_before_package_revise_guard_can_still_allow_inflight_revision(self):
        client = self.client_for(self.editor)
        path = reverse('staff_identity_revise', args=[self.package.pk])
        packages = IdentityPackageDraft.objects.count()
        self.assertEqual(client.get(path).status_code, 200)
        response = self._paused_post(client, path, self.package_payload(), 'catalog.identity.require_staff',
                                     identity_require_staff, self.disable_then_reactivate(self.editor),
                                     [(IdentityPackageDraft, packages)])
        child = IdentityPackageDraft.objects.order_by('-pk').first()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_identity_detail', args=['package', child.pk]))
        self.assertEqual(IdentityPackageDraft.objects.count(), packages + 1)

    def ingredient_payload(self):
        changed = {**INGREDIENT, 'name_fa': 'ماده ساختگی اصلاح‌شده'}
        return {**{key: posted(value) for key, value in changed.items()}, 'synthetic_ack': 'on',
                'change_reason': REASON, 'expected_graph_hash': digest(ingredient_snapshot(self.ingredient))}

    def test_password_invalidation_before_component_correction_guard_denies_inflight_revision(self):
        client = self.client_for(self.editor)
        path = reverse('staff_identity_revise_component', args=['ingredient', self.ingredient.pk])
        payload = self.ingredient_payload()
        ingredients = IngredientDraft.objects.count()
        self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(client.post(path, payload).status_code, 403)  # CSRF negative control
        self.assertEqual(IngredientDraft.objects.count(), ingredients)
        response = self._paused_post(client, path, payload, 'catalog.identity.require_staff', identity_require_staff,
                                     self.invalidate_and_reactivate(self.editor), [(IngredientDraft, ingredients)])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(IngredientDraft.objects.count(), ingredients)
        fresh = client.post(path, payload, HTTP_X_CSRFTOKEN=self.token(client))
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertEqual(IngredientDraft.objects.count(), ingredients)

    def test_flag_only_reactivation_before_component_correction_guard_can_still_allow_inflight_revision(self):
        client = self.client_for(self.editor)
        path = reverse('staff_identity_revise_component', args=['ingredient', self.ingredient.pk])
        ingredients = IngredientDraft.objects.count()
        self.assertEqual(client.get(path).status_code, 200)
        response = self._paused_post(client, path, self.ingredient_payload(), 'catalog.identity.require_staff',
                                     identity_require_staff, self.disable_then_reactivate(self.editor),
                                     [(IngredientDraft, ingredients)])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(IngredientDraft.objects.count(), ingredients + 1)
