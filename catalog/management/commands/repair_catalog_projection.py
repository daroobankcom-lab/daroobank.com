import json
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from catalog.projection_repair import MAX_TOKEN_LENGTH, ProjectionRepairError, apply_projection, preview_projection


def _read_token_from_stdin():
    """Read a bounded single line from a non-terminal stream, without echoing it."""
    try:
        if sys.stdin.isatty():
            raise CommandError('Projection token input is unavailable or invalid.')
        # Allow room for CRLF and one extra character to detect oversized data.
        token = sys.stdin.read(MAX_TOKEN_LENGTH + 3)
    except (AttributeError, OSError, UnicodeError, ValueError):
        raise CommandError('Projection token input is unavailable or invalid.') from None
    if not isinstance(token, str):
        raise CommandError('Projection token input is unavailable or invalid.')
    if token.endswith('\r\n'):
        token = token[:-2]
    elif token.endswith('\n'):
        token = token[:-1]
    if not token or len(token) > MAX_TOKEN_LENGTH or '\r' in token or '\n' in token:
        raise CommandError('Projection token input is unavailable or invalid.')
    return token


class Command(BaseCommand):
    help = 'Preview or explicitly repair derived projections for one synthetic development presentation.'

    def add_arguments(self, parser):
        parser.add_argument('--id', type=int, required=True, dest='presentation_id')
        parser.add_argument('--commit', action='store_true', help='Apply a previously previewed repair')
        parser.add_argument('--token', default='', help='Short-lived token returned by preview (visible in process arguments)')
        parser.add_argument('--token-stdin', action='store_true', help='Read one token from a non-terminal stdin stream')
        parser.add_argument('--confirm-synthetic', action='store_true', help='Attest this is synthetic development data')

    def handle(self, *args, **options):
        commit, token, confirmed = options['commit'], options['token'], options['confirm_synthetic']
        token_stdin = options['token_stdin']
        if (type(commit) is not bool or type(confirmed) is not bool or type(token_stdin) is not bool
                or not isinstance(token, str) or commit != confirmed
                or (token_stdin and (not commit or bool(token)))
                or (not token_stdin and commit != bool(token))):
            raise CommandError('Use --commit, one token source and --confirm-synthetic together; omit all for preview.')
        if token_stdin:
            if not settings.DEBUG:
                raise CommandError('Projection request is unavailable, invalid, unsafe or stale.')
            token = _read_token_from_stdin()
        try:
            if commit:
                result = apply_projection(presentation_id=options['presentation_id'], token=token, synthetic_confirmed=confirmed)
            else:
                result = preview_projection(presentation_id=options['presentation_id'])
        except ProjectionRepairError:
            # Token or database errors can contain private values in tracebacks.
            raise CommandError('Projection request is unavailable, invalid, unsafe or stale.') from None
        self.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True))
