"""Synthetic identity-review missing-account behavior, not reviewer authentication."""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from daroobank.account_checks import current_accounts
from .identity import (IdentityConflict, create_formulation, digest, ingredient_payload, ingredient_snapshot, package_snapshot,
                       review_is_consistent, review_package, revise_package)
from .models import IdentityPackageDraft, IdentityPackageReview, IngredientDraft
from .test_identity import ALL, FORM, PACKAGE, build, user

MISSING = 2_147_483_000
SECRET = 'دلیل محرمانه ساختگی برای بازبینی خاص'
REASON = 'دلیل ساختگی برای بررسی مستقل بسته'


@override_settings(STAFF_PORTAL_ENABLED=True)
class MissingIdentityReviewerTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.author = user('missing-review-author', *ALL)
        cls.reviewer = user('missing-review-actor', 'view_identityworkspace', 'review_identityworkspace')
        cls.editor = user('missing-review-editor', 'view_identityworkspace', 'add_identityworkspace')
        cls.viewer = user('missing-review-viewer', 'view_identityworkspace')
        cls.no_access = user('missing-review-no-access')
        cls.ingredient, cls.part, _, _, cls.package = build(cls.author)
        cls.graph = package_snapshot(cls.package)
        cls.event = review_package(actor=cls.reviewer, package_id=cls.package.pk, decision='defer',
            reason=SECRET, expected_review=0, expected_graph_hash=digest(cls.graph))

    def detail(self):
        return reverse('staff_identity_detail', args=['package', self.package.pk])

    def revision(self):
        return reverse('staff_identity_revise', args=[self.package.pk])

    def assert_private(self, response):
        self.assertIn('private', response['Cache-Control'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(response['Referrer-Policy'], 'same-origin')
        self.assertEqual(response['X-Robots-Tag'], 'noindex, nofollow')

    def test_missing_latest_keeps_version_hides_details_and_does_not_block_new_review(self):
        try:
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reviewer_id=MISSING)
            event = IdentityPackageReview.objects.get(pk=self.event.pk)
            self.assertTrue(review_is_consistent(event, self.package.pk))  # structure, not account presence
            self.client.force_login(self.reviewer)
            response = self.client.get(self.detail())
            self.assert_private(response)
            self.assertContains(response, 'حساب بازبین در دسترس نیست؛ جزئیات این بازبینی نمایش داده نمی‌شود')
            self.assertNotContains(response, SECRET)
            self.assertEqual(response.context['reviews'][0].pk, self.event.pk)
            self.assertEqual(response.context['review_form'].initial['expected_review'], self.event.pk)
            data = {'decision': 'defer', 'reason': REASON, 'expected_review': 0,
                    'expected_graph_hash': digest(self.graph)}
            stale = self.client.post(reverse('staff_identity_review', args=[self.package.pk]), data)
            self.assert_private(stale)
            self.assertEqual(stale.status_code, 409)
            self.assertNotContains(stale, SECRET, status_code=409)
            self.assertEqual(IdentityPackageReview.objects.count(), 1)
            data['expected_review'] = self.event.pk
            self.assertEqual(self.client.post(reverse('staff_identity_review', args=[self.package.pk]), data).status_code, 302)
            self.assertEqual(IdentityPackageReview.objects.count(), 2)
            self.client.force_login(self.no_access)
            self.assertEqual(self.client.get(self.detail()).status_code, 403)
        finally:
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reviewer_id=self.reviewer.pk)

    def test_revision_hides_latest_missing_reviewer_but_service_and_form_remain_available(self):
        try:
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reviewer_id=MISSING)
            self.client.force_login(self.editor)
            response = self.client.get(self.revision())
            self.assert_private(response)
            self.assertContains(response, 'حساب بازبین در دسترس نیست؛ جزئیات این بازبینی نمایش داده نمی‌شود')
            self.assertContains(response, 'نبود حساب بازبین قبلی به‌تنهایی مانع اصلاح نیست')
            self.assertNotContains(response, SECRET)
            self.assertEqual(response.context['form'].initial['expected_review'], self.event.pk)
            payload = {**PACKAGE, 'quantity': '20', 'synthetic_ack': 'on', 'change_reason': REASON,
                       'expected_review': 0, 'expected_graph_hash': digest(self.graph)}
            stale = self.client.post(self.revision(), payload)
            self.assert_private(stale)
            self.assertEqual(stale.status_code, 409)
            self.assertNotContains(stale, SECRET, status_code=409)
            self.assertEqual(IdentityPackageDraft.objects.count(), 1)
            payload['expected_review'] = self.event.pk
            self.assertEqual(self.client.post(self.revision(), payload).status_code, 302)
            child = IdentityPackageDraft.objects.exclude(pk=self.package.pk).get()
            self.assertEqual(child.product_id, self.package.product_id)
            branch = revise_package(actor=self.editor, parent_id=self.package.pk,
                data={**PACKAGE, 'quantity': Decimal('30')}, change_reason=REASON,
                expected_graph_hash=digest(self.graph), expected_review=self.event.pk)
            self.assertNotEqual(branch.pk, child.pk)
            self.assertEqual(IdentityPackageDraft.objects.count(), 3)
        finally:
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reviewer_id=self.reviewer.pk)

    def test_existing_inactive_account_remains_visible_and_not_qualification_proof(self):
        get_user_model().objects.filter(pk=self.reviewer.pk).update(is_active=False, is_staff=False)
        self.client.force_login(self.editor)
        for path in (self.detail(), self.revision()):
            response = self.client.get(path)
            self.assertContains(response, SECRET)
            self.assertNotContains(response, 'حساب بازبین در دسترس نیست')

    def test_older_page_missing_reviewer_retains_cursor_and_does_not_leak_reason(self):
        events = [self.event]
        for i in range(27):
            events.append(review_package(actor=self.reviewer, package_id=self.package.pk, decision='defer',
                reason=f'بازبینی ساختگی شماره {i} برای آزمایش', expected_review=events[-1].pk,
                expected_graph_hash=digest(self.graph)))
        try:
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reviewer_id=MISSING)
            self.client.force_login(self.reviewer)
            first = self.client.get(self.detail())
            self.assertEqual(first.context['review_form'].initial['expected_review'], events[-1].pk)
            self.assertEqual(len(first.context['reviews']), 25)
            next_before = first.context['next_before']
            second = self.client.get(self.detail(), {'before': next_before})
            self.assertEqual([item.pk for item in second.context['reviews']], [item.pk for item in events[::-1][25:]])
            self.assertContains(second, 'حساب بازبین در دسترس نیست')
            self.assertNotContains(second, SECRET)
            self.assertIsNone(second.context['review_form'])
            self.assertIsNone(second.context['next_before'])
        finally:
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reviewer_id=self.reviewer.pk)

    def test_single_page_lookup_has_no_per_review_queries(self):
        self.client.force_login(self.viewer)
        self.client.get(self.detail())
        with CaptureQueriesContext(connection) as one:
            self.client.get(self.detail())
        for i in range(24):
            self.event = review_package(actor=self.reviewer, package_id=self.package.pk, decision='defer',
                reason=f'بازبینی ساختگی شماره {i} برای آزمون', expected_review=self.event.pk,
                expected_graph_hash=digest(self.graph))
        with CaptureQueriesContext(connection) as many:
            response = self.client.get(self.detail())
        self.assertEqual(len(one), len(many))
        self.assertEqual(len(response.context['reviews']), 25)
        with patch('catalog.identity_views.current_accounts', wraps=current_accounts) as lookup:
            self.client.get(self.detail())
        self.assertEqual(len(lookup.call_args.args[0]), 25)

    def test_creator_account_presence_is_not_structural_graph_validation(self):
        original_hash = self.ingredient.payload_sha256
        try:
            self.ingredient.recorded_by_id = MISSING
            fake_hash = digest(ingredient_payload(self.ingredient))
            IngredientDraft.objects.filter(pk=self.ingredient.pk).update(recorded_by_id=MISSING, payload_sha256=fake_hash)
            self.ingredient.refresh_from_db()
            self.assertEqual(ingredient_snapshot(self.ingredient)['recorded_by_id'], MISSING)
            with self.assertRaises(IdentityConflict):
                create_formulation(actor=self.author, data=FORM, components=[self.part])
            self.client.force_login(self.viewer)
            response = self.client.get(reverse('staff_identity_detail', args=['ingredient', self.ingredient.pk]))
            self.assertContains(response, 'نمایش و بازرسی پیوندها آن را کنترل نمی‌کنند')
        finally:
            IngredientDraft.objects.filter(pk=self.ingredient.pk).update(recorded_by_id=self.author.pk, payload_sha256=original_hash)

    def test_account_lookup_and_review_read_are_separate(self):
        def mutate_after_lookup(ids, *, using):
            found = current_accounts(ids, using=using)
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reviewer_id=MISSING)
            return found
        try:
            self.client.force_login(self.viewer)
            with patch('catalog.identity_views.current_accounts', side_effect=mutate_after_lookup):
                response = self.client.get(self.detail())
            self.assertContains(response, SECRET)
            self.assertEqual(IdentityPackageReview.objects.get(pk=self.event.pk).reviewer_id, MISSING)
        finally:
            IdentityPackageReview.objects.filter(pk=self.event.pk).update(reviewer_id=self.reviewer.pk)
