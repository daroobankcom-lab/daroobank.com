"""Bounded, advisory-only comparisons; never assert identity or change records."""
from daroobank.candidate_content_bounds import bounded_candidates, materialize_candidate

from .intake import IntakeError, fingerprint, valid_fields, valid_source
from .models import ProductCandidate
from .normalization import normalize_search
from .services import is_public_presentation, public_candidates

MAX_COMPARISONS = 10
FIELD_LABELS = {
    'name_fa': 'نام فارسی', 'name_en': 'نام انگلیسی', 'manufacturer': 'سازنده',
    'strength': 'مقدار یا غلظت', 'dosage_form': 'شکل دارویی',
    'package_description': 'بسته‌بندی', 'irc': 'IRC',
}
IDENTITY_FIELDS = ('name_fa', 'manufacturer', 'strength', 'dosage_form', 'package_description')


def valid_candidate(candidate):
    try:
        valid_source(candidate.source_name, candidate.source_url)
        valid_fields(candidate.source_fields)
        return (candidate.source_record_id == candidate.source_fields['source_record_id']
                and candidate.irc_normalized == normalize_search(candidate.source_fields['irc'])
                and candidate.payload_sha256 == fingerprint(candidate.source_name, candidate.source_url, candidate.source_fields))
    except IntakeError:
        return False


def differences(left, right, keys):
    """Compare original strings; normalized equality does not establish equivalence."""
    changes = []
    for key in keys:
        a, b = left[key], right[key]
        if a != b:
            changes.append({'label': FIELD_LABELS[key], 'current': a, 'other': b,
                            'normalized_equal': normalize_search(a) == normalize_search(b)})
    return changes


def product_comparison_context(candidate):
    context = {'available': False, 'has_irc': False, 'revisions': [], 'candidate_matches': [],
               'public_matches': [], 'revisions_limited': False, 'candidate_matches_limited': False,
               'public_matches_limited': False, 'candidate_skipped': 0, 'candidate_oversized': 0, 'public_skipped': 0}
    if not valid_candidate(candidate):
        return context
    context['available'] = True
    fields = candidate.source_fields
    revisions = list(bounded_candidates(ProductCandidate.objects.filter(source_url=candidate.source_url,
                     source_record_id=candidate.source_record_id).exclude(pk=candidate.pk).order_by('-pk'))[:MAX_COMPARISONS + 1])
    context['revisions_limited'] = len(revisions) > MAX_COMPARISONS
    for other in revisions[:MAX_COMPARISONS]:
        materialize_candidate(other)
        valid = not other.content_oversized and valid_candidate(other)
        context['revisions'].append({'candidate': other, 'valid': valid,
            'status': 'oversized' if other.content_oversized else 'valid' if valid else 'invalid',
            'source_name_changed': valid and candidate.source_name != other.source_name,
            'changes': differences(fields, other.source_fields, tuple(FIELD_LABELS)) if valid else []})
    if not candidate.irc_normalized:
        return context
    context['has_irc'] = True
    others = list(bounded_candidates(ProductCandidate.objects.filter(irc_normalized=candidate.irc_normalized)
                  .exclude(pk=candidate.pk).order_by('-pk'))[:MAX_COMPARISONS + 1])
    context['candidate_matches_limited'] = len(others) > MAX_COMPARISONS
    for other in others[:MAX_COMPARISONS]:
        materialize_candidate(other)
        if other.content_oversized:
            context['candidate_oversized'] += 1
        elif valid_candidate(other) and normalize_search(other.source_fields['irc']) == candidate.irc_normalized:
            context['candidate_matches'].append({'candidate': other,
                'changes': differences(fields, other.source_fields, IDENTITY_FIELDS)})
        else:
            context['candidate_skipped'] += 1
    products = list(public_candidates().filter(irc_normalized=candidate.irc_normalized)
                    .order_by('pk')[:MAX_COMPARISONS + 1])
    context['public_matches_limited'] = len(products) > MAX_COMPARISONS
    for product in products[:MAX_COMPARISONS]:
        if is_public_presentation(product) and normalize_search(product.irc) == candidate.irc_normalized:
            product_fields = {key: getattr(product, key) for key in IDENTITY_FIELDS}
            context['public_matches'].append({'product': product,
                'changes': differences(fields, product_fields, IDENTITY_FIELDS)})
        else:
            context['public_skipped'] += 1
    return context
