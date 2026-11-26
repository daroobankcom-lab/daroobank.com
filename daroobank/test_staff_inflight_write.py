"""Selected in-flight write observation; this is not a revocation control."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import close_old_connections
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from sources.models import SourceClaim
from sources.services import _find_or_create_claim


@override_settings(STAFF_PORTAL_ENABLED=True,
                   AUTHENTICATION_BACKENDS=['django.contrib.auth.backends.ModelBackend'],
                   SESSION_ENGINE='django.contrib.sessions.backends.db')
class StaffInflightWriteTests(TransactionTestCase):
    def test_selected_csrf_valid_source_write_can_commit_after_disable(self):
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

        def paused_create(*args, **kwargs):
            # The view and service authorization and form validation have passed.
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic write did not resume')
            return _find_or_create_claim(*args, **kwargs)

        def post_claim():
            close_old_connections()
            try:
                return client.post(path, payload, HTTP_X_CSRFTOKEN=token)
            finally:
                close_old_connections()

        with patch('sources.services._find_or_create_claim', side_effect=paused_create):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(post_claim)
                try:
                    self.assertTrue(ready.wait(10), 'Synthetic write did not reach insertion')
                    current = get_user_model().objects.get(pk=user.pk)
                    current.is_active = False
                    current.set_unusable_password()
                    current.save(update_fields=['is_active', 'password'])
                    self.assertFalse(SourceClaim.objects.exists())
                finally:
                    resume.set()
                response = future.result(timeout=15)
        claim = SourceClaim.objects.get()
        self.assertEqual(claim.recorded_by_id, user.pk)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_source_detail', args=[claim.pk]))
        self.assertFalse(get_user_model().objects.get(pk=user.pk).is_active)
        # A fresh request is denied; it must not create another record.
        fresh = client.post(path, {**payload, 'source_url': 'https://example.org/another'}, HTTP_X_CSRFTOKEN=token)
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertEqual(SourceClaim.objects.count(), 1)
