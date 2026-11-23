"""Atomic web intake receipts and row outcomes. Never fetch or publish."""
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Max, Min, Q

from catalog.comparisons import valid_candidate as valid_product
from catalog.intake import stage_products
from pricing.comparisons import valid_candidate as valid_price
from pricing.importer import stage_csv, validate_source
from .models import ImportReceipt, ImportReceiptItem

PRODUCT_VIEW = 'catalog.view_productcandidate'
PRICE_VIEW = 'pricing.view_pricecandidate'
MANIFEST_VERSION = 1
PAGE_SIZE = 25


def visible_kinds(user):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return []
    return [kind for kind, permission in [(ImportReceipt.PRODUCT, PRODUCT_VIEW), (ImportReceipt.PRICE, PRICE_VIEW)]
            if user.has_perm(permission)]


def _write_items(receipt, outcomes, counts):
    # Fail the outer transaction rather than persist a partial manifest on an internal mismatch.
    if (len(outcomes) != counts['rows'] or sum(1 for item in outcomes if item[3]) != counts['created']
            or sum(1 for item in outcomes if not item[3]) != counts['duplicates']):
        raise ValueError('Staging outcomes do not match receipt counts.')
    if receipt.kind == ImportReceipt.PRICE:
        if any(sum(1 for item in outcomes if item[4] == status) != counts[status]
               for status in ('suggested', 'ambiguous', 'unmatched')):
            raise ValueError('Staging outcomes do not match price suggestion counts.')
    elif any(item[4] is not None for item in outcomes):
        raise ValueError('Product outcome contains a price suggestion.')
    items = []
    for ordinal, (candidate_id, source_id, digest, created, match_status) in enumerate(outcomes, 1):
        fields = {'product_candidate_id': candidate_id} if receipt.kind == ImportReceipt.PRODUCT else {'price_candidate_id': candidate_id}
        items.append(ImportReceiptItem(receipt=receipt, ordinal=ordinal, source_record_id=source_id,
                                       payload_sha256=digest, was_created=created, match_status=match_status or '', **fields))
    ImportReceiptItem.objects.bulk_create(items, batch_size=200)


def stage_product_with_receipt(file, source_name, source_url, *, actor, rights_attested):
    if not actor:
        raise PermissionDenied
    outcomes = []
    with transaction.atomic():
        counts = stage_products(file, source_name, source_url, actor=actor, commit=True, rights_attested=rights_attested,
                                on_staged=lambda *item: outcomes.append(item))
        receipt = ImportReceipt.objects.create(kind=ImportReceipt.PRODUCT, source_name=source_name,
            source_url=source_url, actor=actor, manifest_version=MANIFEST_VERSION, rows=counts['rows'],
            created=counts['created'], duplicates=counts['duplicates'])
        _write_items(receipt, outcomes, counts)
    return counts, receipt


def stage_price_with_receipt(file, source_name, source_url, *, actor, rights_attested):
    if (not actor or not actor.is_authenticated or not actor.is_active or not actor.is_staff
            or not actor.has_perm(PRICE_VIEW) or not actor.has_perm('pricing.add_pricecandidate')):
        raise PermissionDenied
    source_name, source_url = validate_source(source_name, source_url)
    outcomes = []
    with transaction.atomic():
        counts = stage_csv(file, source_name, source_url, commit=True, rights_attested=rights_attested, staged_by=actor,
                           on_staged=lambda *item: outcomes.append(item))
        receipt = ImportReceipt.objects.create(kind=ImportReceipt.PRICE, source_name=source_name, source_url=source_url,
            actor=actor, manifest_version=MANIFEST_VERSION, rows=counts['rows'], created=counts['created'], duplicates=counts['duplicates'],
            suggested=counts['suggested'], ambiguous=counts['ambiguous'], unmatched=counts['unmatched'])
        _write_items(receipt, outcomes, counts)
    return counts, receipt


