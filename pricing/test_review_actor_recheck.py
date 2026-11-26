"""Narrow synthetic tests for the pricing reviewer recheck; not revocation."""
import io
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import TransactionTestCase

from .importer import stage_csv
from .models import PriceCandidate, PriceCandidateReview
from .reviews import _lock_latest_review, record_preliminary_review
from .test_workflow import csv_bytes

PRICE = dict(source_record_id='one', irc='001', manufacturer='سازنده فرضی', strength='5 mg',
             dosage_form='قرص', package_description='10 عدد', amount='100', currency='RIAL',
             category='retail', unit='package', effective_date='', source_published_date='')
REASON = 'دلیل ساختگی برای بررسی اولیه'


class PricingReviewActorRecheckTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.stager = User.objects.create_user('synthetic-price-stager', password='synthetic-only', is_staff=True)
        self.reviewer = User.objects.create_user('synthetic-price-reviewer', password='synthetic-only', is_staff=True)
        for user in (self.stager, self.reviewer):
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label='pricing'))
        stage_csv(io.BytesIO(csv_bytes([PRICE])), 'منبع ساختگی', 'https://example.org/price',
                  staged_by=self.stager, commit=True, rights_attested=True)
        self.candidate = PriceCandidate.objects.get()

    def review_data(self, **changes):
        return {'candidate_id': self.candidate.pk, 'decision': 'defer', 'reason': REASON, 'expected_review': 0,
                'expected_product': 0, 'expected_product_hash': '', **changes}

    def test_matching_session_hash_allows_review_and_omitted_hash_keeps_service_calls(self):
        event = record_preliminary_review(actor=self.reviewer, session_auth_hash=self.reviewer.get_session_auth_hash(),
                                          **self.review_data())
        self.assertEqual(event.reviewer_id, self.reviewer.pk)
        PriceCandidateReview.objects.all().delete()
        self.assertEqual(record_preliminary_review(actor=self.reviewer, **self.review_data()).reviewer_id,
                         self.reviewer.pk)

    def test_stale_or_malformed_session_hash_is_denied_for_an_active_reviewer(self):
        for stale in ('synthetic-not-a-real-hash', '', 12345, ['synthetic']):
            with self.subTest(stale=type(stale).__name__):
                with self.assertRaises(PermissionDenied):
                    record_preliminary_review(actor=self.reviewer, session_auth_hash=stale, **self.review_data())
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_password_changed_before_review_denies_the_previous_session_hash(self):
        previous = self.reviewer.get_session_auth_hash()
        current = get_user_model().objects.get(pk=self.reviewer.pk)
        current.set_password('synthetic-rotated')
        current.save(update_fields=['password'])
        with self.assertRaises(PermissionDenied):
            record_preliminary_review(actor=current, session_auth_hash=previous, **self.review_data())
        self.assertFalse(PriceCandidateReview.objects.exists())
        self.assertEqual(record_preliminary_review(actor=current,
                                                   session_auth_hash=current.get_session_auth_hash(),
                                                   **self.review_data()).reviewer_id, current.pk)

    def test_reviewer_disabled_or_destaffed_before_review_is_denied_despite_stale_actor(self):
        for field in ('is_active', 'is_staff'):
            with self.subTest(field=field):
                stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
                get_user_model().objects.filter(pk=self.reviewer.pk).update(**{field: False})
                with self.assertRaises(PermissionDenied):
                    record_preliminary_review(actor=stale_actor,
                                              session_auth_hash=stale_actor.get_session_auth_hash(),
                                              **self.review_data())
                self.assertFalse(PriceCandidateReview.objects.exists())
                get_user_model().objects.filter(pk=self.reviewer.pk).update(**{field: True})

    def test_review_permission_removed_before_review_is_denied_despite_stale_cache(self):
        stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
        self.assertTrue(stale_actor.has_perm('pricing.review_pricecandidate'))  # prime backend cache
        stale_actor.user_permissions.remove(*Permission.objects.filter(content_type__app_label='pricing',
                                                                       codename='review_pricecandidate'))
        with self.assertRaises(PermissionDenied):
            record_preliminary_review(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash(),
                                      **self.review_data())
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_deleted_reviewer_is_denied_even_if_the_instance_still_looks_active(self):
        stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
        get_user_model().objects.filter(pk=self.reviewer.pk).delete()
        with self.assertRaises(PermissionDenied):
            record_preliminary_review(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash(),
                                      **self.review_data())
        self.assertFalse(PriceCandidateReview.objects.exists())

    def test_password_changed_after_the_reviewer_recheck_can_still_race_the_review(self):
        # A remaining gap: the reviewer read takes no lock, so a credential change
        # committed afterwards is not detected by this service.
        stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
        session_hash = stale_actor.get_session_auth_hash()
        ready, resume = Event(), Event()

        def pause(*args, **kwargs):
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic pricing reviewer did not resume')
            return _lock_latest_review(*args, **kwargs)

        def writer():
            close_old_connections()
            try:
                return record_preliminary_review(actor=stale_actor, session_auth_hash=session_hash,
                                                 **self.review_data())
            finally:
                close_old_connections()

        with patch('pricing.reviews._lock_latest_review', side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(writer)
                try:
                    self.assertTrue(ready.wait(10), 'Pricing reviewer did not reach its latest-review lock')
                    current = get_user_model().objects.get(pk=self.reviewer.pk)
                    current.is_active = False
                    current.set_unusable_password()
                    current.save(update_fields=['is_active', 'password'])
                    get_user_model().objects.filter(pk=self.reviewer.pk).update(is_active=True)
                finally:
                    resume.set()
                event = future.result(timeout=15)
        self.assertEqual(event.reviewer_id, self.reviewer.pk)
        self.assertEqual(PriceCandidateReview.objects.count(), 1)
        self.assertFalse(get_user_model().objects.get(pk=self.reviewer.pk).has_usable_password())
