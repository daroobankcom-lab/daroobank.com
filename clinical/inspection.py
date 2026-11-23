"""Bounded technical clues for synthetic drafts, not evidence verification."""
from .evidence import evidence_state
from .models import ClinicalDraft
from .services import valid_draft

BATCH_SIZE = 50
MAX_PK = 9_223_372_036_854_775_807
CATEGORIES = ('available', 'draft_invalid', 'evidence_invalid', 'evidence_over_limit')


class InvalidInspection(ValueError):
    """The position or category is invalid."""


def inspect_drafts(*, after=0, category=''):
    """Inspect one ID-ordered batch; classify before filtering, with no writes."""
    if (type(after) is not int or not 0 <= after <= MAX_PK
            or not isinstance(category, str) or category not in ('', *CATEGORIES)):
        raise InvalidInspection
    drafts = list(ClinicalDraft.objects.select_related('parent').filter(pk__gt=after).order_by('pk')[:BATCH_SIZE + 1])
    batch = drafts[:BATCH_SIZE]
    rows = []
    for draft in batch:
        if not valid_draft(draft):
            status = 'draft_invalid'
        else:
            evidence = evidence_state(draft)['status']
            status = {'available': 'available', 'invalid': 'evidence_invalid', 'over_limit': 'evidence_over_limit'}[evidence]
        if not category or status == category:
            rows.append({'id': draft.pk, 'status': status})
    return {'after': after, 'category': category, 'scanned': len(batch), 'rows': rows,
            'next_after': batch[-1].pk if len(drafts) > BATCH_SIZE else None}
