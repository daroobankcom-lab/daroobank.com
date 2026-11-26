"""Demonstrate one in-flight read boundary, not a session revocation solution."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.shortcuts import render
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse


@override_settings(STAFF_PORTAL_ENABLED=True,
                   AUTHENTICATION_BACKENDS=['django.contrib.auth.backends.ModelBackend'],
                   SESSION_ENGINE='django.contrib.sessions.backends.db')
class StaffInflightRevocationTests(TransactionTestCase):
    def test_password_invalidation_affects_two_old_sessions_but_not_another_account(self):
        users = get_user_model()
        user = users.objects.create_user('synthetic-multiple-sessions', password='synthetic-only', is_staff=True)
        other = users.objects.create_user('synthetic-unaffected', password='synthetic-other', is_staff=True)
        first, second, unrelated = Client(), Client(), Client()
        first.force_login(user)
        second.force_login(user)
        unrelated.force_login(other)
        self.assertNotEqual(first.session.session_key, second.session.session_key)
        path = reverse('staff_workspace')
        for client in (first, second, unrelated):
            self.assertEqual(client.get(path).status_code, 200)
        user.is_active = False
        user.set_unusable_password()
        user.save(update_fields=['is_active', 'password'])
        # No request occurs while disabled; reactivate directly, leaving the
        # password unusable. This is a controlled behavior demonstration only.
        users.objects.filter(pk=user.pk).update(is_active=True)
        for client in (first, second):
            self.assertEqual(client.get(path).status_code, 302)
            self.assertNotIn('_auth_user_id', client.session)
        self.assertEqual(unrelated.get(path).status_code, 200)

    def test_authorized_workspace_read_can_finish_after_account_disable_and_password_invalidation(self):
        user = get_user_model().objects.create_user('synthetic-inflight', password='synthetic-only', is_staff=True)
        client = Client()
        client.force_login(user)
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 200)
        ready, resume = Event(), Event()

        def paused_render(request, *args, **kwargs):
            # workspace has loaded request.user and passed its own staff check.
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic request did not resume')
            return render(request, *args, **kwargs)

        def read_workspace():
            close_old_connections()
            try:
                return client.get(reverse('staff_workspace')).status_code
            finally:
                close_old_connections()

        with patch('daroobank.staff_views.render', side_effect=paused_render):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(read_workspace)
                try:
                    self.assertTrue(ready.wait(10), 'Synthetic request did not reach render')
                    current = get_user_model().objects.get(pk=user.pk)
                    current.is_active = False
                    current.set_unusable_password()
                    current.save(update_fields=['is_active', 'password'])
                finally:
                    resume.set()
                self.assertEqual(future.result(timeout=15), 200)
        # Even a direct reactivation does not resurrect this particular session,
        # because its password-derived authentication hash was also changed.
        get_user_model().objects.filter(pk=user.pk).update(is_active=True)
        self.assertEqual(client.get(reverse('staff_workspace')).status_code, 302)
        self.assertNotIn('_auth_user_id', client.session)
