"""Synthetic schedule-form boundaries and actionable private errors."""
from datetime import datetime, timezone
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .forms import WindowForm
from .schedule import ScheduleError


class WindowFormBoundaryTests(SimpleTestCase):
    good = {'start': '09:00', 'end': '10:00', 'zone': 'UTC'}

    def form(self, values):
        return WindowForm({f'window-{key}': value for key, value in values.items()}, prefix='window')

    def test_each_field_is_independently_validated_when_another_is_missing(self):
        for values, field in (({'start': '25:00', 'end': '', 'zone': 'UTC'}, 'start'),
                              ({'start': '', 'end': '99:99', 'zone': 'UTC'}, 'end'),
                              ({'start': '09:00', 'end': '', 'zone': 'Not/AZone'}, 'zone')):
            with self.subTest(field=field):
                form = self.form(values)
                self.assertFalse(form.is_valid())
                self.assertIn(field, form.errors)
                self.assertNotIn(field, form.cleaned_data)

    def test_forbidden_raw_controls_are_never_silently_trimmed(self):
        for field in self.good:
            for control in ('\x00', '\x09', '\x0a', '\x0d', '\x1c', '\x7f', '\x85', '\ud800'):
                for raw in (control + self.good[field], self.good[field] + control):
                    with self.subTest(field=field, raw=ascii(raw)):
                        form = self.form({**self.good, field: raw})
                        self.assertFalse(form.is_valid())
                        self.assertIn(field, form.errors)
                        self.assertNotIn(field, form.cleaned_data)

    def test_ordinary_spaces_are_trimmed_and_equal_times_remain_general_error(self):
        form = self.form({'start': ' 09:00 ', 'end': ' 10:00 ', 'zone': ' UTC '})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data, self.good)
        form = self.form({**self.good, 'end': '09:00'})
        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)


@override_settings(STAFF_PORTAL_ENABLED=True)
class WindowErrorNavigationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.viewer = get_user_model().objects.create_user('window-form-synthetic', is_staff=True)
        cls.viewer.user_permissions.add(Permission.objects.get(content_type__app_label='pricing', codename='view_pricecandidate'))

    def test_field_and_general_errors_show_title_summary_and_no_plan(self):
        self.client.force_login(self.viewer)
        url = reverse('staff_ingestion_window')
        valid = {'start': '09:00', 'end': '10:00', 'zone': 'UTC'}
        initial = self.client.get(url)
        self.assertNotContains(initial, 'id="staff-form-errors"')
        self.assertNotContains(initial, 'خطا در فرم |')
        for data, link in (({**valid, 'start': '25:00', 'end': ''}, '#id_start'),
                           ({**valid, 'zone': '\u001cUTC'}, '#id_zone')):
            with self.subTest(data=data), patch('ingestion.staff_views.inspect_window') as inspect:
                response = self.client.get(url, data)
                self.assertEqual(response.status_code, 200)
                self.assertIsNone(response.context['plan'])
                inspect.assert_not_called()
                self.assertContains(response, 'خطا در فرم |')
                self.assertContains(response, f'href="{link}"')
                self.assertEqual(response['Cache-Control'], 'private, no-store, max-age=0')
        general = self.client.get(url, {**valid, 'end': '09:00'})
        self.assertContains(general, 'پیام عمومی زیر را نیز بررسی کنید')
        self.assertIsNone(general.context['plan'])
        with patch('ingestion.staff_views.now', return_value=datetime(2024, 11, 3, 4, tzinfo=timezone.utc)):
            dst = self.client.get(url, {'start': '01:30', 'end': '04:00', 'zone': 'America/New_York'})
        self.assertContains(dst, 'خطا در فرم |')
        self.assertContains(dst, 'مبهم یا ناموجود')
        self.assertContains(dst, 'پیام عمومی زیر را نیز بررسی کنید')
        self.assertIsNone(dst.context['plan'])

    def test_default_planning_failure_is_visible_without_bound_form(self):
        self.client.force_login(self.viewer)
        with patch('ingestion.staff_views.inspect_window', side_effect=ScheduleError('خطای ساختگی')):
            response = self.client.get(reverse('staff_ingestion_window'))
        self.assertContains(response, 'خطای ساختگی')
        self.assertIsNone(response.context['plan'])
        self.assertFalse(response.context['form'].is_bound)
