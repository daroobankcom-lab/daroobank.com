import re

from django.conf import settings
from django.http import HttpResponseNotFound


def _is_staff_path(path):
    return path == '/staff' or path.startswith('/staff/')


def _is_public_read_path(path):
    return path in {'/search', '/search/', '/api/v1/search', '/api/v1/search/', '/api/v1/openapi.json'} or bool(
        re.fullmatch(r'/(?:api/v1/)?products/[0-9]+/?', path)
    )


def _public_headers(response):
    response['Cache-Control'] = 'no-store'
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Robots-Tag'] = 'noindex, follow'


def _staff_headers(response):
    response['Cache-Control'] = 'private, no-store, max-age=0'
    response['Pragma'] = 'no-cache'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    # Same-origin Referer is required for Django's HTTPS CSRF fallback.
    response['Referrer-Policy'] = 'same-origin'


class EarlyRedirectPrivacyHeadersMiddleware:
    """Apply known-path headers to redirects produced before URL resolution.

    In particular, this wraps SecurityMiddleware without changing its HTTPS
    redirect or the staff gate's ordering. It cannot affect upstream proxies.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code in (301, 302, 303, 307, 308):
            if _is_staff_path(request.path_info):
                _staff_headers(response)
            elif _is_public_read_path(request.path_info):
                _public_headers(response)
        return response


class PublicReadPrivacyHeadersMiddleware:
    """Apply privacy headers to resolved public reads, including CSRF/405 errors.

    Runs outside CommonMiddleware and CsrfViewMiddleware so their responses for
    these resolved views receive the same policy. Known slashless search/product
    paths receive the policy too, including CommonMiddleware's redirect. Other
    unresolved requests and responses generated upstream are outside scope.
    """

    view_names = frozenset({
        'search', 'search_api', 'presentation_detail', 'presentation_api', 'openapi_document',
    })

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = getattr(request, 'resolver_match', None)
        # CommonMiddleware resolves slash-appended routes without setting
        # request.resolver_match on the original request. Match only the known
        # slashless public reads; do not apply this to unrelated URLs.
        slashless = not request.path_info.endswith('/') and _is_public_read_path(request.path_info)
        if (match is not None and match.url_name in self.view_names) or slashless:
            _public_headers(response)
        return response


class StaffPrivacyHeadersMiddleware:
    """Prevent caching and indexing of all staff responses, including errors."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_staff_path = _is_staff_path(request.path_info)
        if is_staff_path and not settings.STAFF_PORTAL_ENABLED:
            response = HttpResponseNotFound()
        else:
            response = self.get_response(request)
        if is_staff_path:
            _staff_headers(response)
        return response
