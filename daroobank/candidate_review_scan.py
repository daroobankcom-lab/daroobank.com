"""Bounded synthetic candidate review clues; never authentication or audit."""
from django.core.exceptions import PermissionDenied

from catalog.comparisons import valid_candidate as valid_product
from catalog.intake import MAX_PK, require_staff
from catalog.models import ProductCandidate, ProductCandidateReview
from catalog.review_inspection import classify_review as classify_product
from pricing.comparisons import valid_candidate as valid_price
from pricing.models import PriceCandidate, PriceCandidateReview
from pricing.review_inspection import classify_review as classify_price

from .account_checks import current_account_ids

BATCH_SIZE = 50
CATEGORIES = ('consistent', 'invalid_record')
_DOMAINS = {
    'product': (ProductCandidate, ProductCandidateReview, valid_product, classify_product, 'catalog.view_productcandidate'),
    'price': (PriceCandidate, PriceCandidateReview, valid_price, classify_price, 'pricing.view_pricecandidate'),
}


class InvalidCandidateReviewScan(ValueError):
    pass


class ReviewScanNotFound(ValueError):
    pass


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
    candidate = candidate_model.objects.filter(pk=candidate_id).first()
    if candidate is None:
        raise ReviewScanNotFound
    stagers = current_account_ids([candidate.staged_by_id], using=candidate._state.db)
    current_valid = validate(candidate) and candidate.staged_by_id in stagers
    # No inner account join: the snapshot check doesn't establish reviewer existence.
    reviews = list(review_model.objects.filter(candidate_id=candidate_id, pk__gt=after).order_by('pk')[:BATCH_SIZE + 1])
    batch = reviews[:BATCH_SIZE]
    rows = []
    for review in batch:
        status, comparison = classify(review, candidate, current_valid)
        if not category or category == status:
            rows.append({'id': review.pk, 'status': status, 'comparison': comparison})
    return {'candidate_id': candidate_id, 'after': after, 'category': category, 'scanned': len(batch),
            'rows': rows, 'next_after': batch[-1].pk if len(reviews) > BATCH_SIZE else None}
