"""Private scan error response; caller must check access before rendering."""
from django.shortcuts import render


_RESTART_ROUTES = frozenset({'staff_catalog_quality', 'staff_source_date_inspection'})


def invalid_scan_response(request, *, restart_route):
    """Return a generic, non-reflecting error with a fixed local restart link."""
    if restart_route not in _RESTART_ROUTES:
        raise ValueError('Unsupported scan restart route')
    return render(request, 'staff/scan_input_error.html', {
        'page_title': 'ورودی بازرسی نامعتبر | داروبانک',
        'description': 'درخواست بازرسی داخلی معتبر نیست.',
        'private_staff': True, 'noindex': True, 'restart_route': restart_route,
    }, status=400)
