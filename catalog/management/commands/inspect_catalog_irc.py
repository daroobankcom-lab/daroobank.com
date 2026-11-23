import json
from django.core.management.base import BaseCommand, CommandError
from catalog.quality_irc import InvalidIRCCursor, QualityAnchorNotFound, inspect_irc


class Command(BaseCommand):
    help = 'Inspect a bounded page of indexed IRC clues without changing or verifying records.'

    def add_arguments(self, parser):
        parser.add_argument('--id', type=int, required=True, dest='anchor_id', help='Internal presentation ID')
        parser.add_argument('--cursor', default='', help='Continuation returned by the previous page')

    def handle(self, *args, **options):
        try:
            report = inspect_irc(anchor_id=options['anchor_id'], cursor=options['cursor'])
        except (QualityAnchorNotFound, InvalidIRCCursor) as exc:
            raise CommandError('Presentation or cursor is invalid or stale.') from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
