"""Bounded technical checks of synthetic review snapshots; not an audit."""
from datetime import date
from types import SimpleNamespace

from .evidence import reviewed_evidence
from .models import ClinicalDraft, ClinicalDraftReview
from .services import FIELDS, VIEW, require_staff, snapshot, valid_draft, valid_payload
from daroobank.validation import valid_review_reason

BATCH_SIZE = 50
MAX_PK = 9_223_372_036_854_775_807
CATEGORIES = ('consistent', 'legacy', 'invalid_record', 'invalid_evidence')
BASE_KEYS = set(FIELDS) | {'parent_id', 'parent_payload_sha256', 'change_reason', 'author_id'}
EVIDENCE_KEYS = {'evidence_version', 'evidence_fingerprint', 'evidence_snapshot'}


class InvalidReviewInspection(ValueError):
    pass


class ReviewInspectionNotFound(ValueError):
    pass


def _id(value):
    return type(value) is int and 1 <= value <= MAX_PK


def classify_review(review, draft, current_valid):
    """Return only fixed statuses; never return the untrusted snapshot or reason."""
    historical = review.review_snapshot
    if (not isinstance(historical, dict) or set(historical) not in (BASE_KEYS, BASE_KEYS | EVIDENCE_KEYS)
            or not _id(review.draft_id) or review.draft_id != draft.pk
            or not _id(review.reviewer_id) or not _id(historical.get('author_id'))
            or review.reviewer_id == historical['author_id']
            or review.decision not in dict(ClinicalDraftReview.DECISIONS)
            or not valid_review_reason(review.reason) or review.reason != review.reason.strip()):
        return 'invalid_record', 'unknown'
    try:
        parent_id = historical['parent_id']
        if parent_id is not None and not _id(parent_id):
            return 'invalid_record', 'unknown'
        data = {key: historical[key] for key in FIELDS}
        for key in ('reference_published_on', 'reference_accessed_on'):
            value = data[key]
            if value is not None:
                if not isinstance(value, str):
                    return 'invalid_record', 'unknown'
                data[key] = date.fromisoformat(value)
        draft_copy = SimpleNamespace(pk=review.draft_id, **data, parent_id=parent_id,
                                     parent_payload_sha256=historical['parent_payload_sha256'],
                                     change_reason=historical['change_reason'], payload_sha256=review.draft_payload_sha256)
        if (not valid_payload(draft_copy)
                or snapshot(data, parent_id, historical['parent_payload_sha256'], historical['change_reason'])
                != {key: historical[key] for key in BASE_KEYS - {'author_id'}}):
            return 'invalid_record', 'unknown'
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        return 'invalid_record', 'unknown'
    comparison = ('unknown' if not current_valid else
                  'same' if review.draft_payload_sha256 == draft.payload_sha256 and historical['author_id'] == draft.author_id
                  else 'different')
    evidence = reviewed_evidence(review)
    if evidence['status'] == 'legacy':
        return 'legacy', comparison
    if evidence['status'] == 'invalid' or any(item['recorded_by_id'] == review.reviewer_id for item in evidence['items']):
        return 'invalid_evidence', comparison
    return 'consistent', comparison


def inspect_reviews(*, actor, draft_id, after=0, category=''):
    """Scan up to 50 reviews for one version, filtering only within the batch."""
    require_staff(actor, VIEW)
    if not _id(draft_id):
        raise ReviewInspectionNotFound
    if (type(after) is not int or not 0 <= after <= MAX_PK
            or not isinstance(category, str) or category not in ('', *CATEGORIES)):
        raise InvalidReviewInspection
    # No inner author/reviewer join: missing actors must not hide history rows.
    draft = ClinicalDraft.objects.select_related('parent').filter(pk=draft_id).first()
    if draft is None:
        raise ReviewInspectionNotFound
    current_valid = valid_draft(draft)
    reviews = list(ClinicalDraftReview.objects.filter(draft_id=draft_id, pk__gt=after).order_by('pk')[:BATCH_SIZE + 1])
    batch = reviews[:BATCH_SIZE]
    rows = []
    for review in batch:
        status, comparison = classify_review(review, draft, current_valid)
        if not category or status == category:
            rows.append({'id': review.pk, 'status': status, 'comparison': comparison})
    return {'draft_id': draft_id, 'after': after, 'category': category, 'scanned': len(batch), 'rows': rows,
            'next_after': batch[-1].pk if len(reviews) > BATCH_SIZE else None}
