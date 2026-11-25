"""Selected price-review consistency clues, not a provenance or price audit."""
import csv
import hashlib
import io
import json
import re

from catalog.normalization import normalize_search
from daroobank.validation import has_control_or_surrogate, valid_review_reason

from .importer import FIELDS, IDENTITY_FIELDS, LIMITS, ImportValidationError, match_fields_valid, parse_csv, validate_source
from .models import PriceCandidateReview

MAX_PK = 9_223_372_036_854_775_807
_HASH = re.compile(r'^[0-9a-f]{64}$')
SNAPSHOT_KEYS = frozenset({'source_name', 'source_url', 'source_record_id', 'source_fields', 'amount_rial',
                           'source_rights_attested', 'staged_by_id', 'product'})
PRODUCT_KEYS = frozenset({'id', 'name_fa', *IDENTITY_FIELDS})
PRODUCT_LIMITS = {'name_fa': 200, 'irc': 80, 'manufacturer': 200, 'strength': 100,
                  'dosage_form': 100, 'package_description': 200}


def _id(value):
    return type(value) is int and 1 <= value <= MAX_PK


def _digest(payload):
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _valid_snapshot(snapshot, candidate_hash):
    if (not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_KEYS
            or snapshot['source_rights_attested'] is not True or not _id(snapshot['staged_by_id'])
            or type(snapshot['amount_rial']) is not int):
        return False
    fields = snapshot['source_fields']
    if (not isinstance(fields, dict) or set(fields) != set(FIELDS)
            or any(not isinstance(fields[key], str) or len(fields[key]) > LIMITS[key] for key in FIELDS)):
        return False
    try:
        if validate_source(snapshot['source_name'], snapshot['source_url']) != (snapshot['source_name'], snapshot['source_url']):
            return False
        stream = io.StringIO(newline='')
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(fields)
        parsed, _, amount, _, _ = parse_csv(io.BytesIO(stream.getvalue().encode('utf-8')))[0]
        return (parsed == fields and snapshot['source_record_id'] == fields['source_record_id']
                and snapshot['amount_rial'] == amount and match_fields_valid(fields)
                and _digest({'source_name': snapshot['source_name'], 'fields': fields}) == candidate_hash)
    except (ImportValidationError, ValueError, TypeError, UnicodeError, csv.Error, OverflowError):
        return False


def _valid_product(snapshot, fields, review):
    if (not isinstance(snapshot, dict) or set(snapshot) != PRODUCT_KEYS
            or not _id(snapshot['id']) or snapshot['id'] != review.reviewed_product_id
            or any(not isinstance(snapshot[key], str) or len(snapshot[key]) > limit
                   or has_control_or_surrogate(snapshot[key]) for key, limit in PRODUCT_LIMITS.items())
            or not normalize_search(snapshot['name_fa']) or not match_fields_valid(snapshot)
            or any(normalize_search(snapshot[key]) != normalize_search(fields[key]) for key in IDENTITY_FIELDS)
            or not isinstance(review.product_identity_sha256, str)
            or not _HASH.fullmatch(review.product_identity_sha256)):
        return False
    try:
        return _digest(snapshot) == review.product_identity_sha256
    except (ValueError, TypeError, UnicodeError, OverflowError):
        return False


def classify_review(review, candidate, current_valid):
    """Return fixed status and candidate comparison, never untrusted content."""
    snapshot = review.review_snapshot
    if (not _id(candidate.pk) or not _id(review.candidate_id) or review.candidate_id != candidate.pk
            or not _id(review.reviewer_id) or not isinstance(review.decision, str)
            or review.decision not in dict(PriceCandidateReview.DECISIONS)
            or not valid_review_reason(review.reason) or review.reason != review.reason.strip()
            or not isinstance(review.candidate_payload_sha256, str)
            or not _HASH.fullmatch(review.candidate_payload_sha256)
            or not _valid_snapshot(snapshot, review.candidate_payload_sha256)
            or review.reviewer_id == snapshot['staged_by_id']):
        return 'invalid_record', 'unknown'
    if review.decision == PriceCandidateReview.ACCEPT_SUGGESTION:
        if not _valid_product(snapshot['product'], snapshot['source_fields'], review):
            return 'invalid_record', 'unknown'
    elif (snapshot['product'] is not None or review.reviewed_product_id is not None
          or review.product_identity_sha256 != ''):
        return 'invalid_record', 'unknown'

    if not current_valid or not _id(candidate.staged_by_id):
        comparison = 'unknown'
    else:
        current = {'source_name': candidate.source_name, 'source_url': candidate.source_url,
                   'source_record_id': candidate.source_record_id, 'source_fields': candidate.source_fields,
                   'amount_rial': candidate.amount_rial, 'source_rights_attested': candidate.source_rights_attested,
                   'staged_by_id': candidate.staged_by_id}
        comparison = ('same' if all(snapshot[key] == value for key, value in current.items())
                      and review.candidate_payload_sha256 == candidate.payload_sha256 else 'different')
    return 'consistent', comparison
