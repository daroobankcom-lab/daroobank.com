from .models import ProductPresentation
from .normalization import normalize_search

MAX_QUERY_LENGTH = 120
MAX_RESULTS = 30

def search_products(query):
    """Return at most 30 vetted presentation records, never drafts or blank sources."""
    normalized = normalize_search((query or '')[:MAX_QUERY_LENGTH])
    if not normalized:
        return []
    return ProductPresentation.objects.filter(
        published=True, verified_at__isnull=False, search_text__contains=normalized,
        source_url__startswith='https://',
    ).exclude(source_name='').order_by('name_fa', 'pk')[:MAX_RESULTS]
