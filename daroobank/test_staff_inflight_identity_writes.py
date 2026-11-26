"""Selected in-flight identity write boundaries; not global revocation."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from catalog.identity import digest, package_snapshot, require_staff
from catalog.models import IdentityPackageReview, IngredientDraft
from catalog.test_identity import ALL, INGREDIENT, build, user

REASON = 'دلایل ساختگی برای بررسی بیشتر'


@override_settings(STAFF_PORTAL_ENABLED=True,
                   AUTHENTICATION_BACKENDS=['django.contrib.auth.backends.ModelBackend'],
                   SESSION_ENGINE='django.contrib.sessions.backends.db')
class StaffInflightIdentityWriteTests(TransactionTestCase):
    def setUp(self):
        self.author = user('synthetic-inflight-identity-author', *ALL)
        self.reviewer = user('synthetic-inflight-identity-reviewer', 'view_identityworkspace',
                             'review_identityworkspace')
        self.package = build(self.author)[-1]
        # setUp already builds a chain, so compare counts rather than emptiness.
        self.ingredients = IngredientDraft.objects.count()
        self.reviews = IdentityPackageReview.objects.count()

    def client_for(self, account):
        client = Client(enforce_csrf_checks=True)
        client.force_login(account)
        return client

    def token(self, client):
        return client.cookies['csrftoken'].value

    def _paused_post(self, client, path, payload, change_account, unchanged):
        """Park one CSRF-valid identity POST at its service entry."""
        ready, resume = Event(), Event()

        def paused(*args, **kwargs):
            # The view's own permission checks have already passed.
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic in-flight identity write did not resume')
            return require_staff(*args, **kwargs)

        def post_write():
            close_old_connections()
            try:
                return client.post(path, payload, HTTP_X_CSRFTOKEN=self.token(client))
            finally:
                close_old_connections()

        # The view imports require_staff by name, so this patch only parks the
        # service entry, which is after the view's checks and before the recheck.
        with patch('catalog.identity.require_staff', side_effect=paused):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(post_write)
                try:
                    self.assertTrue(ready.wait(10), 'Synthetic identity write did not reach its service entry')
                    change_account()
                    for model, count in unchanged:
                        self.assertEqual(model.objects.count(), count)
                finally:
                    resume.set()
                return future.result(timeout=20)

    def invalidate_and_reactivate(self, account):
        def change():
            current = get_user_model().objects.get(pk=account.pk)
            current.is_active = False
            current.set_unusable_password()
            current.save(update_fields=['is_active', 'password'])
            get_user_model().objects.filter(pk=account.pk).update(is_active=True)
        return change

    def disable_then_reactivate(self, account):
        def change():
            current = get_user_model().objects.get(pk=account.pk)
            current.is_active = False
            current.save(update_fields=['is_active'])
            get_user_model().objects.filter(pk=account.pk).update(is_active=True)
        return change

    def test_password_invalidation_before_ingredient_guard_denies_inflight_create(self):
        client = self.client_for(self.author)
        path = reverse('staff_identity_create', args=['ingredient'])
        payload = {**INGREDIENT, 'synthetic_ack': 'on'}
        self.assertEqual(client.get(path).status_code, 200)
        self.assertEqual(client.post(path, payload).status_code, 403)  # CSRF negative control
        self.assertEqual(IngredientDraft.objects.count(), self.ingredients)
        response = self._paused_post(client, path, payload, self.invalidate_and_reactivate(self.author),
                                     [(IngredientDraft, self.ingredients)])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(IngredientDraft.objects.count(), self.ingredients)
        fresh = client.post(path, payload, HTTP_X_CSRFTOKEN=self.token(client))
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertEqual(IngredientDraft.objects.count(), self.ingredients)

    def test_flag_only_reactivation_before_ingredient_guard_can_still_allow_inflight_create(self):
        client = self.client_for(self.author)
        path = reverse('staff_identity_create', args=['ingredient'])
        payload = {**INGREDIENT, 'synthetic_ack': 'on'}
        self.assertEqual(client.get(path).status_code, 200)
        response = self._paused_post(client, path, payload, self.disable_then_reactivate(self.author),
                                     [(IngredientDraft, self.ingredients)])
        ingredient = IngredientDraft.objects.order_by('-pk').first()
        self.assertEqual(IngredientDraft.objects.count(), self.ingredients + 1)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_identity_detail', args=['ingredient', ingredient.pk]))
        self.assertEqual(ingredient.recorded_by_id, self.author.pk)

    def review_payload(self):
        return {'decision': 'defer', 'reason': REASON, 'expected_review': '0',
                'expected_graph_hash': digest(package_snapshot(self.package))}

    def test_password_invalidation_before_package_review_guard_denies_inflight_review(self):
        client = self.client_for(self.reviewer)
        path = reverse('staff_identity_review', args=[self.package.pk])
        payload = self.review_payload()
        self.assertEqual(client.get(reverse('staff_identity_detail', args=['package', self.package.pk])).status_code, 200)
        self.assertEqual(client.post(path, payload).status_code, 403)  # CSRF negative control
        self.assertEqual(IdentityPackageReview.objects.count(), self.reviews)
        response = self._paused_post(client, path, payload, self.invalidate_and_reactivate(self.reviewer),
                                     [(IdentityPackageReview, self.reviews)])
        self.assertEqual(response.status_code, 403)
        self.assertEqual(IdentityPackageReview.objects.count(), self.reviews)
        fresh = client.post(path, payload, HTTP_X_CSRFTOKEN=self.token(client))
        self.assertEqual(fresh.status_code, 302)
        self.assertTrue(fresh['Location'].startswith(reverse('staff_login') + '?'))
        self.assertEqual(IdentityPackageReview.objects.count(), self.reviews)

    def test_flag_only_reactivation_before_package_review_guard_can_still_allow_inflight_review(self):
        client = self.client_for(self.reviewer)
        path = reverse('staff_identity_review', args=[self.package.pk])
        payload = self.review_payload()
        self.assertEqual(client.get(reverse('staff_identity_detail', args=['package', self.package.pk])).status_code, 200)
        response = self._paused_post(client, path, payload, self.disable_then_reactivate(self.reviewer),
                                     [(IdentityPackageReview, self.reviews)])
        review = IdentityPackageReview.objects.order_by('-pk').first()
        self.assertEqual(IdentityPackageReview.objects.count(), self.reviews + 1)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], reverse('staff_identity_detail', args=['package', self.package.pk]))
        self.assertEqual(review.reviewer_id, self.reviewer.pk)
