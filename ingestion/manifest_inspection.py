"""Private bounded manifest consistency inspection, never provenance verification."""
from django.core.exceptions import PermissionDenied

from .models import ImportReceipt
from .receipts import manifest_item_safe, manifest_structure, visible_kinds

BATCH_SIZE = 50
MAX_ORDINAL = 5000
MAX_PK = 9_223_372_036_854_775_807
CATEGORIES = ('consistent', 'inconsistent')


class ReceiptNotFound(ValueError):
    pass


class InvalidManifestInspection(ValueError):
    pass


def inspect_manifest(*, actor, receipt_id, after=0, category=''):
    """Scan at most 50 outcomes plus one lookahead, returning no source fields."""
    kinds = visible_kinds(actor) if actor is not None else []
    if not kinds:
        raise PermissionDenied
    if type(receipt_id) is not int or not 1 <= receipt_id <= MAX_PK:
        raise ReceiptNotFound
    receipt = ImportReceipt.objects.filter(pk=receipt_id, kind__in=kinds).first()
    if receipt is None:
        raise ReceiptNotFound
    if (type(after) is not int or not 0 <= after <= MAX_ORDINAL
            or not isinstance(category, str) or category not in ('', *CATEGORIES)):
        raise InvalidManifestInspection
    status = manifest_structure(receipt)
    report = {'receipt_id': receipt.pk, 'status': status, 'after': after, 'category': category,
              'scanned': 0, 'rows': [], 'next_after': None}
    if status != 'available':
        return report
    field = 'product_candidate' if receipt.kind == ImportReceipt.PRODUCT else 'price_candidate'
    batch = list(receipt.items.select_related(field).filter(ordinal__gt=after).order_by('ordinal')[:BATCH_SIZE + 1])
    scanned = batch[:BATCH_SIZE]
    rows = []
    for item in scanned:
        item_status = 'consistent' if manifest_item_safe(receipt, item) else 'inconsistent'
        if not category or category == item_status:
            rows.append({'ordinal': item.ordinal, 'status': item_status})
    report.update(scanned=len(scanned), rows=rows,
                  next_after=scanned[-1].ordinal if len(batch) > BATCH_SIZE else None)
    return report
