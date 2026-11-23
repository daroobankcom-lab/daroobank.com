"""Bounded indexed IRC clues for staff; never an identity or uniqueness proof."""
import re
import unicodedata

from django.core import signing
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import ProductPresentation
from .normalization import normalize_search
from .quality import BATCH_SIZE, MAX_PK

CURSOR_SALT = 'catalog.quality.irc.cursor.v1'
CURSOR_MAX_AGE = 3600
MAX_CURSOR_LENGTH = 512


class InvalidIRCCursor(ValueError):
    pass


class QualityAnchorNotFound(ValueError):
    pass


def _safe_text(value):
    return isinstance(value, str) and len(value) <= 80 and not any(
        unicodedata.category(c) in ('Cc', 'Cs') for c in value
    )


def _anchor_code(anchor):
    if not _safe_text(anchor.irc) or not _safe_text(anchor.irc_normalized):
        return 'invalid', None
    code = normalize_search(anchor.irc)
    if len(code) > 80 or code != anchor.irc_normalized:
        return 'invalid', None
    if not code:
        return 'empty', None
    return 'available', code


def _digest(code):
    return salted_hmac(f'{CURSOR_SALT}.code', code, algorithm='sha256').hexdigest()


def _decode_cursor(token, anchor_id, code):
    if not isinstance(token, str) or not token or len(token) > MAX_CURSOR_LENGTH or token.startswith('.'):
        raise InvalidIRCCursor
    try:
        data = signing.loads(token, salt=CURSOR_SALT, max_age=CURSOR_MAX_AGE)
        if (not isinstance(data, dict) or set(data) != {'anchor', 'code', 'last'}
                or type(data['anchor']) is not int or data['anchor'] != anchor_id
                or type(data['last']) is not int or not 1 <= data['last'] <= MAX_PK
                or not isinstance(data['code'], str) or not re.fullmatch(r'[0-9a-f]{64}', data['code'])
                or not constant_time_compare(data['code'], _digest(code))):
            raise InvalidIRCCursor
        return data['last']
    except (signing.BadSignature, TypeError, ValueError, KeyError, OverflowError) as exc:
        raise InvalidIRCCursor from exc


def inspect_irc(*, anchor_id, cursor=''):
    """Inspect up to 50 indexed rows for an anchor; no consistent snapshot."""
    if type(anchor_id) is not int or not 1 <= anchor_id <= MAX_PK:
        raise QualityAnchorNotFound
    if not isinstance(cursor, str):
        raise InvalidIRCCursor
    anchor = ProductPresentation.objects.only('pk', 'irc', 'irc_normalized').filter(pk=anchor_id).first()
    if anchor is None:
        raise QualityAnchorNotFound
    status, code = _anchor_code(anchor)
    if status != 'available':
        if cursor:
            raise InvalidIRCCursor
        return {'anchor_id': anchor_id, 'status': status, 'limit': BATCH_SIZE, 'scanned': 0,
                'consistent': 0, 'inconsistent': 0, 'rows': [], 'next_cursor': None}
    last = _decode_cursor(cursor, anchor_id, code) if cursor else 0
    batch = list(ProductPresentation.objects.filter(irc_normalized=code, pk__gt=last).exclude(pk=anchor_id)
                 .only('pk', 'irc', 'irc_normalized').order_by('pk')[:BATCH_SIZE + 1])
    more = len(batch) > BATCH_SIZE
    rows = []
    for item in batch[:BATCH_SIZE]:
        item_status, item_code = _anchor_code(item)
        rows.append({'id': item.pk, 'status': 'consistent' if item_status == 'available' and item_code == code
                     else 'inconsistent'})
    next_cursor = signing.dumps({'anchor': anchor_id, 'code': _digest(code), 'last': rows[-1]['id']},
                                salt=CURSOR_SALT) if more and rows else None
    consistent = sum(row['status'] == 'consistent' for row in rows)
    return {'anchor_id': anchor_id, 'status': 'available', 'limit': BATCH_SIZE, 'scanned': len(rows),
            'consistent': consistent, 'inconsistent': len(rows) - consistent, 'rows': rows, 'next_cursor': next_cursor}
