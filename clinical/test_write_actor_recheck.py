"""Narrow synthetic tests for the clinical draft/reference writer rechecks."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections
from django.test import TransactionTestCase

from .evidence import add_reference, evidence_state, reference_fingerprint
from .models import ClinicalDraft, ClinicalReferenceAssertion
from .services import create_draft, fingerprint

DRAFT = {'subject': 'موضوع فرضی', 'audience': 'patient', 'title': 'عنوان ساختگی',
         'statement': 'گزاره ساختگی صرفاً برای آزمون', 'reference_title': 'ارجاع فرضی',
         'reference_url': 'https://example.org/reference', 'reference_location': 'بخش فرضی',
         'reference_author': '', 'reference_version': '', 'reference_published_on': None,
         'reference_accessed_on': None}
REFERENCE = {'reference_title': 'ارجاع ساختگی', 'reference_url': 'https://example.org/extra',
             'reference_location': 'بخش ساختگی', 'reference_author': '', 'reference_version': '',
             'reference_published_on': None, 'reference_accessed_on': None, 'relation': 'supports'}


class ClinicalWriteActorRecheckTests(TransactionTestCase):
    def setUp(self):
        self.author = get_user_model().objects.create_user('synthetic-clinical-writer', password='synthetic-only',
                                                           is_staff=True)
        self.author.user_permissions.add(*Permission.objects.filter(content_type__app_label='clinical'))

    def create(self, actor=None, **kwargs):
        return create_draft(actor=actor or self.author, data=dict(DRAFT), **kwargs)

    def reference_data(self, draft):
        return {'draft_id': draft.pk, 'data': dict(REFERENCE), 'expected_draft_hash': draft.payload_sha256,
                'expected_evidence_hash': evidence_state(draft)['fingerprint']}

    def park_and_change(self, target, original, call, change_account):
        """Run `call` in a worker, parked inside the transaction, and change the account."""
        ready, resume = Event(), Event()

        def pause(*args, **kwargs):
            ready.set()
            if not resume.wait(10):
                raise TimeoutError('Synthetic clinical writer did not resume')
            return original(*args, **kwargs)

        def writer():
            close_old_connections()
            try:
                return call()
            finally:
                close_old_connections()

        with patch(target, side_effect=pause):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(writer)
                try:
                    self.assertTrue(ready.wait(10), f'Clinical writer did not reach {target}')
                    change_account()
                finally:
                    resume.set()
                return future.result(timeout=20)

    def invalidate_and_reactivate(self):
        current = get_user_model().objects.get(pk=self.author.pk)
        current.is_active = False
        current.set_unusable_password()
        current.save(update_fields=['is_active', 'password'])
        get_user_model().objects.filter(pk=self.author.pk).update(is_active=True)

    def test_matching_session_hash_allows_a_draft_and_omitted_hash_keeps_service_calls(self):
        draft = self.create(session_auth_hash=self.author.get_session_auth_hash())
        self.assertEqual(draft.author_id, self.author.pk)
        ClinicalDraft.objects.all().delete()
        self.assertEqual(self.create().author_id, self.author.pk)

    def test_stale_or_malformed_session_hash_is_denied_for_a_draft(self):
        for stale in ('synthetic-not-a-real-hash', '', 12345, ['synthetic']):
            with self.subTest(stale=type(stale).__name__):
                with self.assertRaises(PermissionDenied):
                    self.create(session_auth_hash=stale)
        self.assertFalse(ClinicalDraft.objects.exists())

    def test_password_changed_before_a_draft_denies_the_previous_session_hash(self):
        previous = self.author.get_session_auth_hash()
        current = get_user_model().objects.get(pk=self.author.pk)
        current.set_password('synthetic-rotated')
        current.save(update_fields=['password'])
        with self.assertRaises(PermissionDenied):
            self.create(actor=current, session_auth_hash=previous)
        self.assertFalse(ClinicalDraft.objects.exists())
        self.assertEqual(self.create(actor=current, session_auth_hash=current.get_session_auth_hash()).author_id,
                         current.pk)

    def test_writer_disabled_or_destaffed_before_a_draft_is_denied_despite_stale_actor(self):
        for field in ('is_active', 'is_staff'):
            with self.subTest(field=field):
                stale_actor = get_user_model().objects.get(pk=self.author.pk)
                get_user_model().objects.filter(pk=self.author.pk).update(**{field: False})
                with self.assertRaises(PermissionDenied):
                    self.create(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash())
                self.assertFalse(ClinicalDraft.objects.exists())
                get_user_model().objects.filter(pk=self.author.pk).update(**{field: True})

    def test_add_permission_removed_before_a_draft_is_denied_despite_stale_cache(self):
        stale_actor = get_user_model().objects.get(pk=self.author.pk)
        self.assertTrue(stale_actor.has_perm('clinical.add_clinicaldraft'))  # prime backend cache
        # Remove through a second instance so the request actor keeps its stale cache.
        other = get_user_model().objects.get(pk=self.author.pk)
        other.user_permissions.remove(*Permission.objects.filter(content_type__app_label='clinical',
                                                                 codename='add_clinicaldraft'))
        with self.assertRaises(PermissionDenied):
            self.create(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash())
        self.assertFalse(ClinicalDraft.objects.exists())

    def test_deleted_writer_is_denied_even_if_the_instance_still_looks_active(self):
        stale_actor = get_user_model().objects.get(pk=self.author.pk)
        self.assertTrue(stale_actor.has_perm('clinical.add_clinicaldraft'))
        get_user_model().objects.filter(pk=self.author.pk).delete()
        with self.assertRaises(PermissionDenied):
            self.create(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash())
        self.assertFalse(ClinicalDraft.objects.exists())

    def test_password_changed_after_the_draft_recheck_can_still_race_the_write(self):
        # A remaining gap: the recheck is an unlocked point-in-time read.
        stale_actor = get_user_model().objects.get(pk=self.author.pk)
        draft = self.park_and_change('clinical.services.fingerprint', fingerprint,
                                     lambda: self.create(actor=stale_actor,
                                                         session_auth_hash=stale_actor.get_session_auth_hash()),
                                     self.invalidate_and_reactivate)
        self.assertEqual(draft.author_id, self.author.pk)
        self.assertEqual(ClinicalDraft.objects.count(), 1)
        self.assertFalse(get_user_model().objects.get(pk=self.author.pk).has_usable_password())

    def test_matching_session_hash_allows_a_reference_and_omitted_hash_keeps_service_calls(self):
        draft = self.create()
        assertion, created = add_reference(actor=self.author,
                                           session_auth_hash=self.author.get_session_auth_hash(),
                                           **self.reference_data(draft))
        self.assertTrue(created)
        self.assertEqual(assertion.recorded_by_id, self.author.pk)
        ClinicalReferenceAssertion.objects.all().delete()
        self.assertTrue(add_reference(actor=self.author, **self.reference_data(draft))[1])

    def test_stale_session_hash_is_denied_for_a_reference(self):
        draft = self.create()
        for stale in ('synthetic-not-a-real-hash', '', 12345):
            with self.subTest(stale=type(stale).__name__):
                with self.assertRaises(PermissionDenied):
                    add_reference(actor=self.author, session_auth_hash=stale, **self.reference_data(draft))
        self.assertFalse(ClinicalReferenceAssertion.objects.exists())

    def test_writer_disabled_or_permission_removed_before_a_reference_is_denied(self):
        draft = self.create()
        stale_actor = get_user_model().objects.get(pk=self.author.pk)
        self.assertTrue(stale_actor.has_perm('clinical.add_clinicaldraft'))
        get_user_model().objects.filter(pk=self.author.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            add_reference(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash(),
                          **self.reference_data(draft))
        get_user_model().objects.filter(pk=self.author.pk).update(is_active=True)
        other = get_user_model().objects.get(pk=self.author.pk)
        other.user_permissions.remove(*Permission.objects.filter(content_type__app_label='clinical',
                                                                 codename='add_clinicaldraft'))
        with self.assertRaises(PermissionDenied):
            add_reference(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash(),
                          **self.reference_data(draft))
        self.assertFalse(ClinicalReferenceAssertion.objects.exists())

    def test_password_changed_after_the_reference_recheck_can_still_race_the_write(self):
        draft = self.create()
        stale_actor = get_user_model().objects.get(pk=self.author.pk)
        payload = self.reference_data(draft)
        assertion, created = self.park_and_change(
            'clinical.evidence.reference_fingerprint', reference_fingerprint,
            lambda: add_reference(actor=stale_actor, session_auth_hash=stale_actor.get_session_auth_hash(), **payload),
            self.invalidate_and_reactivate)
        self.assertTrue(created)
        self.assertEqual(assertion.recorded_by_id, self.author.pk)
        self.assertEqual(ClinicalReferenceAssertion.objects.count(), 1)
        self.assertFalse(get_user_model().objects.get(pk=self.author.pk).has_usable_password())
