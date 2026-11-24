"""Bounded synthetic candidate review clues; never authentication or audit."""
from django.core.exceptions import PermissionDenied
from django.db.models import Case, F, JSONField, TextField, Value, When
from django.db.models.functions import Cast, Length, Substr

from catalog.comparisons import valid_candidate as valid_product
from catalog.intake import MAX_PK, require_staff
from catalog.models import ProductCandidate, ProductCandidateReview
from catalog.review_inspection import classify_review as classify_product
from pricing.comparisons import valid_candidate as valid_price
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.review_inspection import classify_review as classify_price

from .account_checks import current_account_ids

BATCH_SIZE = 50
# Bounds characters in the database's JSON textual representation, not DB work.
MAX_CANDIDATE_JSON_TEXT_LENGTH = 65_536
MAX_REVIEW_JSON_TEXT_LENGTH = 65_536
MAX_REVIEW_REASON_LENGTH = 1_000
CATEGORIES = ('consistent', 'invalid_record', 'oversized')
_DOMAINS = {
    'product': (ProductCandidate, ProductCandidateReview, valid_product, classify_product, 'catalog.view_productcandidate'),
    'price': (PriceCandidate, PriceCandidateReview, valid_price, classify_price, 'pricing.view_pricecandidate'),
}


class InvalidCandidateReviewScan(ValueError):
    pass


class ReviewScanNotFound(ValueError):
    pass


def _review_batch(model, candidate_id, after):
    """Return bounded fields from one SELECT; deferred originals must not be accessed."""
    return list(model.objects.filter(candidate_id=candidate_id, pk__gt=after)
        .defer('review_snapshot', 'reason')
        .annotate(_json_length=Length(Cast('review_snapshot', TextField())))
        .annotate(_bounded_json=Case(
            When(_json_length__lte=MAX_REVIEW_JSON_TEXT_LENGTH, then=F('review_snapshot')),
            default=Value(None), output_field=JSONField()),
            _bounded_reason=Substr('reason', 1, MAX_REVIEW_REASON_LENGTH + 1))
        .order_by('pk')[:BATCH_SIZE + 1])


def inspect_reviews(*, actor, domain, candidate_id, after=0, category=''):
    """Scan one authorized candidate's next 50 IDs; filter only within that batch."""
    if not isinstance(domain, str) or domain not in _DOMAINS:
        raise InvalidCandidateReviewScan
    candidate_model, review_model, validate, classify, permission = _DOMAINS[domain]
    if actor is None:
        raise PermissionDenied
    require_staff(actor, permission)
    if type(candidate_id) is not int or not 1 <= candidate_id <= MAX_PK:
        raise ReviewScanNotFound
    if (type(after) is not int or not 0 <= after <= MAX_PK
            or not isinstance(category, str) or category not in ('', *CATEGORIES)):
        raise InvalidCandidateReviewScan
    candidate = (candidate_model.objects.filter(pk=candidate_id).defer('source_fields')
        .annotate(_json_length=Length(Cast('source_fields', TextField())))
        .annotate(_bounded_json=Case(
            When(_json_length__lte=MAX_CANDIDATE_JSON_TEXT_LENGTH, then=F('source_fields')),
            default=Value(None), output_field=JSONField())).first())
    if candidate is None:
        raise ReviewScanNotFound
    # Populate the deferred field from the same SELECT, even for oversized or
    # SQL-null rows, so a validator cannot trigger an unbounded lazy fetch.
    candidate.source_fields = candidate._bounded_json
    stagers = current_account_ids([candidate.staged_by_id], using=candidate._state.db)
    current_valid = validate(candidate) and candidate.staged_by_id in stagers
    # No inner account join: the snapshot check doesn't establish reviewer existence.
    # Return at most a bounded snapshot and a reason prefix from this one SELECT;
    # database casting, storage and work are not bounded by the transfer limit.
    reviews = _review_batch(review_model, candidate_id, after)
    batch = reviews[:BATCH_SIZE]
    rows = []
    for review in batch:
        # Never classify from a partial record; keep it as an explicit unknown.
        if ((review._json_length is not None and review._json_length > MAX_REVIEW_JSON_TEXT_LENGTH)
                or (isinstance(review._bounded_reason, str) and len(review._bounded_reason) > MAX_REVIEW_REASON_LENGTH)):
            status, comparison = 'oversized', 'unknown'
        else:
            review.review_snapshot = review._bounded_json
            review.reason = review._bounded_reason
            status, comparison = classify(review, candidate, current_valid)
        if not category or category == status:
            rows.append({'id': review.pk, 'status': status, 'comparison': comparison})
    return {'candidate_id': candidate_id, 'after': after, 'category': category, 'scanned': len(batch),
            'rows': rows, 'next_after': batch[-1].pk if len(reviews) > BATCH_SIZE else None}
