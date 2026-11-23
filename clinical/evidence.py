"""Bounded unverified reference assertions, never network access or approval."""
import hashlib
import json
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Prefetch, prefetch_related_objects

from .models import ClinicalDraft, ClinicalReferenceAssertion
from .services import (ADD, HASH, REFERENCE_FIELDS, VIEW, DraftConflict, DraftError, require_staff,
                       _valid_draft_for_update, validate_reference_data)

ASSERTION_FIELDS = REFERENCE_FIELDS + ('relation',)
MAX_REFERENCES = 10
MAX_INSPECTION_DRAFTS = 50


def validate_reference(data):
    if not isinstance(data, dict) or set(data) != set(ASSERTION_FIELDS):
        raise DraftError('ساختار ارجاع تکمیلی معتبر نیست.')
    if not isinstance(data['relation'], str) or data['relation'] not in dict(ClinicalReferenceAssertion.RELATIONS):
        raise DraftError('رابطه اعلام‌شده معتبر نیست.')
    validate_reference_data({key: data[key] for key in REFERENCE_FIELDS})


def reference_data(item):
    return {key: getattr(item, key) for key in ASSERTION_FIELDS}


def serialize(data):
    return {key: value.isoformat() if isinstance(value, date) else value for key, value in data.items()}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode('utf-8')).hexdigest()


def reference_fingerprint(data, draft_id, draft_hash):
    return digest({'draft_id': draft_id, 'draft_payload_sha256': draft_hash, 'reference': serialize(data)})


def valid_reference(item, draft):
    try:
        data = reference_data(item)
        validate_reference(data)
        return (item.draft_id == draft.pk and item.draft_payload_sha256 == draft.payload_sha256
                and isinstance(item.payload_sha256, str) and bool(HASH.fullmatch(item.payload_sha256))
                and reference_fingerprint(data, draft.pk, draft.payload_sha256) == item.payload_sha256)
    except (DraftError, ValueError, TypeError, AttributeError, OverflowError):
        return False


def _check_assertions(draft, items):
    """Apply the shared cap and per-assertion checks before looking up recorders."""
    if len(items) > MAX_REFERENCES:
        return 'over_limit', set()
    if any(not valid_reference(item, draft) or type(item.recorded_by_id) is not int or item.recorded_by_id <= 0 for item in items):
        return 'invalid', set()
    return 'available', {item.recorded_by_id for item in items}


def evidence_state(draft, *, lock=False):
    """Return a bounded assertion state; lock only for the transactional writers."""
    # Do not use an inner join: a corrupted missing recorder must not hide an assertion.
    # Writers already hold the draft lock, then lock existing assertions in PK
    # order; this locks neither absent rows nor unrelated users/parent drafts.
    queryset = draft.additional_references.order_by('pk')
    if lock:
        queryset = queryset.select_for_update()
    items = list(queryset[:MAX_REFERENCES + 1])
    status, recorder_ids = _check_assertions(draft, items)
    if status != 'available':
        return {'status': status}
    recorders = get_user_model().objects.in_bulk(recorder_ids) if recorder_ids else {}
    if set(recorders) != recorder_ids:
        return {'status': 'invalid'}
    for item in items:
        item.display_recorder = recorders[item.recorded_by_id]
    # Bind recorded user IDs too, but not timestamps; this is not a signature.
    fingerprint = digest([{'id': item.pk, 'payload_sha256': item.payload_sha256,
                           'recorded_by_id': item.recorded_by_id} for item in items])
    snapshots = [{'id': item.pk, 'recorded_by_id': item.recorded_by_id, 'payload_sha256': item.payload_sha256,
                  'reference': serialize(reference_data(item))} for item in items]
    return {'status': 'available', 'items': items, 'fingerprint': fingerprint, 'snapshot': snapshots}


def inspection_evidence_statuses(drafts):
    """Batch status-only checks for at most 50 already-valid, distinct drafts.

    Per-parent sliced prefetch uses a PostgreSQL window: at most 11 assertions
    per draft reach Python, including the over-limit sentinel. Do not join to
    recorders: an absent recorder must remain visible as an invalid assertion.
    This diagnostic is read-only and is not a replacement for evidence_state
    in write/review workflows.
    """
    if (len(drafts) > MAX_INSPECTION_DRAFTS or any(draft.pk is None or draft._state.adding for draft in drafts)
            or len({draft.pk for draft in drafts}) != len(drafts)):
        raise ValueError('Expected at most 50 distinct persisted drafts')
    if not drafts:
        return {}
    # prefetch_related_objects skips an existing to_attr; never reuse stale rows
    # if the same model instances happen to be passed to a later inspection.
    for draft in drafts:
        if hasattr(draft, '_inspection_references'):
            del draft._inspection_references
    prefetch_related_objects(drafts, Prefetch(
        'additional_references',
        queryset=ClinicalReferenceAssertion.objects.order_by('pk')[:MAX_REFERENCES + 1],
        to_attr='_inspection_references',
    ))
    results, needed = {}, set()
    for draft in drafts:
        status, recorder_ids = _check_assertions(draft, draft._inspection_references)
        results[draft.pk] = (status, recorder_ids)
        needed.update(recorder_ids)
    recorders = get_user_model().objects.in_bulk(needed) if needed else {}
    return {pk: ('invalid' if status == 'available' and not ids.issubset(recorders) else status)
            for pk, (status, ids) in results.items()}


