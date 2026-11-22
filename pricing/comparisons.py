"""Bounded, conditional arithmetic on staged source assertions, never price approval."""
from catalog.normalization import normalize_search

from .importer import IDENTITY_FIELDS, match_fields_valid
from .models import PriceCandidate
from .reviews import ReviewConflict, ensure_candidate_integrity

MAX_REVISIONS = 10
FIELD_LABELS = {
    'irc': 'IRC', 'manufacturer': 'سازنده', 'strength': 'مقدار یا غلظت',
    'dosage_form': 'شکل دارویی', 'package_description': 'بسته‌بندی',
}


def valid_candidate(candidate):
    try:
        ensure_candidate_integrity(candidate)
        return match_fields_valid(candidate.source_fields)
    except ReviewConflict:
        return False


def price_revision_context(candidate):
    context = {'available': False, 'revisions': [], 'limited': False}
    if not valid_candidate(candidate):
        return context
    context['available'] = True
    revisions = list(PriceCandidate.objects.filter(source_url=candidate.source_url,
                     source_record_id=candidate.source_record_id).exclude(pk=candidate.pk)
                     .order_by('-pk')[:MAX_REVISIONS + 1])
    context['limited'] = len(revisions) > MAX_REVISIONS
    for other in revisions[:MAX_REVISIONS]:
        item = {'candidate': other, 'valid': valid_candidate(other), 'comparable': False,
                'differences': [], 'delta_rial': None}
        if item['valid']:
            if candidate.source_name != other.source_name:
                item['differences'].append('نام منبع')
            for field in IDENTITY_FIELDS:
                if normalize_search(candidate.source_fields[field]) != normalize_search(other.source_fields[field]):
                    item['differences'].append(FIELD_LABELS[field])
            if candidate.price_category != other.price_category:
                item['differences'].append('دسته قیمت')
            if candidate.unit != other.unit:
                item['differences'].append('واحد قیمت')
            if not item['differences']:
                item['comparable'] = True
                # Explicitly current record minus this other revision, in whole Rials.
                item['delta_rial'] = candidate.amount_rial - other.amount_rial
        context['revisions'].append(item)
    return context
