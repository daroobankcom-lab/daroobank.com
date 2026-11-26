"""Selected source-write account-status boundary; not global revocation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from sources.models import SourceClaim
from sources.services import validate_data


@override_settings(STAFF_PORTAL_ENABLED=True,
                   AUTHENTICATION_BACKENDS=['django.contrib.auth.backends.ModelBackend'],
                   SESSION_ENGINE='django.contrib.sessions.backends.db')
class StaffInflightWriteTests(TransactionTestCase):
    def test_selected_csrf_valid_source_write_denied_if_disable_commits_before_write(self):
        user = get_user_model().objects.create_user('synthetic-inflight-writer', password='synthetic-only', is_staff=True)
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources',
                                  codename__in=['view_sourceclaim', 'add_sourceclaim']))
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        path = reverse('staff_source_create')
        self.assertEqual(client.get(path).status_code, 200)
        token = client.cookies['csrftoken'].value
        payload = {'source_name': 'Synthetic source', 'source_url': 'https://example.org/source',
                   'owner': 'Synthetic owner', 'evidence_url': 'https://example.org/evidence',
                   'evidence_note': 'Synthetic evidence', 'claims_collection': 'on', 'attestation': 'on'}
        self.assertEqual(client.post(path, payload).status_code, 403)  # CSRF negative control
        self.assertFalse(SourceClaim.objects.exists())
        ready, resume = Event(), Event()

        def paused_validation(*args, **kwargs):
            # The view and initial service authorization have passed.
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic write did not resume')
            return validate_data(*args, **kwargs)

        def post_claim():
            close_old_connections()
            try:
                return client.post(path, payload, HTTP_X_CSRFTOKEN=token)
            finally:
                close_old_connections()

        with patch('sources.services.validate_data', side_effect=paused_validation):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(post_claim)
                try:
                    self.assertTrue(ready.wait(10), 'Synthetic write did not reach validation')
                    current = get_user_model().objects.get(pk=user.pk)
                    current.is_active = False
                    current.set_unusable_password()
                    current.save(update_fields=['is_active', 'password'])
                    self.assertFalse(SourceClaim.objects.exists())
                finally:
                    resume.set()
                response = future.result(timeout=15)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SourceClaim.objects.exists())
        self.assertFalse(get_user_model().objects.get(pk=user.pk).is_active)
        # A fresh request is denied; it must not create another record.
        fresh = client.post(path, {**payload, 'source_url': 'https://example.org/another'}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertEqual(SourceClaim.objects.count(), 0)

    def _paused_write(self, client, path, payload, token, change_account):
        """Start one CSRF-valid POST and apply `change_account` while it is parked."""
        ready, resume = Event(), Event()

        def paused_validation(*args, **kwargs):
            # The view and initial service authorization have already passed.
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic in-flight write did not resume')
            return validate_data(*args, **kwargs)

        def post_claim():
            close_old_connections()
            try:
                return client.post(path, payload, HTTP_X_CSRFTOKEN=token)
            finally:
                close_old_connections()

        with patch('sources.services.validate_data', side_effect=paused_validation):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(post_claim)
                try:
                    self.assertTrue(ready.wait(10), 'Synthetic write did not reach validation')
                    change_account()
                    self.assertFalse(SourceClaim.objects.exists())
                finally:
                    resume.set()
                return future.result(timeout=15)

    def test_password_invalidation_before_guard_denies_inflight_write_after_reactivation(self):
        # The guarded transaction binds the write to the session's authentication
        # hash, so invalidating the password denies even a re-enabled account.
        user = get_user_model().objects.create_user('synthetic-reactivated-writer', password='synthetic-only', is_staff=True)
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources',
                                  codename__in=['view_sourceclaim', 'add_sourceclaim']))
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        path = reverse('staff_source_create')
        self.assertEqual(client.get(path).status_code, 200)
        token = client.cookies['csrftoken'].value
        payload = {'source_name': 'Synthetic source', 'source_url': 'https://example.org/reactivation',
                   'owner': 'Synthetic owner', 'evidence_url': 'https://example.org/evidence',
                   'evidence_note': 'Synthetic evidence', 'claims_collection': 'on', 'attestation': 'on'}

        def invalidate_and_reactivate():
            current = get_user_model().objects.get(pk=user.pk)
            current.is_active = False
            current.set_unusable_password()
            current.save(update_fields=['is_active', 'password'])
            get_user_model().objects.filter(pk=user.pk).update(is_active=True)

        response = self._paused_write(client, path, payload, token, invalidate_and_reactivate)
        self.assertEqual(response.status_code, 403)
        self.assertFalse(SourceClaim.objects.exists())
        # A fresh request also revalidates the old session and is rejected.
        fresh = client.post(path, {**payload, 'source_url': 'https://example.org/another'}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertEqual(SourceClaim.objects.count(), 0)

    def test_flag_only_reactivation_before_guard_can_still_allow_an_inflight_write(self):
        # A remaining gap: with the password unchanged the session hash still
        # matches, so re-enabling the flags lets the parked write commit.
        user = get_user_model().objects.create_user('synthetic-flag-only-writer', password='synthetic-only', is_staff=True)
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources',
                                  codename__in=['view_sourceclaim', 'add_sourceclaim']))
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        path = reverse('staff_source_create')
        self.assertEqual(client.get(path).status_code, 200)
        token = client.cookies['csrftoken'].value
        payload = {'source_name': 'Synthetic source', 'source_url': 'https://example.org/flag-only',
                   'owner': 'Synthetic owner', 'evidence_url': 'https://example.org/evidence',
                   'evidence_note': 'Synthetic evidence', 'claims_collection': 'on', 'attestation': 'on'}

        def disable_then_reactivate():
            current = get_user_model().objects.get(pk=user.pk)
            current.is_active = False
            current.save(update_fields=['is_active'])
            get_user_model().objects.filter(pk=user.pk).update(is_active=True)

        response = self._paused_write(client, path, payload, token, disable_then_reactivate)
        claim = SourceClaim.objects.get()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_source_detail', args=[claim.pk]))
        self.assertEqual(claim.recorded_by_id, user.pk)
        # A later request from the same still-valid session is also accepted.
        fresh = client.post(path, {**payload, 'source_url': 'https://example.org/flag-only-second'},
                            HTTP_X_CSRFTOKEN=token)
        self.assertEqual(fresh.status_code, 302)
        self.assertEqual(SourceClaim.objects.count(), 2)