def add_reference(*, actor, draft_id, data, expected_draft_hash, expected_evidence_hash):
    require_staff(actor, VIEW, ADD)
    validate_reference(data)
    if (type(draft_id) is not int or not 1 <= draft_id <= 9_223_372_036_854_775_807
            or not isinstance(expected_draft_hash, str) or not HASH.fullmatch(expected_draft_hash)
            or not isinstance(expected_evidence_hash, str) or not HASH.fullmatch(expected_evidence_hash)):
        raise DraftError('شناسه پیش‌نویس یا فهرست ارجاع معتبر نیست.')
    with transaction.atomic():
        try:
            draft = ClinicalDraft.objects.select_for_update(of=('self',)).get(pk=draft_id)
        except ClinicalDraft.DoesNotExist as exc:
            raise DraftConflict('پیش‌نویس در دسترس نیست.') from exc
        if not _valid_draft_for_update(draft) or draft.payload_sha256 != expected_draft_hash:
            raise DraftConflict('پیش‌نویس تغییر کرده یا ناسازگار است.')
        state = evidence_state(draft, lock=True)
        if state['status'] != 'available' or state['fingerprint'] != expected_evidence_hash:
            raise DraftConflict('ارجاع‌ها تغییر کرده یا ناسازگارند؛ صفحه را تازه کنید.')
        fingerprint = reference_fingerprint(data, draft.pk, draft.payload_sha256)
        existing = next((item for item in state['items'] if item.payload_sha256 == fingerprint), None)
        if existing:
            return existing, False
        if len(state['items']) >= MAX_REFERENCES:
            raise DraftConflict('سقف ۱۰ ارجاع تکمیلی برای این نسخه پر شده است.')
        return ClinicalReferenceAssertion.objects.create(draft=draft, draft_payload_sha256=draft.payload_sha256,
            recorded_by=actor, payload_sha256=fingerprint, **data), True


def reviewed_evidence(review):
    """Defensively read a bounded historical snapshot; never establish authenticity."""
    snap = review.review_snapshot
    if not isinstance(snap, dict):
        return {'status': 'invalid'}
    if 'evidence_version' not in snap:
        return {'status': 'legacy'}
    if type(snap['evidence_version']) is not int or snap['evidence_version'] != 1:
        return {'status': 'invalid'}
    entries, recorded_hash = snap.get('evidence_snapshot'), snap.get('evidence_fingerprint')
    if (not isinstance(entries, list) or len(entries) > MAX_REFERENCES or not isinstance(recorded_hash, str)
            or not HASH.fullmatch(recorded_hash) or not isinstance(review.draft_payload_sha256, str)
            or not HASH.fullmatch(review.draft_payload_sha256)):
        return {'status': 'invalid'}
    items = []
    try:
        for entry in entries:
            if (not isinstance(entry, dict) or set(entry) != {'id', 'recorded_by_id', 'payload_sha256', 'reference'}
                    or type(entry['id']) is not int or not 1 <= entry['id'] <= 9_223_372_036_854_775_807
                    or type(entry['recorded_by_id']) is not int or not 1 <= entry['recorded_by_id'] <= 9_223_372_036_854_775_807
                    or not isinstance(entry['payload_sha256'], str) or not HASH.fullmatch(entry['payload_sha256'])
                    or not isinstance(entry['reference'], dict) or set(entry['reference']) != set(ASSERTION_FIELDS)):
                return {'status': 'invalid'}
            data = dict(entry['reference'])
            for key in ('reference_published_on', 'reference_accessed_on'):
                value = data[key]
                if value is not None:
                    if not isinstance(value, str):
                        return {'status': 'invalid'}
                    data[key] = date.fromisoformat(value)
            validate_reference(data)
            if (serialize(data) != entry['reference']
                    or reference_fingerprint(data, review.draft_id, review.draft_payload_sha256) != entry['payload_sha256']):
                return {'status': 'invalid'}
            items.append(entry)
        ids = [item['id'] for item in items]
        if ids != sorted(set(ids)):
            return {'status': 'invalid'}
        actual = digest([{'id': item['id'], 'payload_sha256': item['payload_sha256'],
                          'recorded_by_id': item['recorded_by_id']} for item in items])
        if actual != recorded_hash:
            return {'status': 'invalid'}
    except (DraftError, ValueError, TypeError, AttributeError, OverflowError):
        return {'status': 'invalid'}
    return {'status': 'available', 'items': items, 'fingerprint': recorded_hash}
