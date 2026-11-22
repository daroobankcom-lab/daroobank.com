from django.conf import settings
from django.http import HttpResponseNotFound


class StaffPrivacyHeadersMiddleware:
    """Prevent caching and indexing of all staff responses, including errors."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        is_staff_path = request.path_info.startswith('/staff/')
        if is_staff_path and not settings.STAFF_PORTAL_ENABLED:
            response = HttpResponseNotFound()
        else:
            response = self.get_response(request)
        if is_staff_path:
            response['Cache-Control'] = 'private, no-store, max-age=0'
            response['Pragma'] = 'no-cache'
            response['X-Robots-Tag'] = 'noindex, nofollow'
            response['Referrer-Policy'] = 'no-referrer'
        return response
