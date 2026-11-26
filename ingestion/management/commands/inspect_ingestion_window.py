import json
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError

from ingestion.schedule import DEFAULT_END, DEFAULT_START, DEFAULT_ZONE, ScheduleError, inspect_window


class Command(BaseCommand):
    help = 'Inspect a daily ingestion window offline; never starts or authorizes work.'

    def add_arguments(self, parser):
        parser.add_argument('--start', default=DEFAULT_START, help='Local start, HH:MM')
        parser.add_argument('--end', default=DEFAULT_END, help='Local end, HH:MM')
        parser.add_argument('--timezone', default=DEFAULT_ZONE, help='IANA timezone')
        parser.add_argument('--at', help='Instant in ISO 8601 with UTC offset; defaults to now')

    def handle(self, *args, **options):
        try:
            at = datetime.fromisoformat(options['at']) if options['at'] else datetime.now(timezone.utc)
            plan = inspect_window(at=at, start=options['start'], end=options['end'], zone=options['timezone'])
        except (ScheduleError, ValueError, OverflowError):
            # Parser and timezone exceptions may contain the submitted value.
            raise CommandError('Invalid or unresolvable schedule or instant.') from None
        self.stdout.write(json.dumps(plan.as_dict(), ensure_ascii=False, sort_keys=True))
