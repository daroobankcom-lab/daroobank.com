"""Selected source-claim evidence note transfer bounds."""
from django.db.models.functions import Substr

MAX_NOTE_LENGTH = 1000


def bounded_claim_notes(queryset):
    return queryset.defer('evidence_note').annotate(_note_prefix=Substr('evidence_note', 1, MAX_NOTE_LENGTH + 1))


def materialize_claim_note(claim):
    # Any prefix longer than the actual max proves this field invalid, without
    # passing a partial note to the full-record validator or a template.
    claim.note_oversized = isinstance(claim._note_prefix, str) and len(claim._note_prefix) > MAX_NOTE_LENGTH
    claim.evidence_note = None if claim.note_oversized else claim._note_prefix
