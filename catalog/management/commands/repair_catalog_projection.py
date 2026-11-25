import json
from django.core.management.base import BaseCommand, CommandError
from catalog.projection_repair import ProjectionRepairError, apply_projection, preview_projection


class Command(BaseCommand):
    help = 'Preview or explicitly repair derived projections for one synthetic development presentation.'

    def add_arguments(self, parser):
        parser.add_argument('--id', type=int, required=True, dest='presentation_id')
        parser.add_argument('--commit', action='store_true', help='Apply a previously previewed repair')
        parser.add_argument('--token', default='', help='Short-lived token returned by preview')
        parser.add_argument('--confirm-synthetic', action='store_true', help='Attest this is synthetic development data')

    def handle(self, *args, **options):
        commit, token, confirmed = options['commit'], options['token'], options['confirm_synthetic']
        if (type(commit) is not bool or type(confirmed) is not bool or not isinstance(token, str)
                or commit != bool(token) or commit != confirmed):
            raise CommandError('Use --commit, --token and --confirm-synthetic together; omit all for preview.')
        try:
            if commit:
                result = apply_projection(presentation_id=options['presentation_id'], token=token, synthetic_confirmed=confirmed)
            else:
                result = preview_projection(presentation_id=options['presentation_id'])
        except ProjectionRepairError as exc:
            raise CommandError('Projection request is unavailable, invalid, unsafe or stale.') from exc
        self.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True))
