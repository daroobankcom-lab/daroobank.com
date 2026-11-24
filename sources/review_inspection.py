"""Bounded source-review snapshot clues, not provenance or source authorization."""
import re
from datetime import date

from django.db.models.functions import Substr

from daroobank.validation import valid_review_reason
from daroobank.review_content_bounds import bounded_review_fields, materialize_review_fields
from .models import SourceClaim, SourceClaimReview
from .services import FIELDS, MAX_PK, VIEW, ClaimError, fingerprint, require_staff, snapshot, valid_claim, validate_data

BATCH_SIZE = 50
CATEGORIES = ('consistent', 'invalid_record', 'oversized')
_HASH = re.compile(r'^[0-9a-f]{64}$')


class InvalidReviewInspection(ValueError):
    pass


class ReviewInspectionNotFound(ValueError):
    pass


def _id(value):
    return type(value) is int and 1 <= value <= MAX_PK


def classify_review(review, claim, current_valid):
    """Classify one stored assertion; never return its untrusted content."""
    historical = review.review_snapshot
    if (not isinstance(historical, dict) or set(historical) != set(FIELDS) | {'recorded_by_id'}
            or not _id(review.claim_id) or review.claim_id != claim.pk
            or not _id(review.reviewer_id) or not _id(historical.get('recorded_by_id'))
            or review.reviewer_id == historical['recorded_by_id']
            or not isinstance(review.decision, str) or review.decision not in dict(SourceClaimReview.DECISIONS)
            or not valid_review_reason(review.reason) or review.reason != review.reason.strip()
            or not isinstance(review.claim_payload_sha256, str) or not _HASH.fullmatch(review.claim_payload_sha256)):
        return 'invalid_record', 'unknown'
    try:
        data = {field: historical[field] for field in FIELDS}
        for field in ('starts_on', 'expires_on'):
            value = data[field]
            if value is not None:
                if not isinstance(value, str):
                    return 'invalid_record', 'unknown'
                parsed = date.fromisoformat(value)
                if parsed.isoformat() != value:
                    return 'invalid_record', 'unknown'
                data[field] = parsed
        validate_data(data)
        if snapshot(data) != {field: historical[field] for field in FIELDS} or fingerprint(data) != review.claim_payload_sha256:
            return 'invalid_record', 'unknown'
    except (ClaimError, ValueError, TypeError, KeyError, UnicodeError, AttributeError, OverflowError):
        return 'invalid_record', 'unknown'
    comparison = ('unknown' if not current_valid or not _id(claim.recorded_by_id) else
                  'same' if review.claim_payload_sha256 == claim.payload_sha256 and
                  historical['recorded_by_id'] == claim.recorded_by_id else 'different')
    return 'consistent', comparison


def inspect_reviews(*, actor, claim_id, after=0, category=''):
    """Scan at most 50 review IDs, filtering only within the current batch."""
    require_staff(actor, VIEW)
    if not _id(claim_id):
        raise ReviewInspectionNotFound
    if (type(after) is not int or not 0 <= after <= MAX_PK
            or not isinstance(category, str) or category not in ('', *CATEGORIES)):
        raise InvalidReviewInspection
    # A bypassed TextField can exceed its validator limit; select one extra
    # character so validation fails without loading its full content.
    claim = (SourceClaim.objects.filter(pk=claim_id).defer('evidence_note')
             .annotate(_note_prefix=Substr('evidence_note', 1, 1001)).first())
    if claim is None:
        raise ReviewInspectionNotFound
    claim.evidence_note = claim._note_prefix
    current_valid = valid_claim(claim)
    # Avoid an inner reviewer join: missing accounts do not hide review rows.
    reviews = list(bounded_review_fields(SourceClaimReview.objects.filter(claim_id=claim_id, pk__gt=after)).order_by('pk')[:BATCH_SIZE + 1])
    batch = reviews[:BATCH_SIZE]
    rows = []
    for review in batch:
        materialize_review_fields(review)
        if review.content_oversized:
            status, comparison = 'oversized', 'unknown'
        else:
            status, comparison = classify_review(review, claim, current_valid)
        if not category or category == status:
            rows.append({'id': review.pk, 'status': status, 'comparison': comparison})
    return {'claim_id': claim_id, 'after': after, 'category': category, 'scanned': len(batch), 'rows': rows,
            'next_after': batch[-1].pk if len(reviews) > BATCH_SIZE else None}
