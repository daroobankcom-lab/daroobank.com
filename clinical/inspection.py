"""Bounded technical clues for synthetic drafts, not evidence verification."""
from daroobank.account_checks import current_account_ids

from .draft_reads import bounded_draft_text, draft_text_uninspected, materialize_draft_text
from .evidence import MAX_INSPECTION_DRAFTS, inspection_evidence_statuses
from .models import ClinicalDraft
from .services import valid_draft

BATCH_SIZE = MAX_INSPECTION_DRAFTS
MAX_PK = 9_223_372_036_854_775_807
CATEGORIES = ('available', 'draft_invalid', 'author_missing', 'evidence_invalid', 'evidence_over_limit', 'oversized')


class InvalidInspection(ValueError):
    """The position or category is invalid."""


def inspect_drafts(*, after=0, category=''):
    """Inspect one ID-ordered batch; classify before filtering, with no writes."""
    if (type(after) is not int or not 0 <= after <= MAX_PK
            or not isinstance(category, str) or category not in ('', *CATEGORIES)):
        raise InvalidInspection
    drafts = list(bounded_draft_text(ClinicalDraft.objects.select_related('parent')
                  .filter(pk__gt=after).order_by('pk'))[:BATCH_SIZE + 1])
    batch = drafts[:BATCH_SIZE]
    for draft in batch:
        materialize_draft_text(draft)
    valid = [draft for draft in batch if not draft_text_uninspected(draft) and valid_draft(draft)]
    # Existence is a separate current observation, not identity or qualification.
    # Invalid drafts take precedence; no related rows are scanned for them.
    authors = current_account_ids([draft.author_id for draft in valid], using=valid[0]._state.db) if valid else set()
    valid_ids = {draft.pk for draft in valid}
    with_author = [draft for draft in valid if draft.author_id in authors]
    statuses = inspection_evidence_statuses(with_author) if with_author else {}
    rows = []
    for draft in batch:
        if draft_text_uninspected(draft):
            status = 'oversized'
        elif draft.pk not in valid_ids:
            status = 'draft_invalid'
        elif draft.author_id not in authors:
            status = 'author_missing'
        else:
            evidence = statuses[draft.pk]
            status = {'available': 'available', 'invalid': 'evidence_invalid', 'over_limit': 'evidence_over_limit'}[evidence]
        if not category or status == category:
            rows.append({'id': draft.pk, 'status': status})
    return {'after': after, 'category': category, 'scanned': len(batch), 'rows': rows,
            'next_after': batch[-1].pk if len(drafts) > BATCH_SIZE else None}
