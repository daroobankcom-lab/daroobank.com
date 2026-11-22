import json
from django.core.management.base import BaseCommand, CommandError
from catalog.quality import QualityError, inspect_batch


class Command(BaseCommand):
    help = 'Inspect one bounded catalog batch, without changing, verifying or publishing data.'

    def add_arguments(self, parser):
        parser.add_argument('--after', type=int, default=0, help='Inspect IDs greater than this value (default 0)')

    def handle(self, *args, **options):
        try:
            result = inspect_batch(after=options['after'])
        except QualityError as exc:
            raise CommandError('Invalid starting ID.') from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
