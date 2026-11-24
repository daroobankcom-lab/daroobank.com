"""Serve only the two fixed, repository-provided synthetic intake examples."""
from django.conf import settings
from django.http import HttpResponse

SAMPLE_FILES = {
    'product': 'product_candidates.synthetic.csv',
    'price': 'price_candidates.synthetic.csv',
}


def synthetic_sample_response(kind):
    # This is a fixed mapping, not a user-supplied filename or general file server.
    filename = SAMPLE_FILES[kind]
    content = (settings.BASE_DIR / 'examples' / filename).read_bytes()
    response = HttpResponse(content, content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
