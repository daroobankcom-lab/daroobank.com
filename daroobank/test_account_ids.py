"""ID-only, current-account existence checks on synthetic data."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .account_checks import current_account_ids


class CurrentAccountIdsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.active = users.objects.create_user('ids-test-active', password='synthetic-secret')
        cls.inactive = users.objects.create_user('ids-test-inactive', is_active=False, is_staff=False)

    def test_invalid_inputs_and_empty_iterable_require_no_select(self):
        with self.assertNumQueries(0):
            self.assertEqual(current_account_ids([], using='default'), set())
            self.assertEqual(current_account_ids([None, -1, 0, True, False, '1', 2**63], using='default'), set())

    def test_only_primary_key_is_selected_in_one_query_and_inactive_counts(self):
        ids = [self.active.pk, self.active.pk, self.inactive.pk, 2_147_483_000, None]
        with CaptureQueriesContext(connection) as queries:
            found = current_account_ids(iter(ids), using='default')
        self.assertEqual(found, {self.active.pk, self.inactive.pk})
        self.assertEqual(len(queries), 1)
        selected = queries[0]['sql'].upper().split(' FROM ', 1)[0]
        self.assertIn('"ID"', selected)
        for name in ('PASSWORD', 'USERNAME', 'EMAIL', 'IS_ACTIVE', 'IS_STAFF'):
            self.assertNotIn(name, selected)

    def test_database_alias_is_forwarded(self):
        manager = get_user_model().objects
        with patch.object(manager, 'using', wraps=manager.using) as using:
            self.assertEqual(current_account_ids([self.active.pk], using='default'), {self.active.pk})
            using.assert_called_once_with('default')
