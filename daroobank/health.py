"""Opt-in minimal process and PostgreSQL probes; not production certification."""
from django.conf import settings
from django.db import DatabaseError, connections, transaction
from django.http import HttpResponse, HttpResponseNotAllowed, HttpResponseNotFound


def database_ready():
    """Check one SELECT on the default DB with a server-side statement timeout.

    Do not modify an enclosing transaction's timeout. The timeout bounds only
    execution on PostgreSQL, not connection setup or a stalled network socket.
    """
    connection = connections['default']
    try:
        if connection.vendor != 'postgresql' or connection.in_atomic_block or not connection.get_autocommit():
            return False
        with transaction.atomic(using='default'):
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL statement_timeout = '1s'")
                cursor.execute('SELECT 1')
                return cursor.fetchone() == (1,)
    except DatabaseError:
        return False


def _probe(request, *, ready):
    if not settings.HEALTH_PROBES_ENABLED:
        return HttpResponseNotFound()
    if request.method not in ('GET', 'HEAD'):
        return HttpResponseNotAllowed(['GET', 'HEAD'])
    available = not ready or database_ready()
    return HttpResponse('ok\n' if available else 'unavailable\n',
                        status=200 if available else 503, content_type='text/plain; charset=utf-8')


def live(request):
    return _probe(request, ready=False)


def ready(request):
    return _probe(request, ready=True)
