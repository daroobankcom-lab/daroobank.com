"""Bounded, read-only date clues; not evidence of source rights or a snapshot."""
from datetime import date

from django.utils import timezone

from .models import SourceClaim
from .services import FIELDS, date_label

BATCH_SIZE = 50
MAX_PK = 9_223_372_036_854_775_807
DATE_CATEGORIES = ('expired', 'future', 'within_dates', 'unknown', 'invalid')


class InvalidDateInspection(ValueError):
    """Invalid scan position, category or date."""


def inspect_dates(*, after=0, category='', today=None):
    """Classify at most 50 ID-ordered claims; filter only within that batch."""
    if (type(after) is not int or not 0 <= after <= MAX_PK
            or not isinstance(category, str) or category not in ('', *DATE_CATEGORIES)
            or (today is not None and type(today) is not date)):
        raise InvalidDateInspection
    today = today if today is not None else timezone.localdate()
    claims = list(SourceClaim.objects.filter(pk__gt=after)
                  .only('id', 'payload_sha256', *FIELDS).order_by('pk')[:BATCH_SIZE + 1])
    more = len(claims) > BATCH_SIZE
    batch = claims[:BATCH_SIZE]
    rows = []
    for claim in batch:
        status = date_label(claim, today=today)
        if not category or status == category:
            rows.append({'id': claim.pk, 'status': status})
    return {'after': after, 'category': category, 'today': today, 'limit': BATCH_SIZE,
            'scanned': len(batch), 'rows': rows,
            'next_after': batch[-1].pk if more else None}
