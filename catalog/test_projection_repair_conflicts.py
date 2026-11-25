"""Synthetic projection repair conflict boundaries, not a retry mechanism."""
import io
from unittest.mock import patch

from django.core.management import CommandError, call_command
from django.db import OperationalError, transaction
from django.db.models.query import QuerySet
from django.test import TestCase, override_settings

from .models import ProductPresentation
from .projection_repair import ProjectionRepairError, apply_projection, preview_projection


class DriverFailure(Exception):
    def __init__(self, code):
        self.sqlstate = code


def fail_with(code):
    try:
        raise DriverFailure(code)
    except DriverFailure as exc:
        raise OperationalError('sensitive synthetic driver detail') from exc


@override_settings(DEBUG=True, SECRET_KEY='synthetic-projection-conflict-key')
class ProjectionRepairConflictTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.product = ProductPresentation.objects.create(
            name_fa='فرآورده ساختگی', manufacturer='سازنده فرضی', strength='5 mg',
            dosage_form='قرص', package_description='10 عدد', irc='001',
            source_name='منبع ساختگی', source_url='https://example.org/synthetic')
        ProductPresentation.objects.filter(pk=cls.product.pk).update(irc='002')

    def plan(self):
        return preview_projection(presentation_id=self.product.pk)

    def test_selected_states_roll_back_update_before_domain_error(self):
        token = self.plan()['token']
        before = ProductPresentation.objects.values().get(pk=self.product.pk)
        update = QuerySet.update
        for code in ('55P03', '40P01', '40001'):
            def update_then_fail(query, **kwargs):
                update(query, **kwargs)
                fail_with(code)
            with self.subTest(code=code), patch.object(QuerySet, 'update', update_then_fail):
                with self.assertRaises(ProjectionRepairError) as caught:
                    apply_projection(presentation_id=self.product.pk, token=token, synthetic_confirmed=True)
                self.assertIsInstance(caught.exception.__cause__, OperationalError)
                self.assertNotIn('sensitive synthetic driver detail', str(caught.exception))
            self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)
            self.assertFalse(transaction.get_connection().needs_rollback)
        self.assertEqual(apply_projection(presentation_id=self.product.pk, token=token,
                                          synthetic_confirmed=True)['status'], 'repaired')

    def test_unselected_database_error_is_not_masked(self):
        token = self.plan()['token']
        before = ProductPresentation.objects.values().get(pk=self.product.pk)
        update = QuerySet.update
        def update_then_fail(query, **kwargs):
            update(query, **kwargs)
            fail_with('23505')
        with patch.object(QuerySet, 'update', update_then_fail):
            with self.assertRaises(OperationalError):
                apply_projection(presentation_id=self.product.pk, token=token, synthetic_confirmed=True)
        self.assertEqual(ProductPresentation.objects.values().get(pk=self.product.pk), before)

    def test_cli_selected_failure_is_generic_and_does_not_emit_partial_output(self):
        token = self.plan()['token']
        out = io.StringIO()
        with patch.object(QuerySet, 'update', side_effect=lambda **kwargs: fail_with('40P01')):
            with self.assertRaises(CommandError) as caught:
                call_command('repair_catalog_projection', presentation_id=self.product.pk, commit=True,
                             token=token, confirm_synthetic=True, stdout=out)
        self.assertNotIn('sensitive synthetic driver detail', str(caught.exception))
        self.assertNotIn(token, str(caught.exception))
        self.assertEqual(out.getvalue(), '')
