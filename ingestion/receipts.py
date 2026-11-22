"""Atomic web intake summaries. No file storage, source access, or publication."""
from django.core.exceptions import PermissionDenied
from django.db import transaction

from catalog.intake import stage_products
from pricing.importer import stage_csv, validate_source
from .models import ImportReceipt

PRODUCT_VIEW = 'catalog.view_productcandidate'
PRICE_VIEW = 'pricing.view_pricecandidate'


def visible_kinds(user):
    if not user.is_authenticated or not user.is_active or not user.is_staff:
        return []
    return [kind for kind, permission in [(ImportReceipt.PRODUCT, PRODUCT_VIEW), (ImportReceipt.PRICE, PRICE_VIEW)]
            if user.has_perm(permission)]


def stage_product_with_receipt(file, source_name, source_url, *, actor, rights_attested):
    if not actor:
        raise PermissionDenied
    with transaction.atomic():
        counts = stage_products(file, source_name, source_url, actor=actor, commit=True, rights_attested=rights_attested)
        receipt = ImportReceipt.objects.create(kind=ImportReceipt.PRODUCT, source_name=source_name,
            source_url=source_url, actor=actor, rows=counts['rows'], created=counts['created'], duplicates=counts['duplicates'])
    return counts, receipt


def stage_price_with_receipt(file, source_name, source_url, *, actor, rights_attested):
    if (not actor or not actor.is_authenticated or not actor.is_active or not actor.is_staff
            or not actor.has_perm(PRICE_VIEW) or not actor.has_perm('pricing.add_pricecandidate')):
        raise PermissionDenied
    source_name, source_url = validate_source(source_name, source_url)
    with transaction.atomic():
        counts = stage_csv(file, source_name, source_url, commit=True, rights_attested=rights_attested, staged_by=actor)
        receipt = ImportReceipt.objects.create(kind=ImportReceipt.PRICE, source_name=source_name, source_url=source_url,
            actor=actor, rows=counts['rows'], created=counts['created'], duplicates=counts['duplicates'],
            suggested=counts['suggested'], ambiguous=counts['ambiguous'], unmatched=counts['unmatched'])
    return counts, receipt
