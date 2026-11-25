"""Construct pre-canonicalization synthetic draft rows for regression tests only."""
from daroobank.validation import valid_review_reason
from .models import ClinicalDraft
from .services import draft_data, fingerprint


def set_legacy_reason(draft, raw_reason):
    if not draft.parent_id or not valid_review_reason(raw_reason):
        raise ValueError('Expected a valid historical revision reason')
    digest = fingerprint(draft_data(draft), draft.parent_id, draft.parent_payload_sha256, raw_reason)
    ClinicalDraft.objects.filter(pk=draft.pk).update(change_reason=raw_reason, payload_sha256=digest)
    draft.change_reason, draft.payload_sha256 = raw_reason, digest
    return draft