def manifest_structure(receipt):
    """Check manifest aggregate structure; this is not proof of authenticity."""
    if receipt.manifest_version is None:
        return 'legacy'
    if receipt.manifest_version != MANIFEST_VERSION:
        return 'invalid'
    rows = receipt.items.all()
    totals = rows.aggregate(total=Count('pk'), first=Min('ordinal'), last=Max('ordinal'),
        created=Count('pk', filter=Q(was_created=True)),
        products=Count('pk', filter=Q(product_candidate__isnull=False, price_candidate__isnull=True, match_status='')),
        prices=Count('pk', filter=Q(price_candidate__isnull=False, product_candidate__isnull=True)),
        suggested=Count('pk', filter=Q(match_status='suggested')),
        ambiguous=Count('pk', filter=Q(match_status='ambiguous')),
        unmatched=Count('pk', filter=Q(match_status='unmatched')))
    valid = (totals['total'] == receipt.rows and totals['first'] == 1 and totals['last'] == receipt.rows
             and totals['created'] == receipt.created and totals['total'] - totals['created'] == receipt.duplicates)
    if receipt.kind == ImportReceipt.PRODUCT:
        valid = valid and totals['products'] == receipt.rows
    elif receipt.kind == ImportReceipt.PRICE:
        valid = (valid and totals['prices'] == receipt.rows and totals['suggested'] == receipt.suggested
                 and totals['ambiguous'] == receipt.ambiguous and totals['unmatched'] == receipt.unmatched)
    else:
        valid = False
    return 'available' if valid else 'invalid'


def manifest_item_safe(receipt, item, *, _candidate_cache=None):
    """Compare each item; cache only pure candidate checks within one joined read."""
    if receipt.kind not in (ImportReceipt.PRODUCT, ImportReceipt.PRICE):
        return False
    candidate_field = 'product_candidate' if receipt.kind == ImportReceipt.PRODUCT else 'price_candidate'
    try:
        candidate = getattr(item, candidate_field)
        if not (candidate and candidate.pk and candidate.source_name == receipt.source_name
                and candidate.source_url == receipt.source_url and candidate.source_record_id == item.source_record_id
                and candidate.payload_sha256 == item.payload_sha256):
            return False
    except (ValueError, TypeError, AttributeError, OverflowError, ObjectDoesNotExist):
        return False
    if _candidate_cache is not None and candidate.pk in _candidate_cache:
        return _candidate_cache[candidate.pk]
    try:
        valid = bool(valid_product(candidate) if receipt.kind == ImportReceipt.PRODUCT else valid_price(candidate))
    except (ValueError, TypeError, AttributeError, OverflowError, ObjectDoesNotExist):
        valid = False
    if _candidate_cache is not None:
        _candidate_cache[candidate.pk] = valid
    return valid


def manifest_context(receipt, page_number):
    """Check structural counts and bounded row/candidate consistency, not authenticity."""
    status = manifest_structure(receipt)
    if status != 'available':
        return {'status': status}
    candidate_field = 'product_candidate' if receipt.kind == ImportReceipt.PRODUCT else 'price_candidate'
    page = Paginator(receipt.items.select_related(candidate_field).order_by('ordinal'), PAGE_SIZE).get_page(page_number)
    # All candidates came from the same joined SELECT. Never share this cache
    # across pages or requests, and always compare each item's own fields.
    candidate_cache = {}
    for item in page.object_list:
        item.safe = manifest_item_safe(receipt, item, _candidate_cache=candidate_cache)
    return {'status': 'available', 'page': page}


def related_receipts(user, candidate, kind):
    """Recent same-domain references, advisory only; never infer complete provenance."""
    if kind not in visible_kinds(user):
        raise PermissionDenied
    if kind == ImportReceipt.PRODUCT:
        filters = {'items__product_candidate_id': candidate.pk, 'items__price_candidate__isnull': True}
    else:
        filters = {'items__price_candidate_id': candidate.pk, 'items__product_candidate__isnull': True}
    rows = list(ImportReceipt.objects.filter(kind=kind, manifest_version=MANIFEST_VERSION,
        source_name=candidate.source_name, source_url=candidate.source_url,
        items__source_record_id=candidate.source_record_id, items__payload_sha256=candidate.payload_sha256,
        **filters).distinct().order_by('-pk')[:6])
    return {'items': rows[:5], 'limited': len(rows) > 5}
