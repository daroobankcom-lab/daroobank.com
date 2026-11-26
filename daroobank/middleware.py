import re
from ipaddress import IPv6Address, ip_address

from django.conf import settings
from django.http import HttpResponseNotFound


# The current server-rendered slice has no executable inline scripts or styles.
# Do not set frame-ancestors here: development previews embed the page, while
# production framing remains governed by the separately configured X-Frame-Options.
DEVELOPMENT_CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; "
                   "img-src 'self'; font-src 'self'; connect-src 'self'; "
                   "object-src 'none'; base-uri 'none'; form-action 'self'; frame-src 'none'")


class ContentSecurityPolicyMiddleware:
    """Set a conservative baseline, without replacing an explicit view policy."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault('Content-Security-Policy', DEVELOPMENT_CSP)
        return response


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


class TrustedProxySchemeMiddleware:
    """Strip forwarded scheme unless the immediate peer and value are trusted.

    Peer addresses are supplied by the serving stack; this does not authenticate
    a proxy, firewall the application, or make a proxy sanitize incoming headers.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        meta = request.META
        if 'HTTP_X_FORWARDED_PROTO' in meta:
            remote = meta.get('REMOTE_ADDR')
            valid = False
            if isinstance(remote, str) and 1 <= len(remote) <= 45 and '%' not in remote:
                try:
                    peer = ip_address(remote)
                    if isinstance(peer, IPv6Address) and peer.ipv4_mapped is not None:
                        peer = peer.ipv4_mapped
                    valid = any(peer in network for network in settings.TRUSTED_PROXY_SCHEME_NETWORKS)
                except ValueError:
                    pass
            if not valid or meta['HTTP_X_FORWARDED_PROTO'] not in ('http', 'https'):
                meta.pop('HTTP_X_FORWARDED_PROTO', None)
        return self.get_response(request)


class HealthProbePrivacyHeadersMiddleware:
    """Non-cacheable, non-indexable probe responses, including early errors."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.path_info == '/health' or request.path_info.startswith('/health/'):
            response['Cache-Control'] = 'no-store'
            response['X-Robots-Tag'] = 'noindex, nofollow'
            response['Referrer-Policy'] = 'no-referrer'
        return response


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
    these resolved views receive the same policy. Known public path shapes
    receive the policy even when unresolved, including slashless redirects and
    oversized numeric IDs. Other unresolved paths and upstream responses remain
    outside scope.
    """

    view_names = frozenset({
        'search', 'search_api', 'presentation_detail', 'presentation_api', 'openapi_document',
    })

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = getattr(request, 'resolver_match', None)
        # CommonMiddleware may redirect before resolving the request. An
        # oversized numeric product ID can also fail the converter before a
        # resolver_match exists. Match only our known public path shapes.
        if (match is not None and match.url_name in self.view_names) or _is_public_read_path(request.path_info):
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
