"""Read-only parent-path clues for synthetic clinical versions, not an audit."""
import re

from django.core import signing
from django.utils.crypto import constant_time_compare, salted_hmac

from daroobank.signed_cursors import loads_nonfuture

from .draft_reads import bounded_draft_text, draft_text_uninspected, materialize_draft_text
from .models import ClinicalDraft
from .services import VIEW, require_staff, valid_draft, valid_payload

PAGE_SIZE = 20
MAX_ID = 9_223_372_036_854_775_807
CURSOR_SALT = 'clinical.draft.lineage.v1'
CURSOR_MAX_AGE = 3600
MAX_CURSOR_LENGTH = 1024
_HASH = re.compile(r'^[0-9a-f]{64}$')


class InvalidLineageCursor(ValueError):
    pass


class LineageNotFound(ValueError):
    pass


def _id(value):
    return type(value) is int and 1 <= value <= MAX_ID


def _keyed_hash(value):
    # Signed tokens are not encrypted; do not put raw payload hashes in them.
    return salted_hmac(CURSOR_SALT + '.payload', value, algorithm='sha256').hexdigest()


def _encode(anchor, current, depth):
    return signing.dumps({'anchor': anchor.pk, 'anchor_hash': _keyed_hash(anchor.payload_sha256),
                          'current': current.pk, 'current_hash': _keyed_hash(current.payload_sha256),
                          'depth': depth}, salt=CURSOR_SALT)


def _decode(token, anchor):
    if not isinstance(token, str) or not token or len(token) > MAX_CURSOR_LENGTH or token.startswith('.'):
        raise InvalidLineageCursor
    try:
        data = loads_nonfuture(token, salt=CURSOR_SALT, max_age=CURSOR_MAX_AGE)
        if (not isinstance(data, dict) or set(data) != {'anchor', 'anchor_hash', 'current', 'current_hash', 'depth'}
                or type(data['anchor']) is not int or data['anchor'] != anchor.pk
                or not _id(data['current']) or data['current'] >= anchor.pk
                or type(data['depth']) is not int or data['depth'] < PAGE_SIZE
                or data['depth'] % PAGE_SIZE or data['depth'] > anchor.pk - data['current']
                or not isinstance(data['anchor_hash'], str) or not _HASH.fullmatch(data['anchor_hash'])
                or not isinstance(data['current_hash'], str) or not _HASH.fullmatch(data['current_hash'])
                or not constant_time_compare(data['anchor_hash'], _keyed_hash(anchor.payload_sha256))):
            raise InvalidLineageCursor
        return data['current'], data['current_hash'], data['depth']
    except (signing.BadSignature, TypeError, ValueError, KeyError, OverflowError) as exc:
        raise InvalidLineageCursor from exc


def inspect_lineage(*, actor, anchor_id, cursor=''):
    """Inspect at most 20 direct-parent links, with no writes or snapshot guarantee."""
    require_staff(actor, VIEW)
    if not _id(anchor_id):
        raise LineageNotFound
    if not isinstance(cursor, str):
        raise InvalidLineageCursor
    objects = bounded_draft_text(ClinicalDraft.objects.select_related('parent'))

    def read(pk):
        draft = objects.filter(pk=pk).first()
        if draft is not None:
            materialize_draft_text(draft)
        return draft

    anchor = read(anchor_id)
    if anchor is None:
        raise LineageNotFound
    if draft_text_uninspected(anchor):
        if cursor:
            raise InvalidLineageCursor
        return {'anchor_id': anchor_id, 'status': 'oversized', 'rows': [], 'next_cursor': None}
    if not valid_payload(anchor):
        if cursor:
            raise InvalidLineageCursor
        return {'anchor_id': anchor_id, 'status': 'inconsistent', 'rows': [], 'next_cursor': None}
    current, depth = anchor, 0
    if cursor:
        current_id, expected, depth = _decode(cursor, anchor)
        current = read(current_id)
        if (current is None or draft_text_uninspected(current) or not valid_payload(current)
                or not constant_time_compare(expected, _keyed_hash(current.payload_sha256))):
            raise InvalidLineageCursor
    rows = []
    expected_current_hash = None
    for step in range(PAGE_SIZE):
        if current is not None and draft_text_uninspected(current):
            return {'anchor_id': anchor_id, 'status': 'oversized', 'rows': rows, 'next_cursor': None}
        if (current is None or not valid_payload(current)
                or (expected_current_hash is not None
                    and not constant_time_compare(expected_current_hash, current.payload_sha256))):
            return {'anchor_id': anchor_id, 'status': 'inconsistent', 'rows': rows, 'next_cursor': None}
        if current.parent_id is None:
            return {'anchor_id': anchor_id, 'status': 'no_parent', 'rows': rows, 'next_cursor': None}
        if not valid_draft(current):
            return {'anchor_id': anchor_id, 'status': 'inconsistent', 'rows': rows, 'next_cursor': None}
        parent = current.parent
        expected_current_hash = current.parent_payload_sha256
        depth += 1
        rows.append({'child_id': current.pk, 'parent_id': parent.pk, 'depth': depth})
        if step == PAGE_SIZE - 1:
            # valid_draft already validated this parent's payload. Its parent ID
            # can tell us whether continuation is needed without another query.
            current = parent
        else:
            current = read(parent.pk)
    more = current.parent_id is not None
    return {'anchor_id': anchor_id, 'status': 'more' if more else 'no_parent', 'rows': rows,
            'next_cursor': _encode(anchor, current, depth) if more else None}
