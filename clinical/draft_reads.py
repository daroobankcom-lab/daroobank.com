"""Selected clinical draft and immediate-parent text transfer bounds."""
from django.db.models.functions import Substr

MAX_STATEMENT_LENGTH = 4000
MAX_REASON_TRANSFER_LENGTH = 1000


def bounded_draft_text(queryset):
    """Queryset must select_related('parent'); originals never lazily fetched."""
    return (queryset.defer('statement', 'change_reason', 'parent__statement', 'parent__change_reason')
        .annotate(_statement_prefix=Substr('statement', 1, MAX_STATEMENT_LENGTH + 1),
                  _reason_prefix=Substr('change_reason', 1, MAX_REASON_TRANSFER_LENGTH + 1),
                  _parent_statement_prefix=Substr('parent__statement', 1, MAX_STATEMENT_LENGTH + 1),
                  _parent_reason_prefix=Substr('parent__change_reason', 1, MAX_REASON_TRANSFER_LENGTH + 1)))


def _materialize(draft, statement, reason):
    oversized_statement = isinstance(statement, str) and len(statement) > MAX_STATEMENT_LENGTH
    oversized_reason = isinstance(reason, str) and len(reason) > MAX_REASON_TRANSFER_LENGTH
    draft.bounded_text_oversized = oversized_statement or oversized_reason
    # A reason's canonical validator permits some long whitespace-bearing values,
    # so never classify an oversize prefix as if it were the complete value.
    draft.statement = None if oversized_statement else statement
    draft.change_reason = None if oversized_reason else reason


def materialize_draft_text(draft):
    _materialize(draft, draft._statement_prefix, draft._reason_prefix)
    parent = draft._state.fields_cache.get('parent')
    if parent is not None:
        _materialize(parent, draft._parent_statement_prefix, draft._parent_reason_prefix)


def draft_text_uninspected(draft):
    parent = draft._state.fields_cache.get('parent')
    return bool(draft.bounded_text_oversized or (parent and parent.bounded_text_oversized))
