from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from decimal import Decimal
from threading import Barrier
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import close_old_connections, connection
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from .identity import (IdentityConflict, IdentityError, create_ingredient, create_formulation, create_product,
                       create_package, review_package, digest, package_snapshot, safe_snapshot, valid_review_snapshot)
from .models import (IngredientDraft, FormulationDraft, FormulationComponent, IdentityProductDraft,
                     IdentityPackageDraft, IdentityPackageReview, ProductPresentation)

SOURCE = {'source_name': 'منبع ساختگی', 'source_url': 'https://example.org/fake'}
INGREDIENT = {'name_fa': 'ماده ساختگی محرمانه', 'name_en': 'Synthetic ingredient', **SOURCE}
FORM = {'name': 'فرمول فرضی', 'dosage_form': 'قرص', 'route': 'خوراکی', **SOURCE}
PRODUCT = {'name': 'فرآورده فرضی', 'brand': '', 'manufacturer': 'سازنده فرضی', **SOURCE}
PACKAGE = {'description': 'بسته فرضی', 'quantity': Decimal('10'), 'quantity_unit': 'عدد', 'irc': '', **SOURCE}


def build(actor):
    ingredient = create_ingredient(actor=actor, data=INGREDIENT)
    part = {'ingredient_id': ingredient.pk, 'numerator': Decimal('2.5'), 'numerator_unit': 'mg',
            'denominator': Decimal('1'), 'denominator_unit': 'tablet'}
    form = create_formulation(actor=actor, data=FORM, components=[part])
    product = create_product(actor=actor, data=PRODUCT, formulation_id=form.pk)
    package = create_package(actor=actor, data=PACKAGE, product_id=product.pk)
    return ingredient, part, form, product, package


def user(name, *permissions, staff=True):
    actor = get_user_model().objects.create_user(name, password='test-only', is_staff=staff)
    actor.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog', codename__in=permissions))
    return actor

ALL = ('view_identityworkspace', 'add_identityworkspace', 'review_identityworkspace')


