"""Bounded display helper, not review validation or an audit."""
from django.contrib.auth import get_user_model
from django.db.models import Case, F, JSONField, TextField, Value, When
from django.db.models.functions import Cast, Length, Substr

from .review_content_bounds import MAX_REVIEW_JSON_TEXT_LENGTH, MAX_REVIEW_REASON_LENGTH

MAX_RECENT_REVIEWS = 25


def recent_reviews_with_reviewers(queryset):
    """Read a scoped review queryset without joins that can hide broken FKs.

    The caller must provide an unsliced queryset scoped to one authorized parent. The account
    lookup is a separate read, not proof of historical existence or authority.
    """
    rows = list(queryset.select_related(None).defer('review_snapshot', 'reason')
        .annotate(_json_length=Length(Cast('review_snapshot', TextField())))
        .annotate(_bounded_json=Case(
            When(_json_length__lte=MAX_REVIEW_JSON_TEXT_LENGTH, then=F('review_snapshot')),
            default=Value(None), output_field=JSONField()),
            _bounded_reason=Substr('reason', 1, MAX_REVIEW_REASON_LENGTH + 1))
        .order_by('-pk')[:MAX_RECENT_REVIEWS])
    for row in rows:
        row.content_oversized = ((row._json_length is not None and row._json_length > MAX_REVIEW_JSON_TEXT_LENGTH)
            or (isinstance(row._bounded_reason, str) and len(row._bounded_reason) > MAX_REVIEW_REASON_LENGTH))
        # Prevent accidental lazy reads. Callers must not classify or render partial data.
        row.review_snapshot = None if row.content_oversized else row._bounded_json
        row.reason = None if row.content_oversized else row._bounded_reason
    ids = {row.reviewer_id for row in rows if row.reviewer_id is not None}
    users = get_user_model().objects.using(queryset.db).in_bulk(ids) if ids else {}
    for row in rows:
        row.display_reviewer = users.get(row.reviewer_id)
    return rows
