"""Synthetic limits for selected identity revision-link inspection reads."""
from decimal import Decimal

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from . import test_identity_lineage as fixtures
from .identity import (digest, ingredient_snapshot, formulation_snapshot, product_snapshot, package_snapshot,
                       revise_identity, revise_package, _revision_payload)
from .identity_lineage import inspect_lineage
from .models import IngredientRevision, FormulationRevision, ProductRevision, IdentityPackageRevision
from .test_identity import INGREDIENT, FORM, PRODUCT, PACKAGE


@override_settings(STAFF_PORTAL_ENABLED=True)
class IdentityRevisionBoundedReasonTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.IdentityLineageTests.setUpTestData.__func__(cls)
        cls.items = []
        for kind, parent, data, snapshot, model in [
            ('ingredient', cls.ingredient, INGREDIENT, ingredient_snapshot, IngredientRevision),
            ('formulation', cls.formulation, FORM, formulation_snapshot, FormulationRevision),
            ('product', cls.product, PRODUCT, product_snapshot, ProductRevision),
            ('package', cls.package, PACKAGE, package_snapshot, IdentityPackageRevision),
        ]:
            if kind == 'package':
                child = revise_package(actor=cls.editor, parent_id=parent.pk, data={**data, 'quantity': Decimal('20')},
                    change_reason=fixtures.REASON, expected_graph_hash=digest(snapshot(parent)), expected_review=0)
            else:
                key = 'name_fa' if kind == 'ingredient' else 'name'
                child = revise_identity(actor=cls.editor, kind=kind, parent_id=parent.pk,
                    data={**data, key: 'نام اصلاح‌شده ساختگی'}, change_reason=fixtures.REASON,
                    expected_graph_hash=digest(snapshot(parent)), components=[cls.part] if kind == 'formulation' else None)
            cls.items.append((kind, parent, child, model, model.objects.get(child=child)))

    def check_query(self, queries, model):
        link_queries = [q['sql'] for q in queries if f'FROM "{model._meta.db_table}"' in q['sql']]
        self.assertTrue(link_queries)
        for sql in link_queries:
            select = sql.split(' FROM ', 1)[0].lower()
            if 'select 1' in select:
                continue
            self.assertIn('substring', select)
            self.assertNotRegex(select, rf'(?:^select |, )"{model._meta.db_table}"\."change_reason"(?:,|$)')

    def test_oversized_reason_is_never_fetched_or_reflected_for_parent_child_and_lineage(self):
        self.client.force_login(self.viewer)
        self.viewer.has_perm('catalog.view_identityworkspace')
        for kind, parent, child, model, link in self.items:
            with self.subTest(kind=kind):
                model.objects.filter(pk=link.pk).update(change_reason='ر' * 1_000_000 + 'private-canary')
                for item in (parent, child):
                    with CaptureQueriesContext(connection) as queries:
                        response = self.client.get(reverse('staff_identity_detail', args=[kind, item.pk]))
                    self.assertContains(response, 'پیوند نسخه')
                    self.assertContains(response, 'ناسازگار است؛ جزئیات پنهان شد')
                    self.assertNotContains(response, 'private-canary')
                    self.assertIn('no-store', response['Cache-Control'])
                    self.check_query(queries, model)
                with CaptureQueriesContext(connection) as queries:
                    report = inspect_lineage(actor=self.viewer, kind=kind, anchor_id=child.pk)
                self.assertEqual(report['status'], 'inconsistent')
                self.assertEqual(report['rows'], [])
                self.check_query(queries, model)
                self.assertEqual(len(model.objects.get(pk=link.pk).change_reason), 1_000_000 + len('private-canary'))

    def test_valid_threshold_and_oversized_reason_keep_existing_classification(self):
        self.client.force_login(self.viewer)
        for kind, parent, child, model, link in self.items:
            with self.subTest(kind=kind):
                for length in (1000, 1001):
                    reason = 'ر' * length
                    payload = _revision_payload(link.parent_id, link.child_id, link.recorded_by_id, reason,
                                                link.parent_graph_sha256, link.child_graph_sha256)
                    model.objects.filter(pk=link.pk).update(change_reason=reason, payload_sha256=digest(payload))
                    report = inspect_lineage(actor=self.viewer, kind=kind, anchor_id=child.pk)
                    self.assertEqual(report['status'], 'no_parent' if length == 1000 else 'inconsistent')
                    response = self.client.get(reverse('staff_identity_detail', args=[kind, child.pk]))
                    self.assertEqual(response.context['parent_link'].safe, length == 1000)
                    if length == 1001:
                        self.assertNotContains(response, reason)

    def test_oversized_space_suffix_cannot_turn_into_valid_trimmed_prefix(self):
        for kind, parent, child, model, link in self.items:
            with self.subTest(kind=kind):
                reason = 'ر' * 12 + ' ' * 200_000 + 'final-canary'
                payload = _revision_payload(link.parent_id, link.child_id, link.recorded_by_id, reason,
                                            link.parent_graph_sha256, link.child_graph_sha256)
                model.objects.filter(pk=link.pk).update(change_reason=reason, payload_sha256=digest(payload))
                report = inspect_lineage(actor=self.viewer, kind=kind, anchor_id=child.pk)
                self.assertEqual(report['status'], 'inconsistent')
                self.client.force_login(self.viewer)
                response = self.client.get(reverse('staff_identity_detail', args=[kind, child.pk]))
                self.assertFalse(response.context['parent_link'].safe)
                self.assertNotContains(response, 'final-canary')

    def test_large_lookahead_reason_is_bounded_and_keeps_pagination(self):
        parent = self.ingredient
        for index in range(10):
            revise_identity(actor=self.editor, kind='ingredient', parent_id=parent.pk,
                data={**INGREDIENT, 'name_fa': f'نام آزمون {index}'}, change_reason=fixtures.REASON,
                expected_graph_hash=digest(ingredient_snapshot(parent)))
        oldest = IngredientRevision.objects.filter(parent=parent).order_by('pk').first()
        IngredientRevision.objects.filter(pk=oldest.pk).update(change_reason='ر' * 1_000_000 + 'sentinel-canary')
        from .revision_read import bounded_revision_reasons
        with CaptureQueriesContext(connection) as fetched:
            rows = list(bounded_revision_reasons(IngredientRevision.objects.filter(parent=parent).order_by('-pk'))[:11])
        self.assertEqual(len(fetched), 1)
        self.assertEqual(rows[-1].pk, oldest.pk)
        self.assertEqual(len(rows[-1]._reason_prefix), 1001)
        self.assertIn('change_reason', rows[-1].get_deferred_fields())
        self.client.force_login(self.viewer)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(reverse('staff_identity_detail', args=['ingredient', parent.pk]))
        self.check_query(queries, IngredientRevision)
        self.assertEqual(len(response.context['child_links']), 10)
        self.assertNotContains(response, 'sentinel-canary')
        cursor = response.context['next_revision_before']
        self.assertIsNotNone(cursor)
        page = self.client.get(reverse('staff_identity_detail', args=['ingredient', parent.pk]), {'revisions_before': cursor})
        self.assertEqual([item.pk for item in page.context['child_links']], [oldest.pk])
        self.assertFalse(page.context['child_links'][0].safe)
        self.assertNotContains(page, 'sentinel-canary')
