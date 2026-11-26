"""Bounded, development-only inspection of synthetic staff sessions.

The session guard in `daroobank/session_guard.py` ends a session when a request
presents it after the account changed. That leaves an operational question the guard
cannot answer on its own: which sessions are sitting in the store, whose are they, and
which of them would survive a request? A transition no request observes leaves a
dormant session, and `revoke_staff_sessions` needs a way to be aimed.

This command is read-only. It never deletes, and it never prints material that could be
used as a credential: session keys and cookies are replaced by a keyed digest, so two
lines can be told apart and correlated with a revocation run without handing the reader
a usable session. Account state is reported next to each session because the interesting
case is a session belonging to an account that is no longer active or no longer staff.
"""
import json

from django.conf import settings
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.crypto import salted_hmac

from daroobank.session_guard import SESSION_FINGERPRINT_KEY, authorization_fingerprint

SCAN_LIMIT = 5000
_ID_SALT = 'daroobank.staff.session.inventory.v1'


def session_alias(session_key):
    """Return a keyed digest of a session key, so it can be listed without being usable."""
    return salted_hmac(_ID_SALT, session_key, algorithm='sha256').hexdigest()[:32]


class Command(BaseCommand):
    help = 'Inspect one bounded batch of synthetic staff sessions; never deletes anything.'

    def add_arguments(self, parser):
        parser.add_argument('--username', help='Report only the sessions of this account.')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Only synthetic development environments are supported.')
        target_pk = None
        if options['username'] is not None:
            if not options['username']:
                raise CommandError('A username must not be empty.')
            account = get_user_model().objects.filter(username=options['username']).values('pk').first()
            if account is None:
                raise CommandError('No such account.')
            target_pk = str(account['pk'])
        accounts = {}
        digests = {}
        scanned = matched = unbound = 0
        sessions = Session.objects.filter(expire_date__gte=timezone.now()).order_by('session_key')
        for session in sessions[:SCAN_LIMIT]:
            scanned += 1
            decoded = session.get_decoded()
            named = decoded.get(SESSION_KEY)
            if named is None or not str(named).isdigit():
                continue
            named = str(named)
            if target_pk is not None and named != target_pk:
                continue
            matched += 1
            bound = SESSION_FINGERPRINT_KEY in decoded
            if not bound:
                unbound += 1
            if named not in digests:
                digests[named] = authorization_fingerprint(int(named))
            row = accounts.setdefault(named, {'account_id': named, 'sessions': []})
            row['sessions'].append({
                'alias': session_alias(session.session_key),
                'bound': bound,
                'expires_at': session.expire_date.isoformat(),
                # Would the guard end this session on its next staff request? An
                # unbound session is never trusted, and a missing account never matches.
                'guard_would_end_it': (not bound) or decoded[SESSION_FINGERPRINT_KEY] != digests[named],
            })
        for pk, row in accounts.items():
            account = get_user_model().objects.filter(pk=int(pk)).values(
                'username', 'is_active', 'is_staff', 'is_superuser').first()
            # A session can outlive its account; the row stays, marked as such.
            row['account_exists'] = account is not None
            row['username'] = account['username'] if account else None
            row['is_active'] = account['is_active'] if account else None
            row['is_staff'] = account['is_staff'] if account else None
            row['is_superuser'] = account['is_superuser'] if account else None
            row['sessions'].sort(key=lambda item: item['alias'])
            row['session_count'] = len(row['sessions'])
        report = {
            'accounts': [accounts[pk] for pk in sorted(accounts, key=int)],
            'scan_limit': SCAN_LIMIT,
            'scanned': scanned,
            'sessions_matched': matched,
            'sessions_unbound': unbound,
            'username': options['username'],
        }
        self.stdout.write(json.dumps(report, sort_keys=True))
