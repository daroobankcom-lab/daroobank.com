"""Selected staff authorization checks after a staff flag is revoked."""
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import get_resolver, reverse


@override_settings(STAFF_PORTAL_ENABLED=True)
class StaffRevocationBoundaryTests(TestCase):
    def test_existing_session_with_superuser_permissions_but_no_staff_flag_is_denied(self):
        user = get_user_model().objects.create_user('synthetic-revoked-staff', password='synthetic-only',
                                                    is_staff=True, is_superuser=True)
        self.client.force_login(user)
        # Simulate a privilege change after a session was established.
        get_user_model().objects.filter(pk=user.pk).update(is_staff=False)
        checked = 0
        for pattern in get_resolver().url_patterns:
            name = pattern.name or ''
            if not name.startswith('staff_') or name in {'staff_login', 'staff_logout'}:
                continue
            kwargs = {key: 1 if converter.__class__.__name__ == 'IntConverter' else 'synthetic'
                      for key, converter in pattern.pattern.converters.items()}
            for method in ('get', 'head', 'post'):
                with self.subTest(name=name, method=method):
                    response = getattr(self.client, method)(reverse(name, kwargs=kwargs))
                    self.assertIn(response.status_code, (403, 405), f'{name} unexpectedly allowed a revoked staff account')
                    self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
                    checked += 1
        self.assertGreater(checked, 90)