@override_settings(STAFF_PORTAL_ENABLED=True)
class IdentityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = user('identity-author', *ALL)
        cls.reviewer = user('identity-reviewer', 'view_identityworkspace', 'review_identityworkspace')
        cls.viewer = user('identity-viewer', 'view_identityworkspace')
        cls.regular = user('identity-regular', *ALL, staff=False)
        cls.ingredient, cls.part, cls.formulation, cls.product, cls.package = build(cls.author)

    def test_chain_snapshot_review_and_immutability(self):
        graph = package_snapshot(self.package)
        self.assertEqual(graph['product']['formulation']['ingredients'][0]['name_fa'], INGREDIENT['name_fa'])
        self.assertEqual(graph['quantity'], '10.0000')
        event = review_package(actor=self.reviewer, package_id=self.package.pk, decision='defer',
            reason='دلایل ساختگی برای بررسی بیشتر', expected_review=0, expected_graph_hash=digest(graph))
        self.assertEqual(event.graph_snapshot, graph)
        with self.assertRaises(IdentityConflict):
            review_package(actor=self.reviewer, package_id=self.package.pk, decision='reject',
                reason='دلایل ساختگی برای بررسی بیشتر', expected_review=0, expected_graph_hash=digest(graph))
        with self.assertRaises(PermissionDenied):
            review_package(actor=self.author, package_id=self.package.pk, decision='defer',
                reason='دلایل ساختگی برای بررسی بیشتر', expected_review=event.pk, expected_graph_hash=digest(graph))
        with self.assertRaises(ValidationError): self.ingredient.save()
        with self.assertRaises(ValidationError): event.delete()
        self.assertEqual(ProductPresentation.objects.count(), 0)

    def test_validation_permissions_and_atomicity(self):
        with self.assertRaises(PermissionDenied): create_ingredient(actor=self.viewer, data=INGREDIENT)
        with self.assertRaises(PermissionDenied): create_ingredient(actor=self.regular, data=INGREDIENT)
        for url in ('http://example.org', 'https://user:pass@example.org', 'https://example.org/?secret=1', 'https://example.org/#x'):
            with self.assertRaises(IdentityError): create_ingredient(actor=self.author, data={**INGREDIENT, 'source_url': url})
        for amount in [Decimal('0'), Decimal('NaN'), Decimal('1.00001'), Decimal('100000000')]:
            with self.assertRaises(IdentityError): create_formulation(actor=self.author, data=FORM, components=[{**self.part, 'numerator': amount}])
        with self.assertRaises(IdentityError): create_formulation(actor=self.author, data=FORM, components=[self.part, self.part])
        with self.assertRaises(IdentityConflict): create_formulation(actor=self.author, data=FORM, components=[{**self.part, 'ingredient_id': 999999}])
        with self.assertRaises(IdentityConflict): create_product(actor=self.author, data=PRODUCT, formulation_id=999999)
        with self.assertRaises(IdentityConflict): create_package(actor=self.author, data=PACKAGE, product_id=999999)
        with self.assertRaises(IdentityConflict): review_package(actor=self.reviewer, package_id=999999, decision='defer',
            reason='دلایل ساختگی برای بررسی بیشتر', expected_review=0, expected_graph_hash='a'*64)
        count = FormulationDraft.objects.count()
        with patch('catalog.identity.FormulationComponent.objects.create', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError): create_formulation(actor=self.author, data=FORM, components=[self.part])
        self.assertEqual(FormulationDraft.objects.count(), count)

    def test_corruption_hides_entire_graph(self):
        IngredientDraft.objects.filter(pk=self.ingredient.pk).update(name_fa='اطلاعات ناسازگار محرمانه')
        self.package.refresh_from_db()
        self.assertIsNone(safe_snapshot(self.package, package_snapshot))
        with self.assertRaises(IdentityConflict): create_product(actor=self.author, data=PRODUCT, formulation_id=self.formulation.pk)
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_identity_detail', args=['package', self.package.pk]))
        self.assertContains(response, 'ناسازگار')
        self.assertNotContains(response, 'اطلاعات ناسازگار محرمانه')
        self.assertNotContains(response, PRODUCT['name'])
        response = self.client.get(reverse('staff_identity_list') + '?kind=ingredient')
        self.assertNotContains(response, 'اطلاعات ناسازگار محرمانه')

    def test_web_permissions_headers_gate_csrf_and_public_isolation(self):
        path = reverse('staff_identity_list')
        response = self.client.get(path)
        self.assertEqual(response.status_code, 302)
        self.assertIn('no-store', response['Cache-Control'])
        self.client.force_login(self.regular)
        self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.viewer)
        response = self.client.get(path)
        self.assertContains(response, INGREDIENT['name_fa'])
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')
        self.assertEqual(response['Referrer-Policy'], 'no-referrer')
        self.assertEqual(self.client.get(reverse('staff_identity_create', args=['ingredient'])).status_code, 403)
        self.assertEqual(self.client.post(reverse('staff_identity_review', args=[self.package.pk]), {}).status_code, 403)
        with override_settings(STAFF_PORTAL_ENABLED=False): self.assertEqual(self.client.get(path).status_code, 404)
        csrf_client = Client(enforce_csrf_checks=True); csrf_client.force_login(self.author)
        self.assertEqual(csrf_client.post(reverse('staff_identity_create', args=['ingredient']), {}).status_code, 403)
        self.assertNotContains(self.client.get('/'), INGREDIENT['name_fa'])

    def test_web_create_and_review_stale(self):
        self.client.force_login(self.author)
        response = self.client.post(reverse('staff_identity_create', args=['ingredient']), {**INGREDIENT, 'synthetic_ack': 'on'})
        self.assertEqual(response.status_code, 302)
        data = {**FORM, 'synthetic_ack': 'on', 'parts-TOTAL_FORMS': '5', 'parts-INITIAL_FORMS': '0',
                'parts-MIN_NUM_FORMS': '1', 'parts-MAX_NUM_FORMS': '5',
                **{f'parts-0-{key}': str(value) for key, value in self.part.items()}}
        response = self.client.post(reverse('staff_identity_create', args=['formulation']), data)
        self.assertEqual(response.status_code, 302, response.content.decode())
        self.client.force_login(self.reviewer)
        path = reverse('staff_identity_detail', args=['package', self.package.pk])
        self.assertContains(self.client.get(path), 'ثبت بازبینی')
        payload = {'decision': 'defer', 'reason': 'دلایل ساختگی برای بررسی بیشتر', 'expected_review': '0',
                   'expected_graph_hash': digest(package_snapshot(self.package))}
        review_url = reverse('staff_identity_review', args=[self.package.pk])
        self.assertEqual(self.client.post(review_url, payload).status_code, 302)
        self.assertEqual(self.client.post(review_url, payload).status_code, 409)
        self.client.force_login(self.author)
        self.assertEqual(self.client.post(review_url, payload).status_code, 403)

    def test_complete_web_chain_and_conflicting_graph(self):
        self.client.force_login(self.author)
        r = self.client.post(reverse('staff_identity_create', args=['product']),
                             {**PRODUCT, 'formulation_id': self.formulation.pk, 'synthetic_ack': 'on'})
        self.assertEqual(r.status_code, 302)
        product = IdentityProductDraft.objects.latest('pk')
        r = self.client.post(reverse('staff_identity_create', args=['package']),
                             {**PACKAGE, 'product_id': product.pk, 'synthetic_ack': 'on'})
        self.assertEqual(r.status_code, 302)
        package = IdentityPackageDraft.objects.latest('pk')
        graph_hash = digest(package_snapshot(package))
        IngredientDraft.objects.filter(pk=self.ingredient.pk).update(name_fa='ناسازگار جدید')
        self.client.force_login(self.reviewer)
        r = self.client.post(reverse('staff_identity_review', args=[package.pk]), {
            'decision': 'defer', 'reason': 'دلایل ساختگی برای بررسی بیشتر',
            'expected_review': '0', 'expected_graph_hash': graph_hash})
        self.assertEqual(r.status_code, 409)
        self.assertFalse(IdentityPackageReview.objects.filter(package=package).exists())

    def test_multiple_components_and_order_hash(self):
        other = create_ingredient(actor=self.author, data={**INGREDIENT, 'name_fa': 'ماده دیگر'})
        second = {**self.part, 'ingredient_id': other.pk}
        form = create_formulation(actor=self.author, data=FORM, components=[second, self.part])
        product = create_product(actor=self.author, data=PRODUCT, formulation_id=form.pk)
        package = create_package(actor=self.author, data=PACKAGE, product_id=product.pk)
        graph = package_snapshot(package)
        self.assertTrue(valid_review_snapshot(graph, package.pk))
        self.assertEqual([i['id'] for i in graph['product']['formulation']['ingredients']], [other.pk, self.ingredient.pk])
        FormulationComponent.objects.filter(formulation=form, ordinal=2).update(ordinal=3)
        self.assertIsNone(safe_snapshot(package, package_snapshot))

    def test_invalid_forms_and_bounded_pages(self):
        self.client.force_login(self.author)
        url = reverse('staff_identity_create', args=['ingredient'])
        self.assertEqual(self.client.post(url, INGREDIENT).status_code, 200)
        self.assertEqual(IngredientDraft.objects.count(), 1)
        for i in range(21): create_ingredient(actor=self.author, data={**INGREDIENT, 'name_fa': f'ماده ساختگی {i}'})
        r = self.client.get(reverse('staff_identity_list'))
        self.assertEqual(len(r.context['page'].object_list), 20)
        self.assertEqual(self.client.get(reverse('staff_identity_list') + '?kind=wrong').status_code, 400)
        self.assertEqual(self.client.get(reverse('staff_identity_detail', args=['unknown', 1])).status_code, 404)
        self.assertEqual(self.client.get(reverse('staff_identity_detail', args=['ingredient', 999999])).status_code, 404)
        self.assertEqual(self.client.get(reverse('staff_identity_review', args=[self.package.pk])).status_code, 405)

    def test_group_inactive_login_and_html_escaping(self):
        grouped = user('identity-group')
        group = Group.objects.create(name='identity viewers')
        group.permissions.add(Permission.objects.get(content_type__app_label='catalog', codename='view_identityworkspace'))
        grouped.groups.add(group)
        self.client.force_login(grouped)
        self.assertEqual(self.client.get(reverse('staff_identity_list')).status_code, 200)
        self.client.logout()
        response = self.client.post(reverse('staff_login'), {'username': 'identity-viewer', 'password': 'test-only'})
        self.assertRedirects(response, reverse('staff_identity_list'))
        inactive = user('identity-inactive', *ALL)
        inactive.is_active = False; inactive.save()
        self.client.force_login(inactive)
        self.assertNotEqual(self.client.get(reverse('staff_identity_list')).status_code, 200)
        create_ingredient(actor=self.author, data={**INGREDIENT, 'name_fa': '<script>alert(1)</script>'})
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_identity_list'))
        self.assertNotContains(response, '<script>alert(1)</script>')
        self.assertContains(response, '&lt;script&gt;alert(1)&lt;/script&gt;', html=False)

    def test_review_graph_validation_and_readable_chain(self):
        graph = package_snapshot(self.package)
        self.assertTrue(valid_review_snapshot(graph, self.package.pk))
        cases = []
        g = deepcopy(graph); g['product']['formulation']['ingredients'][0]['name_fa'] = 'داده ناسازگار'; cases.append(g)
        g = deepcopy(graph); g['product']['formulation']['components'][0]['numerator'] = '1e99999999'; cases.append(g)
        g = deepcopy(graph); g['product']['formulation']['components'][0]['numerator'] = '02.5000'; cases.append(g)
        g = deepcopy(graph); g['product']['formulation']['components'][0]['numerator'] = '0.0000'; cases.append(g)
        g = deepcopy(graph); g['product']['formulation']['components'][0]['ingredient_id'] = True; cases.append(g)
        g = deepcopy(graph); g['product']['formulation']['components'] = []; cases.append(g)
        g = deepcopy(graph); g['product']['formulation']['ingredients'] = 'wrong'; cases.append(g)
        g = deepcopy(graph); g['product']['formulation_id'] = True; cases.append(g)
        g = deepcopy(graph); g['product_id'] = True; cases.append(g)
        g = deepcopy(graph); g['quantity'] = '1e99999999'; cases.append(g)
        g = deepcopy(graph); g['product']['name'] = 'داده ناسازگار'; cases.append(g)
        g = deepcopy(graph); g['payload_sha256'] = 'bad'; cases.append(g)
        g = deepcopy(graph); g['id'] += 1; cases.append(g)
        g = deepcopy(graph); g['extra'] = 'private'; cases.append(g)
        cases.extend([{}, [], None, 'wrong'])
        for bad in cases:
            with self.subTest(bad=bad): self.assertFalse(valid_review_snapshot(bad, self.package.pk))
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_identity_detail', args=['package', self.package.pk]))
        for value in (INGREDIENT['name_fa'], FORM['name'], PRODUCT['name'], PACKAGE['description'], '2.5000'):
            self.assertContains(response, value)
        self.assertContains(response, reverse('staff_identity_detail', args=['ingredient', self.ingredient.pk]))
        self.assertNotContains(response, 'payload_sha256')

    def test_review_history_current_historical_and_inconsistent(self):
        graph = package_snapshot(self.package)
        event = review_package(actor=self.reviewer, package_id=self.package.pk, decision='defer',
            reason='دلایل ساختگی برای بررسی بیشتر', expected_review=0, expected_graph_hash=digest(graph))
        self.client.force_login(self.viewer)
        path = reverse('staff_identity_detail', args=['package', self.package.pk])
        self.assertContains(self.client.get(path), 'تصویر بازبینی با زنجیره فعلی همخوان است')
        old_product = create_product(actor=self.author, data={**PRODUCT, 'name': '<script>old</script>'}, formulation_id=self.formulation.pk)
        old_package = create_package(actor=self.author, data=PACKAGE, product_id=old_product.pk)
        other = package_snapshot(old_package)
        other['id'] = self.package.pk
        self.assertTrue(valid_review_snapshot(other, self.package.pk))
        IdentityPackageReview.objects.filter(pk=event.pk).update(graph_snapshot=other, graph_sha256=digest(other))
        response = self.client.get(path)
        self.assertContains(response, 'تصویر تاریخی با زنجیره فعلی متفاوت است')
        self.assertContains(response, event.reason)
        self.assertContains(response, '&lt;script&gt;old&lt;/script&gt;')
        self.assertNotContains(response, '<script>old</script>')
        self.assertNotContains(response, reverse('staff_identity_detail', args=['product', old_product.pk]))
        other['product']['name'] = 'نام جعلی ناسازگار'
        IdentityPackageReview.objects.filter(pk=event.pk).update(graph_snapshot=other, graph_sha256=digest(other))
        response = self.client.get(path)
        self.assertContains(response, 'بازبینی ناسازگار')
        self.assertNotContains(response, event.reason)
        self.assertNotContains(response, 'نام جعلی ناسازگار')
        IdentityPackageReview.objects.filter(pk=event.pk).update(graph_snapshot=graph, graph_sha256=digest(graph), reviewer=self.author)
        response = self.client.get(path)
        self.assertContains(response, 'بازبینی ناسازگار')
        self.assertNotContains(response, event.reason)

    def test_invalid_current_chain_does_not_claim_no_reviews(self):
        graph = package_snapshot(self.package)
        review_package(actor=self.reviewer, package_id=self.package.pk, decision='defer',
            reason='دلایل ساختگی برای بررسی بیشتر', expected_review=0, expected_graph_hash=digest(graph))
        IngredientDraft.objects.filter(pk=self.ingredient.pk).update(name_fa='ناسازگار')
        self.client.force_login(self.viewer)
        response = self.client.get(reverse('staff_identity_detail', args=['package', self.package.pk]))
        self.assertContains(response, 'رکورد یا وابستگی آن ناسازگار است')
        self.assertNotContains(response, 'بازبینی‌ای ثبت نشده است')
        self.assertNotContains(response, 'دلایل ساختگی برای بررسی بیشتر')

    def test_review_history_keyset_pages_and_latest_review_token(self):
        graph = package_snapshot(self.package)
        events = IdentityPackageReview.objects.bulk_create([
            IdentityPackageReview(package=self.package, reviewer=self.reviewer, decision='defer',
                                  reason=f'دلیل ساختگی شمارۀ {i:02d} برای بررسی', graph_snapshot=graph,
                                  graph_sha256=digest(graph)) for i in range(52)
        ])
        other_package = build(self.author)[-1]
        other_graph = package_snapshot(other_package)
        IdentityPackageReview.objects.create(package=other_package, reviewer=self.reviewer, decision='defer',
            reason='متن خصوصی بسته دیگر است', graph_snapshot=other_graph, graph_sha256=digest(other_graph))
        self.client.force_login(self.reviewer)
        path = reverse('staff_identity_detail', args=['package', self.package.pk])
        first = self.client.get(path)
        self.assertEqual([r.pk for r in first.context['reviews']], [e.pk for e in events[::-1][:25]])
        self.assertEqual(first.context['review_form'].initial['expected_review'], events[-1].pk)
        self.assertContains(first, '?before=' + str(events[-25].pk))
        self.assertNotContains(first, 'متن خصوصی بسته دیگر است')
        # Insert after page one; keyset navigation must not skip/repeat older rows.
        new = review_package(actor=self.reviewer, package_id=self.package.pk, decision='defer',
            reason='بازبینی تازه ساختگی برای بررسی', expected_review=events[-1].pk, expected_graph_hash=digest(graph))
        second = self.client.get(path, {'before': events[-25].pk})
        self.assertEqual([r.pk for r in second.context['reviews']], [e.pk for e in events[::-1][25:50]])
        self.assertIsNone(second.context['review_form'])
        self.assertEqual(second['Referrer-Policy'], 'no-referrer')
        self.assertEqual(second['X-Robots-Tag'], 'noindex, nofollow')
        self.assertContains(second, 'ابتدا به تازه‌ترین بازبینی‌ها بازگردید')
        self.assertNotContains(second, 'name="expected_review"')
        third = self.client.get(path, {'before': events[-50].pk})
        self.assertEqual([r.pk for r in third.context['reviews']], [e.pk for e in events[::-1][50:]])
        self.assertIsNone(third.context['next_before'])
        self.assertContains(third, 'تازه‌ترین بازبینی‌ها')
        refreshed = self.client.get(path)
        self.assertEqual(refreshed.context['review_form'].initial['expected_review'], new.pk)
        payload = {'decision': 'defer', 'reason': 'دلایل ساختگی برای بررسی بیشتر',
                   'expected_review': events[-1].pk, 'expected_graph_hash': digest(graph)}
        response = self.client.post(reverse('staff_identity_review', args=[self.package.pk]), payload)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, 'صفحه را دوباره بارگذاری کنید', status_code=409)
        self.assertNotContains(response, 'name="expected_review"', status_code=409)

    def test_review_cursor_validation_auth_and_empty_page(self):
        path = reverse('staff_identity_detail', args=['package', self.package.pk])
        self.assertEqual(self.client.get(path, {'before': '1'}).status_code, 302)
        self.client.force_login(self.regular)
        self.assertEqual(self.client.get(path, {'before': '1'}).status_code, 403)
        self.client.force_login(self.viewer)
        for value in ['-1', '0', '1.0', '١', '9'*20, str(9223372036854775808), 'secret']:
            response = self.client.get(path, {'before': value})
            self.assertEqual(response.status_code, 400)
            self.assertIn('no-store', response['Cache-Control'])
            self.assertNotContains(response, value, status_code=400)
        response = self.client.get(path, {'before': '1'})
        self.assertContains(response, 'بازبینی قدیمی‌تری در این بخش یافت نشد')
        self.assertNotContains(response, 'بازبینی‌ای ثبت نشده است')
        csrf_client = Client(enforce_csrf_checks=True); csrf_client.force_login(self.reviewer)
        self.assertEqual(csrf_client.post(reverse('staff_identity_review', args=[self.package.pk]), {}).status_code, 403)
        with override_settings(STAFF_PORTAL_ENABLED=False):
            self.assertEqual(self.client.get(path, {'before': '1'}).status_code, 404)

    def test_invalid_review_on_older_page_is_hidden(self):
        graph = package_snapshot(self.package)
        events = IdentityPackageReview.objects.bulk_create([
            IdentityPackageReview(package=self.package, reviewer=self.reviewer, decision='defer',
                                  reason=f'راز ساختگی {i:02d} برای بررسی', graph_snapshot=graph,
                                  graph_sha256=digest(graph)) for i in range(26)
        ])
        IdentityPackageReview.objects.filter(pk=events[0].pk).update(graph_sha256='f'*64)
        self.client.force_login(self.viewer)
        path = reverse('staff_identity_detail', args=['package', self.package.pk])
        response = self.client.get(path, {'before': events[1].pk})
        self.assertContains(response, 'بازبینی ناسازگار')
        self.assertNotContains(response, events[0].reason)
        IngredientDraft.objects.filter(pk=self.ingredient.pk).update(name_fa='اطلاعات ناسازگار محرمانه')
        response = self.client.get(path, {'before': events[1].pk})
        self.assertNotContains(response, 'بازبینی ناسازگار')
        self.assertNotContains(response, events[0].reason)
        self.assertContains(response, 'رکورد یا وابستگی آن ناسازگار است')

    def test_component_order_and_modified_values_detected(self):
        self.assertIsNotNone(safe_snapshot(self.package, package_snapshot))
        FormulationComponent.objects.filter(formulation=self.formulation).update(numerator=Decimal('3'))
        self.package.refresh_from_db()
        self.assertIsNone(safe_snapshot(self.package, package_snapshot))


class ConcurrentIdentityTests(TransactionTestCase):
    def test_two_reviews_same_version_only_one_wins(self):
        author = user('identity-race-author', *ALL)
        actors = [user('identity-race-reviewer-' + str(i), 'view_identityworkspace', 'review_identityworkspace') for i in range(2)]
        package = build(author)[-1]
        fingerprint = digest(package_snapshot(package))
        barrier = Barrier(2, timeout=10)
        def worker(index):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=actors[index].pk)
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                    cursor.execute("SET statement_timeout = '10s'")
                barrier.wait()
                try:
                    review_package(actor=actor, package_id=package.pk, decision='defer',
                        reason='دلایل ساختگی برای بررسی بیشتر', expected_review=0, expected_graph_hash=fingerprint)
                    return 'created'
                except IdentityConflict: return 'conflict'
            finally: connection.close()
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(worker, range(2))), ['created', 'conflict'])
        self.assertEqual(IdentityPackageReview.objects.count(), 1)
