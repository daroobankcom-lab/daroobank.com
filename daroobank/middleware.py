import re

from django.conf import settings
from django.http import HttpResponseNotFound


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
        slashless = request.path_info in {'/search', '/api/v1/search'} or bool(
            re.fullmatch(r'/(?:api/v1/)?products/[0-9]+', request.path_info)
        )
        if (match is not None and match.url_name in self.view_names) or slashless:
            response['Cache-Control'] = 'no-store'
            response['Referrer-Policy'] = 'no-referrer'
            response['X-Robots-Tag'] = 'noindex, follow'
        return response


class StaffPrivacyHeadersMiddleware:
    """Prevent caching and indexing of all staff responses, including errors."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_staff_path = request.path_info == '/staff' or request.path_info.startswith('/staff/')
        if is_staff_path and not settings.STAFF_PORTAL_ENABLED:
            response = HttpResponseNotFound()
        else:
            response = self.get_response(request)
        if is_staff_path:
            response['Cache-Control'] = 'private, no-store, max-age=0'
            response['Pragma'] = 'no-cache'
            response['X-Robots-Tag'] = 'noindex, nofollow'
            # Preserve same-origin form Origin/Referer for Django CSRF validation,
            # while withholding staff URLs from other origins.
            response['Referrer-Policy'] = 'same-origin'
        return response
