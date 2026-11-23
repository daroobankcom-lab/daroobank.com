from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection, IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from .identity import (IdentityConflict, IdentityError, digest, ingredient_snapshot, formulation_snapshot,
                       product_snapshot, package_snapshot, revise_identity, valid_identity_revision, create_ingredient,
                       create_formulation)
from .models import (IngredientDraft, IngredientRevision, FormulationDraft, FormulationRevision, ProductRevision,
                     IdentityProductDraft, IdentityPackageDraft, ProductPresentation)
from .test_identity import ALL, INGREDIENT, FORM, PRODUCT, build, user

REASON = 'اصلاح ساختگی مشخصات برای آزمون'


@override_settings(STAFF_PORTAL_ENABLED=True)
class ComponentRevisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = user('component-revision-author', *ALL)
        cls.editor = user('component-revision-editor', 'view_identityworkspace', 'add_identityworkspace')
        cls.viewer = user('component-revision-viewer', 'view_identityworkspace')
        cls.regular = user('component-revision-regular', *ALL, staff=False)
        cls.ingredient, cls.part, cls.formulation, cls.product, cls.package = build(cls.author)
        cls.parents = {'ingredient': cls.ingredient, 'formulation': cls.formulation, 'product': cls.product}
        cls.snapshots = {'ingredient': ingredient_snapshot, 'formulation': formulation_snapshot, 'product': product_snapshot}
        cls.models = {'ingredient': IngredientRevision, 'formulation': FormulationRevision, 'product': ProductRevision}
        cls.data = {'ingredient': {**INGREDIENT, 'name_fa': 'نام اصلاحی ماده'},
                    'formulation': {**FORM, 'name': 'نام اصلاحی فرمول'},
                    'product': {**PRODUCT, 'name': 'نام اصلاحی فرآورده'}}

    def args(self, kind, **kwargs):
        args = {'actor': self.editor, 'kind': kind, 'parent_id': self.parents[kind].pk, 'data': self.data[kind],
                'change_reason': REASON, 'expected_graph_hash': digest(self.snapshots[kind](self.parents[kind]))}
        if kind == 'formulation': args['components'] = [dict(self.part)]
        return {**args, **kwargs}

    def test_three_revisions_do_not_rewire_existing_dependants(self):
        package_graph = package_snapshot(self.package)
        for kind in self.parents:
            with self.subTest(kind=kind):
                old = self.snapshots[kind](self.parents[kind])
                child = revise_identity(**self.args(kind))
                link = self.models[kind].objects.get(child=child)
                self.assertTrue(valid_identity_revision(kind, link, child.pk))
                self.assertEqual(self.snapshots[kind](self.parents[kind]), old)
                self.assertEqual(link.recorded_by_id, self.editor.pk)
                with self.assertRaises(ValidationError): link.save()
                with self.assertRaises(ValidationError): link.delete()
                with self.assertRaises(ProtectedError): type(child).objects.filter(pk=child.pk).delete()
                if kind == 'formulation':
                    self.assertEqual(child.components.get().ingredient_id, self.ingredient.pk)
                if kind == 'product': self.assertEqual(child.formulation_id, self.formulation.pk)
        self.package.refresh_from_db()
        self.assertEqual(package_snapshot(self.package), package_graph)
        self.assertEqual(ProductPresentation.objects.count(), 0)

    def test_revisions_do_not_change_existing_public_catalog(self):
        public = ProductPresentation.objects.create(name_fa='داروی عمومی ساختگی', name_en='Public Synthetic',
            manufacturer='سازنده فرضی', strength='1 mg', dosage_form='قرص', package_description='10 عدد',
            irc='001', source_name='منبع ساختگی', source_url='https://example.org/public',
            verified_at=timezone.now(), published=True)
        before = self.client.get('/api/v1/search/', {'q': 'Public Synthetic'})
        self.assertEqual(before.status_code, 200)
        fields = ProductPresentation.objects.values().get(pk=public.pk)
        for kind in self.parents: revise_identity(**self.args(kind))
        self.assertEqual(ProductPresentation.objects.values().get(pk=public.pk), fields)
        after = self.client.get('/api/v1/search/', {'q': 'Public Synthetic'})
        self.assertEqual(after.status_code, 200)
        self.assertEqual(after.json(), before.json())
        self.assertNotContains(after, 'نام اصلاحی ماده')
        self.assertNotContains(after, 'نام اصلاحی فرآورده')

    def test_validate_bounds_immutability_conflicts_and_rollback(self):
        for kind in self.parents:
            for actor in (self.viewer, self.regular):
                with self.subTest(kind=kind, actor=actor.username), self.assertRaises(PermissionDenied):
                    revise_identity(**self.args(kind, actor=actor))
            for changes in ({'parent_id': 999999}, {'expected_graph_hash': 'f'*64}, {'change_reason': 'small'}):
                with self.subTest(kind=kind, changes=changes), self.assertRaises(IdentityConflict):
                    revise_identity(**self.args(kind, **changes))
            original_data = {'ingredient': INGREDIENT, 'formulation': FORM, 'product': PRODUCT}[kind]
            with self.assertRaises(IdentityError): revise_identity(**self.args(kind, data=original_data))
            count = type(self.parents[kind]).objects.count()
            with patch(f'catalog.identity.{self.models[kind].__name__}.objects.create', side_effect=RuntimeError):
                with self.assertRaises(RuntimeError): revise_identity(**self.args(kind))
            self.assertEqual(type(self.parents[kind]).objects.count(), count)
            self.assertFalse(self.models[kind].objects.exists())
        with self.assertRaises(IdentityError): revise_identity(**{**self.args('ingredient'), 'kind': 'package'})
        with self.assertRaises(IdentityError): revise_identity(**self.args('ingredient', components=[self.part]))
        with self.assertRaises(IdentityError): revise_identity(**self.args('formulation', components=[]))
        with self.assertRaises(IdentityError): revise_identity(**self.args('formulation', components=[{**self.part, 'ingredient_id': 999999}]))
        with self.assertRaises(IdentityError): revise_identity(**self.args('product', data={**PRODUCT, 'source_url': 'https://example.org/?token=x'}))

    def test_formulation_fixed_ingredients_and_strength_changes(self):
        # A numeric change is a new formulation assertion, not a claim of equivalence.
        new = revise_identity(**self.args('formulation', data=FORM,
                                         components=[{**self.part, 'numerator': Decimal('3')}]))
        self.assertEqual(new.components.get().numerator, Decimal('3'))
        self.assertTrue(valid_identity_revision('formulation', FormulationRevision.objects.get(child=new), new.pk))
        other = create_ingredient(actor=self.author, data={**INGREDIENT, 'name_fa': 'ماده دوم'})
        two = create_formulation(actor=self.author, data=FORM, components=[self.part, {**self.part, 'ingredient_id': other.pk}])
        with self.assertRaises(IdentityError):
            revise_identity(actor=self.editor, kind='formulation', parent_id=two.pk, data=FORM, change_reason=REASON,
                expected_graph_hash=digest(formulation_snapshot(two)), components=[{**self.part, 'ingredient_id': other.pk}, self.part])

    def test_corrupt_links_are_hidden_and_not_reusable(self):
        for kind in self.parents:
            child = revise_identity(**self.args(kind))
            link = self.models[kind].objects.get(child=child)
            self.assertFalse(valid_identity_revision('bad', link, child.pk))
            self.models[kind].objects.filter(pk=link.pk).update(change_reason='اطلاعات ناسازگار محرمانه')
            link.refresh_from_db()
            self.assertFalse(valid_identity_revision(kind, link, child.pk))
            self.client.force_login(self.viewer)
            response = self.client.get(reverse('staff_identity_detail', args=[kind, child.pk]))
            self.assertContains(response, 'پیوند نسخه پیشین ناسازگار')
            self.assertNotContains(response, 'اطلاعات ناسازگار محرمانه')
            response = self.client.get(reverse('staff_identity_detail', args=[kind, self.parents[kind].pk]))
            self.assertContains(response, 'پیوند نسخه اصلاحی ناسازگار')
            self.assertNotContains(response, 'اطلاعات ناسازگار محرمانه')
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.models[kind].objects.filter(pk=link.pk).update(parent=child, child=self.parents[kind])
            with self.assertRaises(IntegrityError), transaction.atomic():
                self.models[kind].objects.create(parent=self.parents[kind], child=child, recorded_by=self.editor,
                    change_reason=REASON, parent_graph_sha256='a'*64, child_graph_sha256='a'*64, payload_sha256='a'*64)

    def test_web_revision_forms_permissions_csrf_and_conflicts(self):
        for kind in self.parents:
            parent = self.parents[kind]
            path = reverse('staff_identity_revise_component', args=[kind, parent.pk])
            self.client.logout(); self.assertEqual(self.client.get(path).status_code, 302)
            self.client.force_login(self.viewer); self.assertEqual(self.client.get(path).status_code, 403)
            self.client.force_login(self.regular); self.assertEqual(self.client.get(path).status_code, 403)
            self.client.force_login(self.editor)
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response['Cache-Control'])
            self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
            payload = {**self.data[kind], 'synthetic_ack': 'on', 'change_reason': REASON,
                       'expected_graph_hash': digest(self.snapshots[kind](parent))}
            if kind == 'formulation':
                self.assertEqual(len(response.context['parts'].forms), 5)
                self.assertEqual(response.context['parts'].initial_form_count(), 1)
                payload.update({'parts-TOTAL_FORMS': '5', 'parts-INITIAL_FORMS': '1',
                                **{f'parts-0-{key}': str(value) for key, value in self.part.items()}})
            if kind == 'product':
                self.assertNotContains(response, 'name="formulation_id"')
                payload['formulation_id'] = '999999'
            csrf_client = Client(enforce_csrf_checks=True); csrf_client.force_login(self.editor)
            self.assertEqual(csrf_client.post(path, payload).status_code, 403)
            with override_settings(STAFF_PORTAL_ENABLED=False): self.assertEqual(self.client.get(path).status_code, 404)
            response = self.client.post(path, payload)
            self.assertEqual(response.status_code, 302, response.content.decode())
            link = self.models[kind].objects.get()
            self.assertRedirects(response, reverse('staff_identity_detail', args=[kind, link.child_id]))
            self.assertContains(self.client.get(response.url), reverse('staff_identity_detail', args=[kind, parent.pk]))
            self.assertContains(self.client.get(reverse('staff_identity_detail', args=[kind, parent.pk])), response.url)
            self.assertNotContains(self.client.get('/'), REASON)
            self.assertEqual(self.client.post(path, {**payload, 'expected_graph_hash': 'f'*64}).status_code, 409)
        self.assertEqual(self.client.get(reverse('staff_identity_revise_component', args=['package', self.package.pk])).status_code, 404)

    def test_formulation_tampered_management_and_composition_rejected(self):
        self.client.force_login(self.editor)
        path = reverse('staff_identity_revise_component', args=['formulation', self.formulation.pk])
        base = {**self.data['formulation'], 'synthetic_ack': 'on', 'change_reason': REASON,
                'expected_graph_hash': digest(formulation_snapshot(self.formulation)),
                **{f'parts-0-{key}': str(value) for key, value in self.part.items()}}
        for management in ({}, {'parts-TOTAL_FORMS': '0', 'parts-INITIAL_FORMS': '0'},
                           {'parts-TOTAL_FORMS': '5', 'parts-INITIAL_FORMS': '0'},
                           {'parts-TOTAL_FORMS': '6', 'parts-INITIAL_FORMS': '1'}):
            response = self.client.post(path, {**base, **management})
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context['parts'].non_form_errors())
            self.assertFalse(FormulationRevision.objects.exists())
        response = self.client.post(path, {**base, 'parts-TOTAL_FORMS': '5', 'parts-INITIAL_FORMS': '1',
                                           'parts-0-ingredient_id': '99999'})
        self.assertContains(response, 'مواد و ترتیب آن‌ها باید ثابت بماند')
        self.assertFalse(FormulationRevision.objects.exists())

    def test_revision_keyset_pagination_and_bad_cursor(self):
        links = []
        for i in range(22):
            child = revise_identity(**self.args('ingredient', data={**INGREDIENT, 'name_fa': f'ماده اصلاحی {i}'}))
            links.append(IngredientRevision.objects.get(child=child))
        self.client.force_login(self.viewer)
        path = reverse('staff_identity_detail', args=['ingredient', self.ingredient.pk])
        with CaptureQueriesContext(connection) as queries:
            page1 = self.client.get(path)
        self.assertLessEqual(len(queries), 10)
        self.assertEqual([x.pk for x in page1.context['child_links']], [x.pk for x in links[::-1][:10]])
        cursor = page1.context['next_revision_before']
        revise_identity(**self.args('ingredient', data={**INGREDIENT, 'name_fa': 'ماده اصلاحی تازه'}))
        page2 = self.client.get(path, {'revisions_before': cursor})
        self.assertEqual([x.pk for x in page2.context['child_links']], [x.pk for x in links[::-1][10:20]])
        page3 = self.client.get(path, {'revisions_before': page2.context['next_revision_before']})
        self.assertEqual([x.pk for x in page3.context['child_links']], [x.pk for x in links[::-1][20:]])
        self.assertIsNone(page3.context['next_revision_before'])
        self.assertContains(page3, 'جدیدترین نسخه‌ها')
        for invalid in ['0', '-1', '١', '9'*20]:
            response = self.client.get(path, {'revisions_before': invalid})
            self.assertEqual(response.status_code, 400)
            self.assertIn('no-store', response['Cache-Control'])

    def test_web_five_component_revision_keeps_all_ingredients(self):
        parts = [dict(self.part)]
        for i in range(4):
            ingredient = create_ingredient(actor=self.author, data={**INGREDIENT, 'name_fa': f'ماده فرضی {i}'})
            parts.append({**self.part, 'ingredient_id': ingredient.pk})
        parent = create_formulation(actor=self.author, data=FORM, components=parts)
        self.client.force_login(self.editor)
        path = reverse('staff_identity_revise_component', args=['formulation', parent.pk])
        response = self.client.get(path)
        self.assertEqual(len(response.context['parts'].forms), 5)
        self.assertEqual(response.context['parts'].initial_form_count(), 5)
        payload = {**FORM, 'synthetic_ack': 'on', 'change_reason': REASON,
                   'expected_graph_hash': digest(formulation_snapshot(parent)),
                   'parts-TOTAL_FORMS': '5', 'parts-INITIAL_FORMS': '5',
                   **{f'parts-{i}-{key}': str(value) for i, part in enumerate(parts) for key, value in part.items()}}
        payload['parts-4-numerator'] = '7.0000'
        incomplete = {key: value for key, value in payload.items() if key != 'parts-3-denominator'}
        self.assertEqual(self.client.post(path, incomplete).status_code, 200)
        self.assertFalse(FormulationRevision.objects.exists())
        response = self.client.post(path, payload)
        self.assertEqual(response.status_code, 302)
        child = FormulationRevision.objects.get(parent=parent).child
        child_parts = list(child.components.order_by('ordinal'))
        self.assertEqual([c.ingredient_id for c in child_parts], [part['ingredient_id'] for part in parts])
        self.assertEqual(child_parts[-1].numerator, Decimal('7'))

    def test_revision_link_reason_is_escaped(self):
        child = revise_identity(**self.args('product', change_reason='<script>synthetic text</script>'))
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_identity_detail', args=['product', child.pk]))
        self.assertContains(response, '&lt;script&gt;synthetic text&lt;/script&gt;')
        self.assertNotContains(response, '<script>synthetic text</script>')

    def test_changing_parent_or_child_suppresses_revision(self):
        child = revise_identity(**self.args('ingredient'))
        path = reverse('staff_identity_detail', args=['ingredient', self.ingredient.pk])
        IngredientDraft.objects.filter(pk=child.pk).update(name_fa='متن ناسازگار محرمانه')
        self.client.force_login(self.viewer)
        response = self.client.get(path)
        self.assertContains(response, 'پیوند نسخه اصلاحی ناسازگار')
        self.assertNotContains(response, 'متن ناسازگار محرمانه')
        self.assertNotContains(response, REASON)
        IngredientDraft.objects.filter(pk=self.ingredient.pk).update(name_fa='متن ناسازگار دیگر')
        self.client.force_login(self.editor)
        response = self.client.get(reverse('staff_identity_revise_component', args=['ingredient', self.ingredient.pk]))
        self.assertContains(response, 'رکورد یا وابستگی آن ناسازگار است')
        self.assertNotContains(response, 'متن ناسازگار دیگر')


