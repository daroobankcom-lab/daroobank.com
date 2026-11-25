"""Bound candidate JSON selected by private receipt inspection queries."""
from django.db.models import Case, TextField, Value, When
from django.db.models.functions import Cast, Length

from daroobank.bounded_json_decode import decode_bounded_json
from daroobank.candidate_content_bounds import MAX_CANDIDATE_JSON_TEXT_LENGTH


def bounded_manifest_candidates(queryset, candidate_field):
    if candidate_field not in ('product_candidate', 'price_candidate'):
        raise ValueError('Unsupported candidate relation')
    path = candidate_field + '__source_fields'
    return (queryset.select_related(candidate_field).defer(path)
        .annotate(_candidate_json_length=Length(Cast(path, TextField())))
        .annotate(_bounded_candidate_json=Case(
            When(_candidate_json_length__lte=MAX_CANDIDATE_JSON_TEXT_LENGTH, then=Cast(path, TextField())),
            default=Value(None), output_field=TextField())))


def materialize_manifest_candidate(item, candidate_field):
    """Populate the joined model without ever triggering a deferred-field read."""
    item.candidate_oversized = (item._candidate_json_length is not None
        and item._candidate_json_length > MAX_CANDIDATE_JSON_TEXT_LENGTH)
    candidate = getattr(item, candidate_field)
    if candidate is not None:
        candidate.source_fields = None if item.candidate_oversized else decode_bounded_json(item._bounded_candidate_json)
