"""Narrow synthetic tests for the review write's actor and session-hash recheck."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import TransactionTestCase

from .models import SourceClaim, SourceClaimReview
from .services import _lock_latest_review, record_claim, review_claim

DATA = {'source_name': 'Synthetic source', 'source_url': 'https://example.org/reviewed',
        'owner': 'Synthetic owner', 'evidence_url': 'https://example.org/evidence', 'evidence_note': '',
        'claims_collection': True, 'claims_storage': False, 'claims_publication': False,
        'starts_on': None, 'expires_on': None}
REASON = 'این مدرک ساختگی به بررسی بیشتر نیاز دارد.'


def grant(user, *codenames):
    user.user_permissions.add(*Permission.objects.filter(content_type__app_label='sources', codename__in=codenames))


class ReviewSessionBindingTests(TransactionTestCase):
    def setUp(self):
        User = get_user_model()
        self.author = User.objects.create_user('synthetic-review-author', password='synthetic-only', is_staff=True)
        grant(self.author, 'view_sourceclaim', 'add_sourceclaim')
        self.reviewer = User.objects.create_user('synthetic-review-actor', password='synthetic-only', is_staff=True)
        grant(self.reviewer, 'view_sourceclaim', 'review_sourceclaim')
        self.claim, _created = record_claim(actor=self.author, data=DATA)

    def review_data(self, **changes):
        return {'claim_id': self.claim.pk, 'decision': 'further_review', 'reason': REASON,
                'expected_review': 0, 'expected_hash': self.claim.payload_sha256, **changes}

    def test_matching_session_hash_allows_review_and_omitted_hash_keeps_service_calls(self):
        event = review_claim(actor=self.reviewer, session_auth_hash=self.reviewer.get_session_auth_hash(),
                             **self.review_data())
        self.assertEqual(event.reviewer_id, self.reviewer.pk)
        SourceClaimReview.objects.all().delete()
        # Direct service callers keep the previous behavior when no hash is given.
        self.assertEqual(review_claim(actor=self.reviewer, **self.review_data()).reviewer_id, self.reviewer.pk)

    def test_stale_or_malformed_session_hash_is_denied_for_an_active_reviewer(self):
        for stale in ('synthetic-not-a-real-hash', '', 12345, ['synthetic']):
            with self.subTest(stale=type(stale).__name__):
                with self.assertRaises(PermissionDenied):
                    review_claim(actor=self.reviewer, session_auth_hash=stale, **self.review_data())
        self.assertFalse(SourceClaimReview.objects.exists())

    def test_password_changed_before_review_denies_the_previous_session_hash(self):
        previous = self.reviewer.get_session_auth_hash()
        current = get_user_model().objects.get(pk=self.reviewer.pk)
        current.set_password('synthetic-rotated')
        current.save(update_fields=['password'])
        with self.assertRaises(PermissionDenied):
            review_claim(actor=current, session_auth_hash=previous, **self.review_data())
        self.assertFalse(SourceClaimReview.objects.exists())
        self.assertEqual(review_claim(actor=current, session_auth_hash=current.get_session_auth_hash(),
                                      **self.review_data()).reviewer_id, current.pk)

    def test_reviewer_disabled_or_destaffed_before_review_is_denied_despite_stale_actor(self):
        for field in ('is_active', 'is_staff'):
            with self.subTest(field=field):
                stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
                get_user_model().objects.filter(pk=self.reviewer.pk).update(**{field: False})
                with self.assertRaises(PermissionDenied):
                    review_claim(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash(),
                                 **self.review_data())
                self.assertFalse(SourceClaimReview.objects.exists())
                get_user_model().objects.filter(pk=self.reviewer.pk).update(**{field: True})

    def test_review_permission_removed_before_review_is_denied_despite_stale_cache(self):
        stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
        self.assertTrue(stale_actor.has_perm('sources.review_sourceclaim'))  # prime backend cache
        # Remove through a second instance so the request actor keeps its stale cache.
        other = get_user_model().objects.get(pk=self.reviewer.pk)
        other.user_permissions.remove(*Permission.objects.filter(content_type__app_label='sources',
                                                                 codename='review_sourceclaim'))
        with self.assertRaises(PermissionDenied):
            review_claim(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash(),
                         **self.review_data())
        self.assertFalse(SourceClaimReview.objects.exists())

    def test_deleted_reviewer_is_denied_even_if_the_instance_still_looks_active(self):
        stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
        get_user_model().objects.filter(pk=self.reviewer.pk).delete()
        with self.assertRaises(PermissionDenied):
            review_claim(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash(),
                         **self.review_data())
        self.assertFalse(SourceClaimReview.objects.exists())

    def test_password_changed_after_the_reviewer_recheck_can_still_race_the_review(self):
        # A remaining gap: this recheck is an unlocked point-in-time read, so a
        # credential change committed afterwards is not detected by this service.
        stale_actor = get_user_model().objects.get(pk=self.reviewer.pk)
        session_hash = stale_actor.get_session_auth_hash()
        ready, resume = Event(), Event()

        def pause(*args, **kwargs):
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic review writer did not resume')
            return _lock_latest_review(*args, **kwargs)

        def writer():
            close_old_connections()
            try:
                return review_claim(actor=stale_actor, session_auth_hash=session_hash, **self.review_data())
            finally:
                close_old_connections()

        with patch('sources.services._lock_latest_review', side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(writer)
                try:
                    self.assertTrue(ready.wait(10), 'Review writer did not reach its latest-review lock')
                    current = get_user_model().objects.get(pk=self.reviewer.pk)
                    current.is_active = False
                    current.set_unusable_password()
                    current.save(update_fields=['is_active', 'password'])
                    get_user_model().objects.filter(pk=self.reviewer.pk).update(is_active=True)
                finally:
                    resume.set()
                event = future.result(timeout=15)
        self.assertEqual(event.reviewer_id, self.reviewer.pk)
        self.assertEqual(SourceClaimReview.objects.count(), 1)
        self.assertFalse(get_user_model().objects.get(pk=self.reviewer.pk).has_usable_password())
        self.assertNotEqual(SourceClaim.objects.count(), 0)
