"""Explicit one-row synthetic projection repair; never validate or publish content."""
import json
import re
import time
import unicodedata
from datetime import datetime

from django.conf import settings
from django.core import signing
from django.db import connections, transaction
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import PRESENTATION_SEARCH_FIELDS, ProductPresentation
from .normalization import normalize_search

MAX_PK = 9_223_372_036_854_775_807
MAX_TOKEN_LENGTH = 512
MAX_SEARCH_LENGTH = 8192
TOKEN_AGE = 600
SALT = 'catalog.synthetic-projection-repair.v1'
DB_ALIAS = 'default'
REQUIRED_FIELDS = set(PRESENTATION_SEARCH_FIELDS) - {'name_en', 'irc'}


class ProjectionRepairError(ValueError):
    """An unavailable, unsafe, invalid or stale repair request."""


def _require_development():
    if not settings.DEBUG:
        raise ProjectionRepairError('Projection repair is restricted to development.')


def _id(value):
    return type(value) is int and 1 <= value <= MAX_PK


def _expected(row):
    for field in PRESENTATION_SEARCH_FIELDS:
        value = row[field]
        max_length = ProductPresentation._meta.get_field(field).max_length
        if (not isinstance(value, str) or len(value) > max_length
                or any(unicodedata.category(c) in ('Cc', 'Cs') for c in value)
                or (field in REQUIRED_FIELDS and not normalize_search(value))):
            return None
    if not isinstance(row['search_text'], str) or len(row['search_text']) > MAX_SEARCH_LENGTH:
        return None
    if not isinstance(row['irc_normalized'], str) or len(row['irc_normalized']) > 80:
        return None
    search = normalize_search(' '.join(row[field] for field in PRESENTATION_SEARCH_FIELDS))
    irc = normalize_search(row['irc'])
    if len(search) > MAX_SEARCH_LENGTH or len(irc) > 80:
        return None
    return {'search_text': search, 'irc_normalized': irc}


def _digest(kind, value):
    return salted_hmac(f'{SALT}.{kind}', value, algorithm='sha256').hexdigest()


def _database_digest():
    db = connections[DB_ALIAS].settings_dict
    # Do not include credentials or expose DB coordinates in the signed payload.
    identity = json.dumps([DB_ALIAS, db.get('ENGINE'), db.get('NAME'), db.get('HOST'), db.get('PORT')],
                          ensure_ascii=True, separators=(',', ':'))
    return _digest('database', identity)


def _json_default(value):
    if isinstance(value, datetime):
        # DjangoJSONEncoder truncates datetimes to milliseconds, losing changes
        # within a millisecond; retain the complete database microsecond value.
        return {'datetime': value.isoformat(timespec='microseconds')}
    raise TypeError('Unexpected snapshot value')


def _state_digest(row, expected):
    state = json.dumps({'row': row, 'expected': expected}, default=_json_default,
                       ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return _digest('state', state)


def _changed(row, expected):
    return [field for field in ('search_text', 'irc_normalized') if row[field] != expected[field]]


def preview_projection(*, presentation_id):
    """Read a single row; output only fixed statuses, ID, field names and a signed token."""
    _require_development()
    if not _id(presentation_id):
        raise ProjectionRepairError('Invalid presentation.')
    row = ProductPresentation.objects.using(DB_ALIAS).filter(pk=presentation_id).values().first()
    if row is None:
        raise ProjectionRepairError('Invalid presentation.')
    expected = _expected(row)
    if expected is None:
        return {'id': presentation_id, 'status': 'unsafe', 'fields': []}
    fields = _changed(row, expected)
    if not fields:
        return {'id': presentation_id, 'status': 'consistent', 'fields': []}
    token = signing.dumps({'id': presentation_id, 'state': _state_digest(row, expected),
                           'database': _database_digest()}, salt=SALT)
    return {'id': presentation_id, 'status': 'needs_repair', 'fields': fields, 'token': token}


def apply_projection(*, presentation_id, token, synthetic_confirmed=False):
    """Recheck signed observation while holding a row lock; change only derived columns."""
    _require_development()
    if (synthetic_confirmed is not True or not _id(presentation_id) or not isinstance(token, str) or not token
            or len(token) > MAX_TOKEN_LENGTH or token.startswith('.')):
        raise ProjectionRepairError('Invalid or stale repair request.')
    try:
        data = signing.loads(token, salt=SALT, max_age=TOKEN_AGE)
        timestamp = signing.b62_decode(token.rsplit(':', 2)[-2])
        if (timestamp > time.time() or not isinstance(data, dict) or set(data) != {'id', 'state', 'database'}
                or type(data['id']) is not int or data['id'] != presentation_id
                or not isinstance(data['state'], str) or not re.fullmatch(r'[0-9a-f]{64}', data['state'])
                or not isinstance(data['database'], str) or not re.fullmatch(r'[0-9a-f]{64}', data['database'])
                or not constant_time_compare(data['database'], _database_digest())):
            raise ProjectionRepairError('Invalid or stale repair request.')
    except (signing.BadSignature, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        raise ProjectionRepairError('Invalid or stale repair request.') from exc
    with transaction.atomic(using=DB_ALIAS):
        row = ProductPresentation.objects.using(DB_ALIAS).select_for_update().filter(pk=presentation_id).values().first()
        if row is None:
            raise ProjectionRepairError('Invalid or stale repair request.')
        expected = _expected(row)
        if expected is None or not constant_time_compare(data['state'], _state_digest(row, expected)):
            raise ProjectionRepairError('Invalid or stale repair request.')
        fields = _changed(row, expected)
        if not fields:
            raise ProjectionRepairError('Invalid or stale repair request.')
        # A deliberate restricted bulk update avoids model validation of unrelated
        # fields and changes no source, identity, publication or provenance field.
        ProductPresentation.objects.using(DB_ALIAS).filter(pk=presentation_id).update(
            **{field: expected[field] for field in fields})
    return {'id': presentation_id, 'status': 'repaired', 'fields': fields}
