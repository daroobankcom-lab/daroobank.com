"""Local synthetic-data catalog clues, not a database integrity certification."""
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection

from daroobank.postgresql_inspection import (expected_auto_fields, expected_check_constraints, expected_columns, expected_field_indexes,
                                             expected_foreign_keys, expected_named_indexes, expected_tables,
                                             expected_unique_keys, inspect_schema, unsupported_unique_constraints)


class Command(BaseCommand):
    help = 'Inspect selected PostgreSQL catalog states for synthetic development data (read-only).'

    def handle(self, *args, **options):
        if not settings.DEBUG or connection.vendor != 'postgresql':
            raise CommandError('This inspection is available only for PostgreSQL development settings.')
        try:
            report = inspect_schema(expected_tables(), expected_foreign_keys(), expected_unique_keys(),
                                    expected_check_constraints(), expected_columns(), expected_field_indexes(),
                                    expected_named_indexes(), unsupported_unique_constraints(), expected_auto_fields())
        except DatabaseError as exc:
            raise CommandError('PostgreSQL catalog inspection could not be completed.') from exc
        self.stdout.write(json.dumps(report, sort_keys=True))
        if report['status'] != 'no_selected_issues':
            raise CommandError('Selected PostgreSQL catalog issues require investigation.')
