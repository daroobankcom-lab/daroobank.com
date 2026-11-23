"""Bounded display helper, not review validation or an audit."""
from django.contrib.auth import get_user_model

MAX_RECENT_REVIEWS = 25


def recent_reviews_with_reviewers(queryset):
    """Read a scoped review queryset without joins that can hide broken FKs.

    The caller must provide an unsliced queryset scoped to one authorized parent. The account
    lookup is a separate read, not proof of historical existence or authority.
    """
    rows = list(queryset.select_related(None).order_by('-pk')[:MAX_RECENT_REVIEWS])
    ids = {row.reviewer_id for row in rows if row.reviewer_id is not None}
    users = get_user_model().objects.using(queryset.db).in_bulk(ids) if ids else {}
    for row in rows:
        row.display_reviewer = users.get(row.reviewer_id)
    return rows
