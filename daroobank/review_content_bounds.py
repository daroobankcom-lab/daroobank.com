"""Local display/inspection transfer thresholds, not storage constraints."""
from django.db.models import Case, TextField, Value, When
from django.db.models.functions import Cast, Length, Substr

from .bounded_json_decode import decode_bounded_json

MAX_REVIEW_JSON_TEXT_LENGTH = 65_536
MAX_REVIEW_REASON_LENGTH = 1_000


def bounded_review_fields(queryset, *, snapshot_field='review_snapshot'):
    """Select only bounded snapshot/reason values; database work is not bounded."""
    if snapshot_field not in ('review_snapshot', 'graph_snapshot'):
        raise ValueError('Unsupported review snapshot field')
    return (queryset.defer(snapshot_field, 'reason')
        .annotate(_json_length=Length(Cast(snapshot_field, TextField())))
        .annotate(_bounded_json=Case(
            When(_json_length__lte=MAX_REVIEW_JSON_TEXT_LENGTH, then=Cast(snapshot_field, TextField())),
            default=Value(None), output_field=TextField()),
            _bounded_reason=Substr('reason', 1, MAX_REVIEW_REASON_LENGTH + 1)))


def materialize_review_fields(row, *, snapshot_field='review_snapshot'):
    """Replace deferred originals to avoid lazy fetching; never classify partial content."""
    if snapshot_field not in ('review_snapshot', 'graph_snapshot'):
        raise ValueError('Unsupported review snapshot field')
    row.content_oversized = ((row._json_length is not None and row._json_length > MAX_REVIEW_JSON_TEXT_LENGTH)
        or (isinstance(row._bounded_reason, str) and len(row._bounded_reason) > MAX_REVIEW_REASON_LENGTH))
    setattr(row, snapshot_field, None if row.content_oversized else decode_bounded_json(row._bounded_json))
    row.reason = None if row.content_oversized else row._bounded_reason
