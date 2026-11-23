"""Bounded unverified reference assertions, never network access or approval."""
import hashlib
import json
from datetime import date

from django.contrib.auth import get_user_model
from django.db import transaction

from .models import ClinicalDraft, ClinicalReferenceAssertion
from .services import (ADD, HASH, REFERENCE_FIELDS, VIEW, DraftConflict, DraftError, require_staff,
                       valid_draft, validate_reference_data)

ASSERTION_FIELDS = REFERENCE_FIELDS + ('relation',)
MAX_REFERENCES = 10


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


def evidence_state(draft):
    """Return at most ten validated assertions, not evidence verification."""
    # Do not use an inner join: a corrupted missing recorder must not hide an assertion.
    items = list(draft.additional_references.order_by('pk')[:MAX_REFERENCES + 1])
    if len(items) > MAX_REFERENCES:
        return {'status': 'over_limit'}
    if any(not valid_reference(item, draft) or type(item.recorded_by_id) is not int or item.recorded_by_id <= 0 for item in items):
        return {'status': 'invalid'}
    recorder_ids = {item.recorded_by_id for item in items}
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


def add_reference(*, actor, draft_id, data, expected_draft_hash, expected_evidence_hash):
    require_staff(actor, VIEW, ADD)
    validate_reference(data)
    if (type(draft_id) is not int or not 1 <= draft_id <= 9_223_372_036_854_775_807
            or not isinstance(expected_draft_hash, str) or not HASH.fullmatch(expected_draft_hash)
            or not isinstance(expected_evidence_hash, str) or not HASH.fullmatch(expected_evidence_hash)):
        raise DraftError('شناسه پیش‌نویس یا فهرست ارجاع معتبر نیست.')
    with transaction.atomic():
        try:
            draft = ClinicalDraft.objects.select_for_update(of=('self',)).select_related('parent').get(pk=draft_id)
        except ClinicalDraft.DoesNotExist as exc:
            raise DraftConflict('پیش‌نویس در دسترس نیست.') from exc
        if not valid_draft(draft) or draft.payload_sha256 != expected_draft_hash:
            raise DraftConflict('پیش‌نویس تغییر کرده یا ناسازگار است.')
        state = evidence_state(draft)
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
