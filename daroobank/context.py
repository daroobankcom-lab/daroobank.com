from django.conf import settings


def staff_portal_context(request):
    return {'staff_portal_enabled': settings.STAFF_PORTAL_ENABLED}
