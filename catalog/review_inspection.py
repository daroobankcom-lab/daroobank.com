"""Selected product-review consistency clues, not an authenticity audit."""
import re

from daroobank.validation import valid_review_reason

from .intake import MAX_PK, IntakeError, fingerprint, valid_fields, valid_source
from .models import ProductCandidateReview

SNAPSHOT_KEYS = frozenset({'source_name', 'source_url', 'source_fields', 'staged_by_id', 'source_rights_attested'})
_HASH = re.compile(r'^[0-9a-f]{64}$')


def _id(value):
    return type(value) is int and 1 <= value <= MAX_PK


def classify_review(review, candidate, current_valid):
    """Return fixed status and comparison without accessing accounts or querying."""
    snapshot = review.review_snapshot
    if (not _id(candidate.pk) or not _id(review.candidate_id) or review.candidate_id != candidate.pk
            or not _id(review.reviewer_id) or not isinstance(review.decision, str)
            or review.decision not in dict(ProductCandidateReview.DECISIONS)
            or not valid_review_reason(review.reason) or review.reason != review.reason.strip()
            or not isinstance(review.candidate_payload_sha256, str)
            or not _HASH.fullmatch(review.candidate_payload_sha256)
            or not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_KEYS
            or snapshot['source_rights_attested'] is not True or not _id(snapshot['staged_by_id'])
            or snapshot['staged_by_id'] == review.reviewer_id):
        return 'invalid_record', 'unknown'
    try:
        valid_source(snapshot['source_name'], snapshot['source_url'])
        valid_fields(snapshot['source_fields'])
        if fingerprint(snapshot['source_name'], snapshot['source_url'], snapshot['source_fields']) != review.candidate_payload_sha256:
            return 'invalid_record', 'unknown'
    except (IntakeError, ValueError, TypeError, UnicodeError, OverflowError):
        return 'invalid_record', 'unknown'
    if not current_valid or not _id(candidate.staged_by_id):
        return 'consistent', 'unknown'
    current = {'source_name': candidate.source_name, 'source_url': candidate.source_url,
               'source_fields': candidate.source_fields, 'staged_by_id': candidate.staged_by_id,
               'source_rights_attested': candidate.source_rights_attested}
    return ('consistent', 'same' if snapshot == current and review.candidate_payload_sha256 == candidate.payload_sha256
            else 'different')