class ConcurrentComponentRevisionTests(TransactionTestCase):
    def setUp(self):
        self.author = user('component-race-author', *ALL)
        self.actors = [user(f'component-race-{i}', *ALL) for i in range(2)]
        self.ingredient, self.part, self.formulation, self.product, self.package = build(self.author)

    def race(self, functions):
        barrier = Barrier(2, timeout=10)
        def worker(index):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.actors[index].pk)
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                barrier.wait()
                try:
                    functions[index](actor)
                    return 'created'
                except IdentityConflict:
                    return 'conflict'
            finally:
                connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(worker, range(2)))

    def test_same_parent_parallel_branches_for_each_type(self):
        for kind, obj, fields, fn, link_model in [
            ('ingredient', self.ingredient, INGREDIENT, ingredient_snapshot, IngredientRevision),
            ('formulation', self.formulation, FORM, formulation_snapshot, FormulationRevision),
            ('product', self.product, PRODUCT, product_snapshot, ProductRevision),
        ]:
            fingerprint = digest(fn(obj))
            def operation(index):
                def call(actor):
                    data = {**fields, ('name_fa' if kind == 'ingredient' else 'name'): f'نام ساختگی شاخه {index}'}
                    revise_identity(actor=actor, kind=kind, parent_id=obj.pk, data=data, change_reason=REASON,
                        expected_graph_hash=fingerprint, components=[self.part] if kind == 'formulation' else None)
                return call
            with self.subTest(kind=kind):
                self.assertEqual(self.race([operation(0), operation(1)]), ['created', 'created'])
                links = link_model.objects.filter(parent=obj)
                self.assertEqual(links.count(), 2)
                for link in links: self.assertTrue(valid_identity_revision(kind, link, link.child_id))

    def test_reverse_order_ingredient_locks_do_not_deadlock(self):
        other = create_ingredient(actor=self.author, data={**INGREDIENT, 'name_fa': 'ماده دوم ساختگی'})
        second_part = {**self.part, 'ingredient_id': other.pk}
        first = create_formulation(actor=self.author, data=FORM, components=[self.part, second_part])
        second = create_formulation(actor=self.author, data=FORM, components=[second_part, self.part])
        hashes = [digest(formulation_snapshot(first)), digest(formulation_snapshot(second))]
        def operation(index):
            def call(actor):
                parent, components = [(first, [self.part, second_part]), (second, [second_part, self.part])][index]
                revise_identity(actor=actor, kind='formulation', parent_id=parent.pk,
                    data={**FORM, 'name': f'نام اصلاحی ساختگی {index}'}, components=components,
                    change_reason=REASON, expected_graph_hash=hashes[index])
            return call
        self.assertEqual(self.race([operation(0), operation(1)]), ['created', 'created'])
        self.assertEqual(FormulationRevision.objects.count(), 2)
