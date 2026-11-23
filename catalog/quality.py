"""Bounded diagnostic inspection; not verification, repair or an audit."""
import unicodedata
from collections import Counter

from django.db.models import Exists, OuterRef

from daroobank.validation import valid_private_source_url
from .models import PRESENTATION_SEARCH_FIELDS, ProductPresentation
from .normalization import normalize_search
from .services import is_public_presentation, public_candidates

BATCH_SIZE = 50
MAX_PK = 9_223_372_036_854_775_807
SEARCH_FIELDS = PRESENTATION_SEARCH_FIELDS
TEXT_FIELDS = SEARCH_FIELDS + ('source_name', 'source_url', 'search_text', 'irc_normalized')
ISSUE_LABELS = {
    'invalid_text': 'متن ناسازگار یا دارای نویسه کنترلی',
    'search_projection': 'شاخص جست‌وجو با داده فعلی همخوان نیست',
    'irc_projection': 'شاخص IRC با داده فعلی همخوان نیست',
    'weak_source_url': 'نشانی منبع با سیاست سخت‌گیرانه داخلی همخوان نیست',
    'duplicate_irc_in_batch': 'IRC در همین بخش تکرار شده است',
    'published_but_filtered': 'پرچم انتشار فعال است ولی فیلتر نمایش عمومی رد می‌کند',
}


class QualityError(ValueError):
    pass


def inspect_batch(*, after=0):
    """Inspect up to 50 rows, advancing by ID; no completeness or snapshot promise."""
    if type(after) is not int or not 0 <= after <= MAX_PK:
        raise QualityError('شناسه شروع نامعتبر است.')
    # Use the exact SQL prefilter used by public detail/search; the later
    # predicate is shared too.
    prefilter = public_candidates().filter(pk=OuterRef('pk'))
    rows = list(ProductPresentation.objects.filter(pk__gt=after).annotate(
        _passes_public_prefilter=Exists(prefilter),
    ).order_by('pk')[:BATCH_SIZE + 1])
    more = len(rows) > BATCH_SIZE
    rows = rows[:BATCH_SIZE]
    results = []
    ircs = []
    for product in rows:
        problems = []
        safe = all(isinstance(getattr(product, field), str) and not any(
            unicodedata.category(char) in ('Cc', 'Cs') for char in getattr(product, field)
        ) for field in TEXT_FIELDS)
        eligible = None
        irc = None
        if not safe:
            problems.append('invalid_text')
        else:
            expected_search = normalize_search(' '.join(getattr(product, field) for field in SEARCH_FIELDS))
            expected_irc = normalize_search(product.irc)
            if product.search_text != expected_search:
                problems.append('search_projection')
            if product.irc_normalized != expected_irc:
                problems.append('irc_projection')
            elif expected_irc:
                irc = expected_irc
            if not valid_private_source_url(product.source_url):
                problems.append('weak_source_url')
            eligible = bool(product._passes_public_prefilter and is_public_presentation(product))
            if product.published and not eligible:
                problems.append('published_but_filtered')
        ircs.append(irc)
        results.append({'id': product.pk, 'published': product.published,
                        'public_filter': 'unknown' if eligible is None else 'passes' if eligible else 'blocked',
                        'issues': problems})
    counts = Counter(irc for irc in ircs if irc is not None)
    for row, irc in zip(results, ircs):
        if irc is not None and counts[irc] > 1:
            row['issues'].append('duplicate_irc_in_batch')
    return {
        'after': after, 'limit': BATCH_SIZE, 'scanned': len(results),
        'next_after': results[-1]['id'] if more else None,
        'issue_rows': sum(bool(row['issues']) for row in results), 'rows': results,
    }
