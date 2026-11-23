from copy import deepcopy
from decimal import Decimal
import time
from unittest.mock import patch

from django.contrib.auth.models import Group, Permission
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from .identity import (digest, ingredient_snapshot, formulation_snapshot, product_snapshot, package_snapshot,
                       revise_identity, revise_package, create_ingredient)
from .identity_lineage import (CURSOR_SALT, CURSOR_MAX_AGE, PAGE_SIZE, InvalidLineageCursor, LineageNotFound, inspect_lineage)
from .models import (IngredientDraft, IngredientRevision, IdentityPackageReview, IdentityPackageRevision,
                     FormulationRevision, ProductRevision, ProductPresentation, IdentityProductDraft)
from .test_identity import ALL, INGREDIENT, FORM, PRODUCT, PACKAGE, build, user

REASON = 'اصلاح کاملاً ساختگی برای آزمایش'


@override_settings(STAFF_PORTAL_ENABLED=True)
class IdentityLineageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = user('lineage-author', *ALL)
        cls.editor = user('lineage-editor', 'view_identityworkspace', 'add_identityworkspace')
        cls.viewer = user('lineage-viewer', 'view_identityworkspace')
        cls.no_view = user('lineage-no-view', 'add_identityworkspace')
        cls.regular = user('lineage-regular', *ALL, staff=False)
        cls.inactive = user('lineage-inactive', 'view_identityworkspace')
        cls.inactive.is_active = False; cls.inactive.save()
        cls.ingredient, cls.part, cls.formulation, cls.product, cls.package = build(cls.author)

    def ingredient_chain(self, count):
        chain = [self.ingredient]
        for i in range(count):
            parent = chain[-1]
            child = revise_identity(actor=self.editor, kind='ingredient', parent_id=parent.pk,
                data={**INGREDIENT, 'name_fa': f'نام ساختگی محرمانه {i}'}, change_reason=REASON,
                expected_graph_hash=digest(ingredient_snapshot(parent)))
            chain.append(child)
        return chain

    def test_each_type_inspection_and_no_write(self):
        parents = {'ingredient': self.ingredient, 'formulation': self.formulation,
                   'product': self.product, 'package': self.package}
        snapshots = {'ingredient': ingredient_snapshot, 'formulation': formulation_snapshot,
                     'product': product_snapshot, 'package': package_snapshot}
        for kind, parent in parents.items():
            graph_hash = digest(snapshots[kind](parent))
            if kind == 'package':
                child = revise_package(actor=self.editor, parent_id=parent.pk, data={**PACKAGE, 'quantity': Decimal('20')},
                    change_reason=REASON, expected_graph_hash=graph_hash, expected_review=0)
            else:
                original = {'ingredient': INGREDIENT, 'formulation': FORM, 'product': PRODUCT}[kind]
                key = 'name_fa' if kind == 'ingredient' else 'name'
                child = revise_identity(actor=self.editor, kind=kind, parent_id=parent.pk,
                    data={**original, key: 'نام ساختگی جدید'}, change_reason=REASON,
                    expected_graph_hash=graph_hash, components=[self.part] if kind == 'formulation' else None)
            counts = (IngredientRevision.objects.count(), FormulationRevision.objects.count(), ProductRevision.objects.count(),
                      IdentityPackageRevision.objects.count(), IdentityPackageReview.objects.count(), ProductPresentation.objects.count())
            report = inspect_lineage(actor=self.viewer, kind=kind, anchor_id=child.pk)
            self.assertEqual(report['rows'], [{'child_id': child.pk, 'parent_id': parent.pk, 'depth': 1}])
            self.assertEqual(report['status'], 'no_parent')
            self.assertIsNone(report['next_cursor'])
            self.assertEqual((IngredientRevision.objects.count(), FormulationRevision.objects.count(), ProductRevision.objects.count(),
                              IdentityPackageRevision.objects.count(), IdentityPackageReview.objects.count(), ProductPresentation.objects.count()), counts)
            self.client.force_login(self.viewer)
            path = reverse('staff_identity_lineage', args=[kind, child.pk])
            self.assertContains(self.client.get(reverse('staff_identity_detail', args=[kind, child.pk])), path)
            response = self.client.get(path)
            self.assertContains(response, f'شناسه {parent.pk}')
            self.assertNotContains(response, REASON)
            self.assertNotContains(response, 'نام ساختگی جدید')
            self.assertNotContains(response, 'https://example.org/fake')

    def test_deep_path_pagination_does_not_reveal_data_and_is_bounded(self):
        chain = self.ingredient_chain(PAGE_SIZE + 3)
        leaf = chain[-1]
        with CaptureQueriesContext(connection) as queries:
            first = inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=leaf.pk)
        self.assertLessEqual(len(queries), PAGE_SIZE * 3 + 6)
        self.assertEqual(first['status'], 'more')
        self.assertEqual(len(first['rows']), PAGE_SIZE)
        self.assertEqual([r['child_id'] for r in first['rows']], [x.pk for x in chain[:0:-1][:PAGE_SIZE]])
        token = first['next_cursor']
        data = signing.loads(token, salt=CURSOR_SALT)
        self.assertNotEqual(data['anchor_graph'], digest(ingredient_snapshot(leaf)))
        self.assertNotIn('نام', token)
        self.assertNotIn(REASON, token)
        second = inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=leaf.pk, cursor=token)
        self.assertEqual(second['status'], 'no_parent')
        self.assertEqual([r['depth'] for r in second['rows']], list(range(PAGE_SIZE + 1, PAGE_SIZE + 4)))
        self.assertEqual(second['rows'][-1]['parent_id'], chain[0].pk)
        self.assertIsNone(second['next_cursor'])
        self.client.force_login(self.viewer)
        path = reverse('staff_identity_lineage', args=['ingredient', leaf.pk])
        response = self.client.get(path)
        self.assertContains(response, 'بررسی بخش بعدی')
        self.assertNotContains(response, 'نام ساختگی محرمانه')
        response = self.client.get(path, {'cursor': token})
        self.assertContains(response, 'این به معنی اثبات منشأ')
        self.assertNotContains(response, 'نام ساختگی محرمانه')

    def test_stale_tampered_or_cross_bound_cursor_fails_closed(self):
        chain = self.ingredient_chain(PAGE_SIZE + 2)
        anchor = chain[-1]
        token = inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=anchor.pk)['next_cursor']
        for bad in [token + 'x', '.' + token, 'x'*1025, 'bad', None]:
            with self.subTest(bad=str(bad)[:10]), self.assertRaises(InvalidLineageCursor):
                inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=anchor.pk, cursor=bad)
        with self.assertRaises(InvalidLineageCursor):
            inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=chain[-2].pk, cursor=token)
        for field, value in [('depth', True), ('depth', 1), ('current', True), ('current', anchor.pk),
                             ('kind', 'product'), ('anchor_graph', 'x'*64)]:
            contents = deepcopy(signing.loads(token, salt=CURSOR_SALT)); contents[field] = value
            forged = signing.dumps(contents, salt=CURSOR_SALT)
            with self.subTest(field=field, value=value), self.assertRaises(InvalidLineageCursor):
                inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=anchor.pk, cursor=forged)
        self.client.force_login(self.viewer)
        path = reverse('staff_identity_lineage', args=['ingredient', anchor.pk])
        response = self.client.get(path, {'cursor': token + 'x'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotContains(response, token, status_code=400)
        current_id = signing.loads(token, salt=CURSOR_SALT)['current']
        IngredientDraft.objects.filter(pk=current_id).update(name_fa='ناسازگاری محرمانه')
        with self.assertRaises(InvalidLineageCursor):
            inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=anchor.pk, cursor=token)

    def test_expired_cursor_and_coherent_anchor_change_are_stale(self):
        chain = self.ingredient_chain(PAGE_SIZE + 1)
        anchor = chain[-1]
        token = inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=anchor.pk)['next_cursor']
        data = signing.loads(token, salt=CURSOR_SALT)
        with patch('django.core.signing.time.time', return_value=time.time() - CURSOR_MAX_AGE - 5):
            expired = signing.dumps(data, salt=CURSOR_SALT)
        with self.assertRaises(InvalidLineageCursor):
            inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=anchor.pk, cursor=expired)
        with patch('django.core.signing.time.time', return_value=time.time() + 60):
            future = signing.dumps(data, salt=CURSOR_SALT)
        with self.assertRaises(InvalidLineageCursor):
            inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=anchor.pk, cursor=future)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_identity_lineage', args=['ingredient', anchor.pk]), {'cursor': future})
        self.assertEqual(response.status_code, 400)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertNotContains(response, future, status_code=400)
        payload = {**INGREDIENT, 'name_fa': 'نام تغییر یافته ساختگی', 'recorded_by_id': self.editor.pk}
        IngredientDraft.objects.filter(pk=anchor.pk).update(name_fa=payload['name_fa'], payload_sha256=digest(payload))
        anchor.refresh_from_db()
        self.assertEqual(ingredient_snapshot(anchor)['name_fa'], payload['name_fa'])
        with self.assertRaises(InvalidLineageCursor):
            inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=anchor.pk, cursor=token)

    def test_continuations_are_not_a_snapshot_of_earlier_pages(self):
        chain = self.ingredient_chain(PAGE_SIZE + 2)
        token = inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=chain[-1].pk)['next_cursor']
        early = IngredientRevision.objects.get(child=chain[-1])
        IngredientRevision.objects.filter(pk=early.pk).update(change_reason='رشته تغییر یافته بعد از صفحه اول')
        # Earlier links are not revalidated: this is explicitly a non-snapshot diagnostic.
        later = inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=chain[-1].pk, cursor=token)
        self.assertEqual(later['status'], 'no_parent')
        self.assertEqual(len(later['rows']), 2)
        restarted = inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=chain[-1].pk)
        self.assertEqual(restarted['status'], 'inconsistent')

    def test_invalid_link_stops_and_hides_raw_data(self):
        chain = self.ingredient_chain(4)
        bad = IngredientRevision.objects.get(child=chain[2])
        IngredientRevision.objects.filter(pk=bad.pk).update(change_reason='رشته محرمانه ناسازگار')
        report = inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=chain[-1].pk)
        self.assertEqual(report['status'], 'inconsistent')
        self.assertEqual(len(report['rows']), 2)
        self.assertIsNone(report['next_cursor'])
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_identity_lineage', args=['ingredient', chain[-1].pk]))
        self.assertContains(response, 'ناسازگار است')
        self.assertNotContains(response, 'رشته محرمانه ناسازگار')
        self.assertNotContains(response, reverse('staff_identity_detail', args=['ingredient', chain[1].pk]))
        IngredientDraft.objects.filter(pk=chain[-1].pk).update(name_fa='نام ناسازگار محرمانه')
        report = inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=chain[-1].pk)
        self.assertEqual(report['status'], 'inconsistent')
        self.assertEqual(report['rows'], [])
        self.assertNotContains(self.client.get(reverse('staff_identity_lineage', args=['ingredient', chain[-1].pk])),
                               'نام ناسازگار محرمانه')

    def test_missing_related_rows_are_inconsistent_not_silently_absent(self):
        # Foreign keys are deferred in this PostgreSQL test transaction; repair the
        # synthetic violations before teardown so no invalid data is committed.
        gap = create_ingredient(actor=self.author, data={**INGREDIENT, 'name_fa': 'رکورد موقتی ساختگی'})
        gap_id = gap.pk
        IngredientDraft.objects.filter(pk=gap_id).delete()
        chain = self.ingredient_chain(1)
        link = IngredientRevision.objects.get(child=chain[-1])
        try:
            IngredientRevision.objects.filter(pk=link.pk).update(parent_id=gap_id)
            report = inspect_lineage(actor=self.viewer, kind='ingredient', anchor_id=chain[-1].pk)
            self.assertEqual(report['status'], 'inconsistent')
            self.assertEqual(report['rows'], [])
        finally:
            IngredientRevision.objects.filter(pk=link.pk).update(parent_id=self.ingredient.pk)
        try:
            IdentityProductDraft.objects.filter(pk=self.product.pk).update(formulation_id=9223372036854775807)
            report = inspect_lineage(actor=self.viewer, kind='product', anchor_id=self.product.pk)
            self.assertEqual(report['status'], 'inconsistent')
            self.assertEqual(report['rows'], [])
        finally:
            IdentityProductDraft.objects.filter(pk=self.product.pk).update(formulation_id=self.formulation.pk)

    def test_permissions_methods_gate_and_headers(self):
        path = reverse('staff_identity_lineage', args=['ingredient', self.ingredient.pk])
        for actor in (self.no_view, self.regular, self.inactive):
            with self.assertRaises(PermissionDenied): inspect_lineage(actor=actor, kind='ingredient', anchor_id=self.ingredient.pk)
        for kwargs in [{'kind': 'unknown', 'anchor_id': 1}, {'kind': 'ingredient', 'anchor_id': 0},
                       {'kind': 'ingredient', 'anchor_id': True}, {'kind': 'ingredient', 'anchor_id': 999999}]:
            with self.assertRaises(LineageNotFound): inspect_lineage(actor=self.viewer, **kwargs)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        self.assertIn('no-store', response['Cache-Control'])
        self.client.force_login(self.no_view); self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.regular); self.assertEqual(self.client.get(path).status_code, 403)
        group_viewer = user('lineage-group')
        group = Group.objects.create(name='lineage-viewers')
        group.permissions.add(Permission.objects.get(content_type__app_label='catalog', codename='view_identityworkspace'))
        group_viewer.groups.add(group)
        self.client.force_login(group_viewer)
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')
        self.assertEqual(self.client.post(path, {}).status_code, 405)
        with override_settings(STAFF_PORTAL_ENABLED=False): self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get(reverse('staff_identity_lineage', args=['unknown', 1])).status_code, 404)
