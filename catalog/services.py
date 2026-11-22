"""Bounded public catalog reads; flags and source checks are not approval."""
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.http import Http404

from .models import ProductPresentation
from .normalization import normalize_search

MAX_QUERY_LENGTH = 120
MAX_RESULTS = 30
# Inspection is bounded independently of the number of corrupt/bypassed records.
MAX_SEARCH_CANDIDATES = 150


def public_candidates():
    return ProductPresentation.objects.filter(
        published=True, verified_at__isnull=False, source_url__startswith='https://',
    ).exclude(source_name='')


def is_public_presentation(product):
    """Fail closed on malformed source metadata, even after bypassed model validation."""
    if not product.published or not product.verified_at or not product.source_name.strip():
        return False
    if not product.source_url or product.source_url != product.source_url.strip():
        return False
    try:
        URLValidator(schemes=['https'])(product.source_url)
        parsed = urlsplit(product.source_url)
        if parsed.username is not None or parsed.password is not None:
            return False
    except (ValidationError, ValueError):
        return False
    return all(getattr(product, field).strip() for field in (
        'name_fa', 'manufacturer', 'strength', 'dosage_form', 'package_description',
    ))


def search_products(query):
    """Return up to 30 eligible records after examining at most 150 candidates."""
    normalized = normalize_search((query or '')[:MAX_QUERY_LENGTH])
    if not normalized:
        return []
    candidates = public_candidates().filter(search_text__contains=normalized).order_by('name_fa', 'pk')[:MAX_SEARCH_CANDIDATES]
    results = []
    for product in candidates:
        if is_public_presentation(product):
            results.append(product)
            if len(results) == MAX_RESULTS:
                break
    return results


def get_public_presentation(pk):
    if not 1 <= pk <= 9_223_372_036_854_775_807:
        raise Http404('Presentation not found')
    product = public_candidates().filter(pk=pk).first()
    if product is None or not is_public_presentation(product):
        raise Http404('Presentation not found')
    return product


def serialize_presentation(product):
    return {
        'id': product.pk, 'name_fa': product.name_fa, 'name_en': product.name_en,
        'manufacturer': product.manufacturer, 'strength': product.strength,
        'dosage_form': product.dosage_form, 'package_description': product.package_description,
        'irc': product.irc or None, 'source': {'name': product.source_name, 'url': product.source_url,
                                               'verified_at': product.verified_at.isoformat()},
    }
