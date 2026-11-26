"""Selected PostgreSQL access clues; no production authorization assessment."""
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection

from daroobank.postgresql_access import inspect_access
from daroobank.postgresql_inspection import expected_tables


class Command(BaseCommand):
    help = 'Inspect selected PostgreSQL session and privilege clues for synthetic development data.'

    def handle(self, *args, **options):
        if not settings.DEBUG or connection.vendor != 'postgresql':
            raise CommandError('This inspection is available only for PostgreSQL development settings.')
        try:
            report = inspect_access(expected_tables())
        except DatabaseError:
            # Do not chain driver details into an operator-facing traceback.
            raise CommandError('PostgreSQL access inspection could not be completed.') from None
        self.stdout.write(json.dumps(report, sort_keys=True))
