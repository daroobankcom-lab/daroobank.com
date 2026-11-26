"""Narrow synthetic tests for the catalog product reviewer recheck; not revocation."""
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import TransactionTestCase

from .intake import _lock_latest_review, review_product, stage_products
from .models import ProductCandidate, ProductCandidateReview
from .test_intake import make_csv

PRODUCT = dict(source_record_id='one', name_fa='فرآورده فرضی', name_en='Synthetic', manufacturer='سازنده فرضی',
               strength='5 mg', dosage_form='قرص', package_description='10 عدد', irc='001')
REASON = 'دلیل ساختگی برای بررسی اولیه'


class CatalogReviewActorRecheckTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.stager = User.objects.create_user('synthetic-product-stager', password='synthetic-only', is_staff=True)
        self.reviewer = User.objects.create_user('synthetic-product-reviewer', password='synthetic-only', is_staff=True)
        for user in (self.stager, self.reviewer):
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label='catalog'))
        stage_products(io.BytesIO(make_csv([PRODUCT])), 'منبع ساختگی', 'https://example.org/product',
                       actor=self.stager, commit=True, rights_attested=True)
        self.candidate = ProductCandidate.objects.get()

    def review_data(self, **changes):
        return {'candidate_id': self.candidate.pk, 'decision': ProductCandidateReview.DEFER, 'reason': REASON,
                'expected_review': 0, 'expected_hash': self.candidate.payload_sha256, **changes}

    def test_matching_session_hash_allows_review_and_omitted_hash_keeps_service_calls(self):
        event = review_product(actor=self.reviewer, session_auth_hash=self.reviewer.get_session_auth_hash(),
                               **self.review_data())
        self.assertEqual(event.reviewer_id, self.reviewer.pk)
        ProductCandidateReview.objects.all().delete()
        self.assertEqual(review_product(actor=self.reviewer, **self.review_data()).reviewer_id, self.reviewer.pk)

    def test_stale_or_malformed_session_hash_is_denied_for_an_active_reviewer(self):
        for stale in ('synthetic-not-a-real-hash', '', 12345, ['synthetic']):
            with self.subTest(stale=type(stale).__name__):
                with self.assertRaises(PermissionDenied):
                    review_product(actor=self.reviewer, session_auth_hash=stale, **self.review_data())
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_password_changed_before_review_denies_the_previous_session_hash(self):
        previous = self.reviewer.get_session_auth_hash()
        current = get_user_model().objects.get(pk=self.reviewer.pk)
        current.set_password('synthetic-rotated')
        current.save(update_fields=['password'])
        with self.assertRaises(PermissionDenied):
            review_product(actor=current, session_auth_hash=previous, **self.review_data())
        self.assertFalse(ProductCandidateReview.objects.exists())
        self.assertEqual(review_product(actor=current, session_auth_hash=current.get_session_auth_hash(),
                                        **self.review_data()).reviewer_id, current.pk)

    def test_reviewer_disabled_or_destaffed_before_review_is_denied_despite_stale_actor(self):
        for field in ('is_active', 'is_staff'):
            with self.subTest(field=field):
                stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
                get_user_model().objects.filter(pk=self.reviewer.pk).update(**{field: False})
                with self.assertRaises(PermissionDenied):
                    review_product(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash(),
                                   **self.review_data())
                self.assertFalse(ProductCandidateReview.objects.exists())
                get_user_model().objects.filter(pk=self.reviewer.pk).update(**{field: True})

    def test_review_permission_removed_before_review_is_denied_despite_stale_cache(self):
        stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
        self.assertTrue(stale_actor.has_perm('catalog.review_productcandidate'))  # prime backend cache
        # Remove through a second instance so the request actor keeps its stale cache.
        other = get_user_model().objects.get(pk=self.reviewer.pk)
        other.user_permissions.remove(*Permission.objects.filter(content_type__app_label='catalog',
                                                                 codename='review_productcandidate'))
        with self.assertRaises(PermissionDenied):
            review_product(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash(),
                           **self.review_data())
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_deleted_reviewer_is_denied_even_if_the_instance_still_looks_active(self):
        stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
        get_user_model().objects.filter(pk=self.reviewer.pk).delete()
        with self.assertRaises(PermissionDenied):
            review_product(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash(),
                           **self.review_data())
        self.assertFalse(ProductCandidateReview.objects.exists())

    def test_password_changed_after_the_reviewer_recheck_can_still_race_the_review(self):
        # A remaining gap: the reviewer read takes no lock, so a credential change
        # committed afterwards is not detected by this service.
        stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
        session_hash = stale_actor.get_session_auth_hash()
        ready, resume = Event(), Event()

        def pause(*args, **kwargs):
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic catalog reviewer did not resume')
            return _lock_latest_review(*args, **kwargs)

        def writer():
            close_old_connections()
            try:
                return review_product(actor=stale_actor, session_auth_hash=session_hash, **self.review_data())
            finally:
                close_old_connections()

        with patch('catalog.intake._lock_latest_review', side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(writer)
                try:
                    self.assertTrue(ready.wait(10), 'Catalog reviewer did not reach its latest-review lock')
                    current = get_user_model().objects.get(pk=self.reviewer.pk)
                    current.is_active = False
                    current.set_unusable_password()
                    current.save(update_fields=['is_active', 'password'])
                    get_user_model().objects.filter(pk=self.reviewer.pk).update(is_active=True)
                finally:
                    resume.set()
                event = future.result(timeout=15)
        self.assertEqual(event.reviewer_id, self.reviewer.pk)
        self.assertEqual(ProductCandidateReview.objects.count(), 1)
        self.assertFalse(get_user_model().objects.get(pk=self.reviewer.pk).has_usable_password())
