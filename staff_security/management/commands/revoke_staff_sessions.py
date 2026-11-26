"""Bounded, development-only revocation of synthetic staff sessions.

The request-time guard in `daroobank/session_guard.py` ends a session when it is
presented while the account differs from the state the session was bound to. A
transition that no request observes leaves nothing to compare, so removing access also
needs a way to revoke sessions explicitly. This command is that mechanism: it deletes
rows from the database session store, after which a cookie a client still holds
resolves to no session and the next request is anonymous.

It is read-only unless `--apply` is given, it scans and deletes one bounded batch, and
it reports what it did as JSON so a caller cannot mistake an inspection for a
revocation. Deleting sessions is not an audit record and says nothing about why access
was removed.
"""
import json

from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

SCAN_LIMIT = 5000
BATCH_LIMIT = 500


class Command(BaseCommand):
    help = 'Inspect or delete one bounded batch of synthetic authenticated sessions.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Delete one eligible batch; default is read-only.')
        parser.add_argument('--username', help='Revoke only the sessions of this account.')
        parser.add_argument('--all', action='store_true', help='Revoke every unexpired authenticated session.')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Only synthetic development environments are supported.')
        if bool(options['username']) == bool(options['all']):
            raise CommandError('Pass exactly one of --username or --all.')
        target_pk = None
        if options['username']:
            account = get_user_model().objects.filter(username=options['username']).values('pk').first()
            if account is None:
                raise CommandError('No such account.')
            target_pk = str(account['pk'])
        scanned = 0
        matched = []
        sessions = Session.objects.filter(expire_date__gte=timezone.now()).order_by('session_key')
        for session in sessions[:SCAN_LIMIT]:
            scanned += 1
            named = session.get_decoded().get(SESSION_KEY)
            if named is None:
                continue
            if target_pk is not None and str(named) != target_pk:
                continue
            matched.append(session.session_key)
            if len(matched) >= BATCH_LIMIT:
                break
        revoked = 0
        if options['apply'] and matched:
            revoked = Session.objects.filter(session_key__in=matched).delete()[0]
        self.stdout.write(json.dumps({'all': bool(options['all']), 'applied': bool(options['apply']),
                                      'batch_limit': BATCH_LIMIT, 'matched': len(matched), 'revoked': revoked,
                                      'scan_limit': SCAN_LIMIT, 'scanned': scanned, 'username': options['username']},
                                     sort_keys=True))
