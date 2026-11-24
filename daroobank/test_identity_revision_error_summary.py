"""Error navigation on selected synthetic identity revision forms."""
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from catalog.identity import digest, formulation_snapshot, ingredient_snapshot, package_snapshot, product_snapshot, review_package
from catalog.models import (IngredientDraft, FormulationDraft, IdentityProductDraft, IdentityPackageDraft,
                            IngredientRevision, FormulationRevision, ProductRevision, IdentityPackageRevision, IdentityPackageReview)
from catalog.test_identity import ALL, FORM, INGREDIENT, PACKAGE, PRODUCT, build, user


@override_settings(STAFF_PORTAL_ENABLED=True)
class IdentityRevisionErrorSummaryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = user('revision-summary-author', *ALL)
        cls.ingredient, cls.part, cls.formulation, cls.product, cls.package = build(cls.author)

    def cases(self):
        common = {'synthetic_ack': 'on', 'change_reason': 'دلیل اصلاح ساختگی برای آزمون'}
        return (
            ('ingredient', reverse('staff_identity_revise_component', args=['ingredient', self.ingredient.pk]),
             IngredientDraft, {**INGREDIENT, **common, 'expected_graph_hash': digest(ingredient_snapshot(self.ingredient))}),
            ('formulation', reverse('staff_identity_revise_component', args=['formulation', self.formulation.pk]),
             FormulationDraft, {**FORM, **common, 'expected_graph_hash': digest(formulation_snapshot(self.formulation)),
               'parts-TOTAL_FORMS': '5', 'parts-INITIAL_FORMS': '1',
               **{f'parts-0-{key}': str(value) for key, value in self.part.items()}}),
            ('product', reverse('staff_identity_revise_component', args=['product', self.product.pk]),
             IdentityProductDraft, {**PRODUCT, **common, 'expected_graph_hash': digest(product_snapshot(self.product))}),
            ('package', reverse('staff_identity_revise', args=[self.package.pk]), IdentityPackageDraft,
             {**PACKAGE, **common, 'expected_graph_hash': digest(package_snapshot(self.package)), 'expected_review': '0'}),
        )

    def test_visible_hidden_errors_have_title_and_correct_summary_without_writes(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.author)
        for kind, url, model, data in self.cases():
            with self.subTest(kind=kind):
                get = client.get(url)
                self.assertNotContains(get, 'staff-form-errors')
                self.assertNotContains(get, 'خطا در فرم |')
                self.assertEqual(client.post(url, data).status_code, 403)
                response = client.post(url, {**data, 'change_reason': 'canary', 'expected_graph_hash': 'hidden-canary'},
                                       HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
                self.assertEqual(response.status_code, 200)
                html = response.content.decode()
                summary = html.split('<section id="staff-form-errors"', 1)[1].split('</section>', 1)[0]
                self.assertIn('خطا در فرم |', html)
                self.assertIn('href="#id_change_reason"', summary)
                self.assertIn('id_change_reason_error', html)
                self.assertIn('اطلاعات پنهان فرم معتبر نیست', summary)
                self.assertNotIn('href="#id_expected_graph_hash"', summary)
                self.assertNotIn('canary', summary)
                self.assertNotIn('hidden-canary', summary)
                self.assertEqual(model.objects.count(), 1)
                self.assertIn('no-store', response['Cache-Control'])
        for model in (IngredientRevision, FormulationRevision, ProductRevision, IdentityPackageRevision):
            self.assertEqual(model.objects.count(), 0)

    def test_formset_only_errors_and_broken_management_have_reachable_or_generic_guidance(self):
        self.client.force_login(self.author)
        _, url, _, data = self.cases()[1]
        response = self.client.post(url, {**data, 'parts-0-numerator': 'bad'})
        self.assertContains(response, 'خطا در فرم |')
        self.assertContains(response, 'href="#id_parts-0-numerator"')
        self.assertContains(response, 'id_parts-0-numerator_error')
        broken = self.client.post(url, {**data, 'parts-TOTAL_FORMS': '0'})
        self.assertContains(broken, 'خطا در فرم |')
        self.assertContains(broken, 'ساختار فرم را بررسی کنید')
        self.assertContains(broken, 'صفحه را دوباره باز کنید')
        self.assertNotContains(broken, 'href="#id_parts-0-numerator"')
        self.assertEqual(FormulationRevision.objects.count(), 0)

    def test_conflicts_hide_form_and_do_not_render_dead_links_or_values(self):
        self.client.force_login(self.author)
        for kind, url, model, data in self.cases():
            with self.subTest(kind=kind):
                response = self.client.post(url, {**data, 'expected_graph_hash': '0' * 64,
                                                 'change_reason': 'private-canary دلیل ساختگی'})
                self.assertEqual(response.status_code, 409)
                html = response.content.decode()
                self.assertIn('خطا در فرم |', html)
                self.assertIn('صفحه را دوباره بارگذاری کنید', html)
                self.assertNotIn('href="#id_change_reason"', html)
                self.assertNotIn('name="change_reason"', html)
                self.assertNotIn('private-canary', html)
                self.assertEqual(model.objects.count(), 1)

    def test_invalid_latest_review_hides_form_without_dangling_summary_links(self):
        reviewer = user('revision-summary-reviewer', 'view_identityworkspace', 'review_identityworkspace')
        event = review_package(actor=reviewer, package_id=self.package.pk, decision='defer',
                               reason='دلیل ساختگی برای بازبینی', expected_review=0,
                               expected_graph_hash=digest(package_snapshot(self.package)))
        IdentityPackageReview.objects.filter(pk=event.pk).update(graph_snapshot={'canary': 'review-snapshot-canary'})
        self.client.force_login(self.author)
        _, url, _, data = self.cases()[3]
        response = self.client.post(url, {**data, 'change_reason': 'short', 'expected_review': str(event.pk)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'آخرین بازبینی ناسازگار است')
        self.assertNotContains(response, 'href="#id_change_reason"')
        self.assertNotContains(response, 'name="change_reason"')
        self.assertNotContains(response, 'review-snapshot-canary')
        self.assertNotContains(response, 'خطا در فرم |')
        self.assertEqual(IdentityPackageRevision.objects.count(), 0)

    def test_corrected_ingredient_and_formulation_can_be_submitted(self):
        self.client.force_login(self.author)
        for index, field, new_value in ((0, 'name_fa', 'ماده اصلاحی ساختگی'), (1, 'name', 'فرمول اصلاحی ساختگی')):
            kind, url, model, data = self.cases()[index]
            invalid = self.client.post(url, {**data, 'change_reason': 'short'})
            self.assertContains(invalid, 'href="#id_change_reason"')
            corrected = self.client.post(url, {**data, field: new_value})
            self.assertEqual(corrected.status_code, 302)
            self.assertEqual(model.objects.count(), 2)

    def test_unavailable_graph_does_not_expose_error_links_to_absent_form(self):
        self.client.force_login(self.author)
        IngredientDraft.objects.filter(pk=self.ingredient.pk).update(source_url='invalid')
        url = reverse('staff_identity_revise_component', args=['ingredient', self.ingredient.pk])
        response = self.client.post(url, {'change_reason': 'secret-canary'})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'href="#id_change_reason"')
        self.assertNotContains(response, 'name="change_reason"')
        self.assertNotContains(response, 'secret-canary')
