"""Bounded, development-only maintenance of synthetic login window state."""
import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.db.models import Subquery
from django.db.models.functions import Now

from staff_security.models import StaffLoginWindow

BATCH_LIMIT = 500
RETENTION = timedelta(hours=24)


class Command(BaseCommand):
    help = 'Inspect or delete one bounded batch of old synthetic login windows.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Delete one eligible batch; default is read-only.')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Only synthetic development environments are supported.')
        try:
            if connection.vendor != 'postgresql' or connection.in_atomic_block or not connection.get_autocommit():
                raise CommandError('Synthetic login-window maintenance is unavailable.')
            # Local timeouts must not escape to a caller's transaction or leave
            # a delete lock held after this command returns.
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '1s'")
                    cursor.execute("SET LOCAL statement_timeout = '2s'")
                stale = StaffLoginWindow.objects.filter(started_at__lt=Now() - RETENTION)
                ordered = stale.order_by('started_at', 'client_key').values('client_key')
                if options['apply']:
                    # The outer age predicate is rechecked after any concurrent
                    # row-lock wait, so a freshly reset window is not deleted.
                    deleted, _ = stale.filter(client_key__in=Subquery(ordered[:BATCH_LIMIT])).delete()
                    result = {'mode': 'delete', 'deleted': deleted, 'limit': BATCH_LIMIT}
                else:
                    count = ordered[:BATCH_LIMIT + 1].count()
                    result = {'mode': 'dry_run', 'eligible': min(count, BATCH_LIMIT),
                              'more': count > BATCH_LIMIT, 'limit': BATCH_LIMIT}
        except DatabaseError:
            # Driver errors can contain queries or sensitive environment details.
            raise CommandError('Synthetic login-window maintenance is unavailable.') from None
        self.stdout.write(json.dumps(result, sort_keys=True))
