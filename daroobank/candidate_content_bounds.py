"""Selected candidate JSON transfer limit, not a database work limit."""
from django.db.models import Case, F, JSONField, TextField, Value, When
from django.db.models.functions import Cast, Length

MAX_CANDIDATE_JSON_TEXT_LENGTH = 65_536


def bounded_candidates(queryset):
    return (queryset.defer('source_fields')
        .annotate(_candidate_json_length=Length(Cast('source_fields', TextField())))
        .annotate(_bounded_candidate_json=Case(
            When(_candidate_json_length__lte=MAX_CANDIDATE_JSON_TEXT_LENGTH, then=F('source_fields')),
            default=Value(None), output_field=JSONField())))


def materialize_candidate(candidate):
    candidate.content_oversized = (candidate._candidate_json_length is not None
        and candidate._candidate_json_length > MAX_CANDIDATE_JSON_TEXT_LENGTH)
    candidate.source_fields = None if candidate.content_oversized else candidate._bounded_candidate_json
