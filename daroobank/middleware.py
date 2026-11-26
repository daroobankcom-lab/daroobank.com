import re
from ipaddress import IPv6Address, ip_address

from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponse, HttpResponseNotFound

from staff_security.read_limit import consume_read

from .session_guard import session_matches_account


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


def _is_health_probe_path(path):
    return path == '/health' or path.startswith('/health/')


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
    """Apply known-path privacy headers even before URL resolution.

    This wraps SecurityMiddleware, covering its redirects and selected early
    errors without changing the staff gate's ordering. The historical class name
    is retained; upstream proxies and unknown paths remain outside its scope.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
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

class StaffSessionGuardMiddleware:
    """End a staff session whose account state changed after it was established.

    Django's own session-auth hash covers the password field only, so deactivating an
    account or removing a permission left an unexpired session that a later
    reactivation or regrant revived (ADR 0191). This compares the authorization state
    the session was bound to against the account's current state and flushes the
    session on any difference, which makes the rest of the request anonymous: every
    staff route then answers with the 302 to the login page that an expired session
    already produces, so no route learns a new denial path.

    It runs only on staff paths, after AuthenticationMiddleware, so public reads pay
    no extra queries and no behavior change.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if _is_staff_path(request.path_info) and not session_matches_account(request):
            logout(request)
        return self.get_response(request)


class PublicReadLimitMiddleware:
    """Refuse an over-limit public read with 429 and a `Retry-After` delay.

    Opt-in and off by default; `docs/DEPLOYMENT.md` assigns abuse protection to
    the edge, and this middleware is not a substitute for it. It sits above the
    session middleware so a refused read creates no session row, and it sets the
    public privacy headers itself, because a refusal is produced before URL
    resolution and so never reaches the middleware that would set them. Staff
    paths and health probes are not limited: the staff portal has its own login
    window, and a probe that is rate limited cannot report anything. An
    unavailable limiter serves the read, because on a public path failing closed
    would turn one database problem into an outage.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (settings.PUBLIC_READ_LIMIT_ENABLED and request.method == 'GET'
                and not _is_staff_path(request.path_info)
                and not _is_health_probe_path(request.path_info)):
            outcome, retry_after = consume_read(request.META.get('REMOTE_ADDR'))
            if outcome == 'limited':
                response = HttpResponse(status=429)
                response['Retry-After'] = str(retry_after)
                _public_headers(response)
                return response
        return self.get_response(request)
