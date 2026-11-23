import json
from datetime import datetime, timedelta, timezone
from io import StringIO
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management import call_command, CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .schedule import ScheduleError, inspect_window

UTC = timezone.utc


def utc(year, month, day, hour=0, minute=0, second=0):
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


class WindowPlanningTests(SimpleTestCase):
    def test_tehran_overnight_and_exact_boundaries(self):
        start, end = utc(2026, 11, 22, 19, 30), utc(2026, 11, 22, 21, 30)
        for at, opened, expected in [(start - timedelta(microseconds=1), False, start),
                                      (start, True, start), (end - timedelta(microseconds=1), True, start),
                                      (end, False, start + timedelta(days=1))]:
            with self.subTest(at=at):
                plan = inspect_window(at=at)
                self.assertEqual((plan.start_utc, plan.is_open), (expected, opened))
                self.assertEqual(plan.end_utc, expected + timedelta(hours=2))
                self.assertTrue(plan.crosses_midnight)
                self.assertFalse(plan.as_dict()['dispatch_enabled'])
        # After midnight Tehran the window belongs to the previous local day.
        plan = inspect_window(at=utc(2026, 11, 22, 21))
        self.assertEqual(plan.as_dict()['start_local'], '2026-11-22T23:00:00+03:30')
        self.assertEqual(plan.as_dict()['end_local'], '2026-11-23T01:00:00+03:30')

    def test_non_overnight_and_non_utc_input(self):
        tz = ZoneInfo('Asia/Tehran')
        start = datetime(2026, 3, 1, 9, 0, tzinfo=tz)
        for offset, opened, day in [(-1, False, 1), (0, True, 1), (59, True, 1), (60, False, 2)]:
            plan = inspect_window(at=start + timedelta(minutes=offset), start='09:00', end='10:00')
            self.assertEqual(plan.is_open, opened)
            self.assertFalse(plan.crosses_midnight)
            self.assertEqual(plan.start_utc.astimezone(tz).day, day)

    def test_month_year_and_leap_day_rollover(self):
        plan = inspect_window(at=utc(2024, 2, 29, 23, 45), start='23:00', end='01:00', zone='UTC')
        self.assertEqual(plan.end_utc, utc(2024, 3, 1, 1))
        plan = inspect_window(at=utc(2026, 12, 31, 23, 45), zone='UTC')
        self.assertEqual(plan.end_utc, utc(2027, 1, 1, 1))
        plan = inspect_window(at=utc(2024, 2, 29, 1), start='23:00', end='01:00', zone='UTC')
        self.assertEqual(plan.start_utc, utc(2024, 2, 29, 23))

    def test_dst_transition_inside_window_uses_utc_instants(self):
        # DST begins or ends inside this window; endpoints themselves are unambiguous.
        spring = inspect_window(at=utc(2024, 3, 10, 6), start='00:00', end='04:00', zone='America/New_York')
        autumn = inspect_window(at=utc(2024, 11, 3, 5), start='00:00', end='04:00', zone='America/New_York')
        self.assertEqual(spring.end_utc - spring.start_utc, timedelta(hours=3))
        self.assertEqual(autumn.end_utc - autumn.start_utc, timedelta(hours=5))
        self.assertTrue(spring.is_open and autumn.is_open)
        for at in [utc(2024, 11, 3, 5, 30), utc(2024, 11, 3, 6, 30)]:
            self.assertTrue(inspect_window(at=at, start='00:00', end='04:00', zone='America/New_York').is_open)

    def test_historical_tehran_offset_transition_not_fixed_offset(self):
        spring = inspect_window(at=utc(2022, 3, 21, 20))
        self.assertEqual(spring.end_utc - spring.start_utc, timedelta(hours=1))
        self.assertTrue(spring.as_dict()['start_local'].endswith('+03:30'))
        self.assertTrue(spring.as_dict()['end_local'].endswith('+04:30'))
        with self.assertRaises(ScheduleError):
            inspect_window(at=utc(2022, 9, 21, 20))

    def test_dst_ambiguous_and_missing_boundaries_fail_closed(self):
        for args in [dict(at=utc(2024, 3, 10, 6), start='02:30', end='04:00'),
                     dict(at=utc(2024, 11, 3, 4), start='01:30', end='04:00'),
                     dict(at=utc(2024, 3, 10, 6), start='00:00', end='02:30'),
                     dict(at=utc(2024, 11, 3, 4), start='00:00', end='01:30')]:
            with self.subTest(args=args), self.assertRaises(ScheduleError):
                inspect_window(zone='America/New_York', **args)

    def test_invalid_input_never_returns_plan(self):
        for override in [dict(start='23:00', end='23:00'), dict(start='24:00'), dict(end='1:00'),
                         dict(start='۲۳:۰۰'), dict(start='00:00:00'), dict(zone='Missing/Zone'),
                         dict(zone='../etc/passwd'), dict(zone='a' * 81), dict(zone='UTC\x00'),
                         dict(at=datetime(2026, 1, 1)), dict(at=None),
                         dict(at=datetime.max.replace(tzinfo=UTC), start='00:00', end='00:01', zone='UTC')]:
            with self.subTest(override=override), self.assertRaises(ScheduleError):
                inspect_window(**({'at': utc(2026, 1, 1)} | override))

    def test_command_json_config_errors_and_no_io(self):
        with patch('socket.create_connection', side_effect=AssertionError('network access forbidden')):
            output = StringIO()
            call_command('inspect_ingestion_window', at='2026-11-22T20:00:00Z', stdout=output)
            data = json.loads(output.getvalue())
            self.assertEqual(data['mode'], 'inspection_only')
            self.assertTrue(data['is_open'])
            self.assertFalse(data['dispatch_enabled'])
            self.assertEqual(data['end_local'], '2026-11-23T01:00:00+03:30')
            output = StringIO()
            call_command('inspect_ingestion_window', at='2026-11-22T09:30:00+00:00', start='09:00', end='10:00', timezone='UTC', stdout=output)
            self.assertTrue(json.loads(output.getvalue())['is_open'])
        for kwargs in [dict(at='2026-11-22T09:30:00'), dict(at='not-a-date'), dict(start='23:00', end='23:00'),
                       dict(at='2024-11-03T04:00:00Z', start='01:30', end='04:00', timezone='America/New_York')]:
            with self.subTest(kwargs=kwargs), self.assertRaises(CommandError):
                call_command('inspect_ingestion_window', stdout=StringIO(), **kwargs)


class WindowStaffTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        cls.no_access = user_model.objects.create_user('no-window-access', password='test-only-password', is_staff=True)
        cls.regular = user_model.objects.create_user('regular-window', password='test-only-password')
        cls.inactive = user_model.objects.create_user('inactive-window', password='test-only-password', is_staff=True, is_active=False)
        cls.price = user_model.objects.create_user('price-window', password='test-only-password', is_staff=True)
        cls.product = user_model.objects.create_user('product-window', password='test-only-password', is_staff=True)
        cls.source = user_model.objects.create_user('source-window', password='test-only-password', is_staff=True)
        for user, app, codename in [(cls.price, 'pricing', 'view_pricecandidate'), (cls.product, 'catalog', 'view_productcandidate'),
                                    (cls.source, 'sources', 'view_sourceclaim'), (cls.regular, 'sources', 'view_sourceclaim'),
                                    (cls.inactive, 'sources', 'view_sourceclaim')]:
            user.user_permissions.add(Permission.objects.get(content_type__app_label=app, codename=codename))
        cls.group_user = user_model.objects.create_user('group-window', password='test-only-password', is_staff=True)
        group = Group.objects.create(name='window-price-viewers')
        group.permissions.add(Permission.objects.get(content_type__app_label='pricing', codename='view_pricecandidate'))
        cls.group_user.groups.add(group)

    def assert_private(self, response):
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    def test_authorization_headers_navigation_and_default(self):
        url = reverse('staff_ingestion_window')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302); self.assert_private(response)
        for user in [self.no_access, self.regular]:
            self.client.force_login(user)
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.inactive)
        self.assertEqual(self.client.get(url).status_code, 302)
        for user, listing in [(self.price, 'staff_prices'), (self.product, 'staff_products'), (self.source, 'staff_sources'), (self.group_user, 'staff_prices')]:
            self.client.force_login(user)
            with patch('ingestion.staff_views.now', return_value=utc(2026, 11, 22, 20)):
                response = self.client.get(url)
            self.assertEqual(response.status_code, 200); self.assert_private(response)
            self.assertContains(response, '2026-11-23T01:00:00+03:30')
            self.assertContains(response, 'هیچ زمان‌بند یا خزنده‌ای اجرا نمی‌شود')
            self.assertContains(self.client.get(reverse(listing)), url)
            self.assertEqual(self.client.head(url).status_code, 200)
            self.assertEqual(self.client.post(url).status_code, 405)

    def test_configurable_read_only_get_invalid_and_escaped(self):
        self.client.force_login(self.price)
        url = reverse('staff_ingestion_window')
        with patch('ingestion.staff_views.now', return_value=utc(2026, 11, 22, 9, 30)):
            response = self.client.get(url, {'start': '09:00', 'end': '10:00', 'zone': 'UTC'})
        self.assertContains(response, '2026-11-22T09:00:00+00:00')
        self.assertTrue(response.context['plan']['is_open'])
        for data in [{'start': '09:00', 'end': '09:00', 'zone': 'UTC'},
                     {'start': '09:00', 'end': '10:00', 'zone': '<script>'},
                     {'start': '09:00', 'end': '', 'zone': 'UTC'}]:
            response = self.client.get(url, data)
            self.assertIsNone(response.context['plan'])
            self.assertNotContains(response, '<script>')
            self.assert_private(response)
        with patch('ingestion.staff_views.now', return_value=utc(2024, 11, 3, 4)):
            response = self.client.get(url, {'start': '01:30', 'end': '04:00', 'zone': 'America/New_York'})
        self.assertIsNone(response.context['plan']); self.assertContains(response, 'مبهم یا ناموجود')
        with patch('ingestion.staff_views.inspect_window', side_effect=ScheduleError('خطای زمان')):
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200); self.assertIsNone(response.context['plan'])

    @override_settings(STAFF_PORTAL_ENABLED=False, SECURE_SSL_REDIRECT=False)
    def test_disabled_even_for_staff(self):
        self.client.force_login(self.price)
        for method in [self.client.get, self.client.post]:
            response = method(reverse('staff_ingestion_window'))
            self.assertEqual(response.status_code, 404); self.assert_private(response)
