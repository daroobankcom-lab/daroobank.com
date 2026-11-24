"""Bounded public catalog reads; flags and source checks are not approval."""
import unicodedata
from urllib.parse import urlsplit

from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db.models import Q
from django.http import Http404
from django.utils.crypto import constant_time_compare, salted_hmac

from daroobank.signed_cursors import loads_nonfuture

from .models import PRESENTATION_SEARCH_FIELDS, ProductPresentation
from .normalization import normalize_search

MAX_QUERY_LENGTH = 120
MAX_RESULTS = 30
# Inspection is bounded independently of the number of corrupt/bypassed records.
MAX_SEARCH_CANDIDATES = 150
MAX_CURSOR_LENGTH = 512
CURSOR_MAX_AGE = 3600
CURSOR_SALT = 'catalog.search.cursor.v1'


class InvalidSearchQuery(ValueError):
    """The bounded search query contains unsupported control or surrogate characters."""


class InvalidSearchCursor(ValueError):
    """A cursor is invalid, expired, belongs to another query or is stale."""


def _cursor_digest(kind, value):
    # Keyed hashes avoid exposing query or skipped invalid names in the signed token.
    return salted_hmac(f'{CURSOR_SALT}.{kind}', value, algorithm='sha256').hexdigest()


def _encode_cursor(query, anchor):
    return signing.dumps({
        'query': _cursor_digest('query', query), 'pk': anchor.pk,
        'name': _cursor_digest('name', anchor.name_fa),
    }, salt=CURSOR_SALT)


def _decode_cursor(token, query, candidates):
    # We only issue uncompressed cursors; never decompress client input.
    if len(token) > MAX_CURSOR_LENGTH or token.startswith('.') or not query:
        raise InvalidSearchCursor
    try:
        data = loads_nonfuture(token, salt=CURSOR_SALT, max_age=CURSOR_MAX_AGE)
        if (not isinstance(data, dict) or set(data) != {'query', 'pk', 'name'}
                or type(data['pk']) is not int or not 1 <= data['pk'] <= 9_223_372_036_854_775_807
                or not isinstance(data['query'], str) or not isinstance(data['name'], str)
                or not constant_time_compare(data['query'], _cursor_digest('query', query))):
            raise InvalidSearchCursor
        anchor = candidates.filter(pk=data['pk']).only('pk', 'name_fa').first()
        if anchor is None or not constant_time_compare(data['name'], _cursor_digest('name', anchor.name_fa)):
            raise InvalidSearchCursor
        return anchor
    except (signing.BadSignature, ValueError, TypeError, KeyError) as exc:
        raise InvalidSearchCursor from exc


def public_candidates():
    return ProductPresentation.objects.filter(
        published=True, verified_at__isnull=False, source_url__startswith='https://',
    ).exclude(source_name='')


def is_public_presentation(product):
    """Reject selected malformed display data, even after bypassed validation."""
    if not product.published or not product.verified_at:
        return False
    # Do not emit control characters from corrupted direct writes in HTML or
    # JSON. Unicode format characters (including Persian ZWNJ) are intentionally
    # not prohibited by this limited check; it is not a spoofing defense.
    for field in (*PRESENTATION_SEARCH_FIELDS, 'source_name', 'source_url'):
        value = getattr(product, field)
        if not isinstance(value, str) or any(unicodedata.category(ch) in ('Cc', 'Cs') for ch in value):
            return False
    if not product.source_name.strip():
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


def search_product_page(query, cursor=''):
    """Return one bounded, forward-only page; no consistent snapshot is promised."""
    bounded = (query or '')[:MAX_QUERY_LENGTH]
    # Reject control and surrogate characters in the retained query, before
    # querying, cursor parsing or echoing it in HTML. Format characters such
    # as Persian ZWNJ remain supported by lookup normalization.
    if any(unicodedata.category(char) in ('Cc', 'Cs') for char in bounded):
        raise InvalidSearchQuery
    normalized = normalize_search(bounded)
    if not normalized:
        if cursor:
            raise InvalidSearchCursor
        return [], None
    candidates = public_candidates().filter(search_text__contains=normalized)
    if cursor:
        anchor = _decode_cursor(cursor, normalized, candidates)
        candidates = candidates.filter(Q(name_fa__gt=anchor.name_fa) | Q(name_fa=anchor.name_fa, pk__gt=anchor.pk))
    # One extra row is fetched only to know whether any subsequent candidate exists.
    # The stored projection is needed by SQL for matching, not by the public
    # serializer. Avoid transferring potentially oversized bypass-written text.
    batch = list(candidates.defer('search_text', 'irc_normalized').order_by('name_fa', 'pk')[:MAX_SEARCH_CANDIDATES + 1])
    results = []
    scanned = 0
    for product in batch[:MAX_SEARCH_CANDIDATES]:
        scanned += 1
        if is_public_presentation(product):
            # A bulk update or direct SQL can leave the stored projection stale.
            # Recheck the current fetched fields before presenting a SQL match.
            # This cannot find candidates omitted by a stale projection.
            current_text = normalize_search(' '.join(getattr(product, field) for field in PRESENTATION_SEARCH_FIELDS))
            if normalized not in current_text:
                continue
            results.append(product)
            if len(results) == MAX_RESULTS:
                break
    next_cursor = _encode_cursor(normalized, batch[scanned - 1]) if scanned and scanned < len(batch) else None
    return results, next_cursor


def search_products(query):
    """Compatibility helper for callers that only need the first page."""
    return search_product_page(query)[0]


def get_public_presentation(pk):
    if not 1 <= pk <= 9_223_372_036_854_775_807:
        raise Http404('Presentation not found')
    product = public_candidates().filter(pk=pk).defer('search_text', 'irc_normalized').first()
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
