"""Local display/inspection transfer thresholds, not storage constraints."""
from django.db.models import Case, F, JSONField, TextField, Value, When
from django.db.models.functions import Cast, Length, Substr

MAX_REVIEW_JSON_TEXT_LENGTH = 65_536
MAX_REVIEW_REASON_LENGTH = 1_000


def bounded_review_fields(queryset):
    """Select only bounded snapshot/reason values; database work is not bounded."""
    return (queryset.defer('review_snapshot', 'reason')
        .annotate(_json_length=Length(Cast('review_snapshot', TextField())))
        .annotate(_bounded_json=Case(
            When(_json_length__lte=MAX_REVIEW_JSON_TEXT_LENGTH, then=F('review_snapshot')),
            default=Value(None), output_field=JSONField()),
            _bounded_reason=Substr('reason', 1, MAX_REVIEW_REASON_LENGTH + 1)))


def materialize_review_fields(row):
    """Replace deferred originals to avoid lazy fetching; never classify partial content."""
    row.content_oversized = ((row._json_length is not None and row._json_length > MAX_REVIEW_JSON_TEXT_LENGTH)
        or (isinstance(row._bounded_reason, str) and len(row._bounded_reason) > MAX_REVIEW_REASON_LENGTH))
    row.review_snapshot = None if row.content_oversized else row._bounded_json
    row.reason = None if row.content_oversized else row._bounded_reason
