"""New synthetic clinical revisions should store a bounded canonical reason."""
from django.test import TestCase

from . import test_lineage as fixtures
from .evidence import evidence_state
from .inspection import inspect_drafts
from .legacy_reason_test_utils import set_legacy_reason
from .models import ClinicalDraft, ClinicalDraftReview
from .services import DraftError, create_draft, draft_data, fingerprint, review_draft, valid_draft


class RevisionReasonCanonicalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        fixtures.ClinicalLineageTests.setUpTestData.__func__(cls)
        from django.contrib.auth.models import Permission
        cls.viewer.user_permissions.add(Permission.objects.get(content_type__app_label='clinical', codename='review_clinicaldraft'))

    def test_long_outer_whitespace_is_canonicalized_before_storage_and_hash(self):
        root = create_draft(actor=self.author, data=self.data)
        core = 'دلیل ساختگی با\tفاصله داخلی\nو سطر دوم'
        raw = ' ' * 100_000 + core + '\n\t' * 50_000
        child = create_draft(actor=self.author, data=self.data, parent_id=root.pk,
                             expected_parent_hash=root.payload_sha256, change_reason=raw)
        child = ClinicalDraft.objects.select_related('parent').get(pk=child.pk)
        self.assertEqual(child.change_reason, core)
        self.assertEqual(child.payload_sha256, fingerprint(draft_data(child), root.pk, root.payload_sha256, core))
        self.assertTrue(valid_draft(child))
        self.assertEqual(inspect_drafts()['rows'][-1], {'id': child.pk, 'status': 'available'})
        event = review_draft(actor=self.viewer, draft_id=child.pk, decision='defer',
                             reason='توضیح ساختگی برای بررسی بیشتر', expected_review=0,
                             expected_hash=child.payload_sha256, expected_evidence_hash=evidence_state(child)['fingerprint'])
        self.assertEqual(event.review_snapshot['change_reason'], core)
        self.assertEqual(ClinicalDraftReview.objects.count(), 1)

    def test_canonical_boundary_and_invalid_raw_controls(self):
        root = create_draft(actor=self.author, data=self.data)
        for length in (12, 1000):
            with self.subTest(length=length):
                child = create_draft(actor=self.author, data=self.data, parent_id=root.pk,
                    expected_parent_hash=root.payload_sha256, change_reason='  ' + 'ر' * length + '  ')
                self.assertEqual(child.change_reason, 'ر' * length)
                self.assertTrue(valid_draft(ClinicalDraft.objects.select_related('parent').get(pk=child.pk)))
        before = ClinicalDraft.objects.count()
        for raw in (' ' * 2000, 'ر' * 11, 'ر' * 1001, '\x00' + 'ر' * 12,
                    'ر' * 12 + '\x7f', 'ر' * 12 + '\ud800'):
            with self.subTest(raw=ascii(raw[:20])), self.assertRaises(DraftError):
                create_draft(actor=self.author, data=self.data, parent_id=root.pk,
                             expected_parent_hash=root.payload_sha256, change_reason=raw)
        self.assertEqual(ClinicalDraft.objects.count(), before)

    def test_legacy_short_reason_and_digest_are_not_rewritten(self):
        root = create_draft(actor=self.author, data=self.data)
        old = create_draft(actor=self.author, data=self.data, parent_id=root.pk,
                           expected_parent_hash=root.payload_sha256, change_reason='دلیل قدیمی ساختگی')
        raw = '  دلیل قدیمی ساختگی\n'
        set_legacy_reason(old, raw)
        old_hash = old.payload_sha256
        self.assertTrue(valid_draft(ClinicalDraft.objects.select_related('parent').get(pk=old.pk)))
        self.assertEqual(inspect_drafts()['rows'][-1]['status'], 'available')
        newer = create_draft(actor=self.author, data=self.data, parent_id=old.pk,
            expected_parent_hash=old_hash, change_reason='  دلیل جدید ساختگی  ')
        old.refresh_from_db()
        self.assertEqual((old.change_reason, old.payload_sha256), (raw, old_hash))
        self.assertEqual(newer.change_reason, 'دلیل جدید ساختگی')
        self.assertEqual(newer.parent_payload_sha256, old_hash)
        self.assertTrue(valid_draft(ClinicalDraft.objects.select_related('parent').get(pk=newer.pk)))

    def test_root_still_rejects_any_change_reason(self):
        with self.assertRaises(DraftError):
            create_draft(actor=self.author, data=self.data, change_reason=' ' * 20)
        self.assertFalse(ClinicalDraft.objects.exists())
