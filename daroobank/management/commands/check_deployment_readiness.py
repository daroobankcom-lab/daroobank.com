"""Report whether this process's settings and database look deployable.

The Phase 1 gate for monitoring and response asks for production-specific readiness
checks. `health/ready/` answers one question — can this process run a SELECT — and the
non-debug startup checks in `daroobank/configuration.py` refuse to boot on a bad secret or
host shape, but nothing collected the rest of the settings a deployment has to get right,
and nothing said so in a form an operator or a release gate can read.

This command reads settings and the migration table, writes nothing, and prints one JSON
report:

* `required` — checks that must pass before this process is deployed. Each carries an id,
  a boolean and a detail line that never includes the secret's value.
* `review` — conditions that are not failures of this configuration but that a deployment
  still has to decide about, each with the reason it is listed.
* `ready` — true only when every required check passed. `--strict` additionally requires
  an empty `review` list.

Exit status is 0 when ready, 1 when not. The command runs in debug and non-debug alike;
in a development environment it is expected to report "not ready" and to say why.

This is a settings and database shape check for one process. It is not monitoring,
alerting, MFA, TLS issuance, backup verification, network isolation, a penetration test
or an independent security assessment, and a zero exit status is not a deployment
authorization.
"""
import json

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.migrations.loader import MigrationLoader

from daroobank.configuration import require_nondebug_hosts, require_nondebug_secret
from daroobank.health import database_ready

SCOPE = ('settings and database shape for this process only; not monitoring, alerting, MFA, TLS issuance, '
         'backups, network isolation or an independent security assessment')
DEVELOPMENT_HOSTS = frozenset({'localhost', '127.0.0.1', 'testserver', '.e2b.app', '[::1]'})
CLICKJACKING_MIDDLEWARE = 'django.middleware.clickjacking.XFrameOptionsMiddleware'


def debug_disabled():
    if settings.DEBUG:
        return False, 'DEBUG is on; detailed errors, the staff portal and insecure cookies follow from it'
    return True, 'DEBUG is off'


def staff_portal_disabled():
    if getattr(settings, 'STAFF_PORTAL_ENABLED', False):
        return False, ('the staff portal is enabled; it is restricted to development until MFA, throttling '
                       'and audit exist')
    return True, 'the staff portal is disabled and every /staff/ request is answered 404'


def secret_key_shape():
    try:
        require_nondebug_secret(settings.SECRET_KEY)
    except ImproperlyConfigured:
        return False, 'DAROOBANK_SECRET_KEY does not have a supported non-debug shape'
    return True, 'the secret has a supported non-debug shape; its entropy and secrecy are not measured here'


def allowed_hosts_explicit():
    try:
        hosts = require_nondebug_hosts(','.join(settings.ALLOWED_HOSTS))
    except ImproperlyConfigured:
        return False, 'ALLOWED_HOSTS is empty, holds a wildcard or holds an invalid host pattern'
    return True, f'{len(hosts)} explicit host patterns'


def cookies_secure():
    insecure = [name for name in ('SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE') if not getattr(settings, name, False)]
    if insecure:
        return False, 'sent over plain HTTP: ' + ', '.join(sorted(insecure))
    return True, 'the session and CSRF cookies are both marked Secure'


def session_flags():
    expected = {'SESSION_COOKIE_HTTPONLY': True, 'SESSION_COOKIE_SAMESITE': 'Lax',
                'SESSION_COOKIE_AGE': 3600, 'SESSION_EXPIRE_AT_BROWSER_CLOSE': True}
    wrong = sorted(name for name, value in expected.items() if getattr(settings, name, None) != value)
    if wrong:
        return False, 'unexpected session settings: ' + ', '.join(wrong)
    return True, 'httponly, SameSite=Lax, one hour and browser-close expiry, as ADR 0208 pins'


def ssl_redirect_enabled():
    if not getattr(settings, 'SECURE_SSL_REDIRECT', False):
        return False, 'SECURE_SSL_REDIRECT is off, so plain HTTP requests are served'
    return True, 'plain HTTP requests are redirected'


def migrations_applied():
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    unapplied = sorted(set(loader.disk_migrations) - set(loader.applied_migrations))
    if unapplied:
        listed = ', '.join(f'{app}.{name}' for app, name in unapplied[:5])
        return False, f'{len(unapplied)} migrations are not applied: {listed}'
    return True, f'{len(loader.applied_migrations)} migrations applied, none pending'


def migration_history_consistent():
    loader = MigrationLoader(connection, ignore_no_migrations=True)
    orphaned = sorted(set(loader.applied_migrations) - set(loader.disk_migrations))
    if orphaned:
        listed = ', '.join(f'{app}.{name}' for app, name in orphaned[:5])
        return False, f'{len(orphaned)} applied migrations have no file in this release: {listed}'
    return True, 'every applied migration has a file in this release'


def database_reachable():
    if database_ready():
        return True, 'one SELECT answered inside the one-second statement timeout'
    return False, ('the readiness SELECT did not answer; this check also reports false inside an open '
                   'transaction, so it must run outside one')


REQUIRED = (
    ('debug_disabled', debug_disabled),
    ('staff_portal_disabled', staff_portal_disabled),
    ('secret_key_shape', secret_key_shape),
    ('allowed_hosts_explicit', allowed_hosts_explicit),
    ('cookies_secure', cookies_secure),
    ('session_flags', session_flags),
    ('ssl_redirect_enabled', ssl_redirect_enabled),
    ('migrations_applied', migrations_applied),
    ('migration_history_consistent', migration_history_consistent),
    ('database_reachable', database_reachable),
)


def review_items():
    """Conditions a deployment must decide about; none of them is a broken setting."""
    items = []
    if settings.SECURE_HSTS_SECONDS == 0:
        items.append({'id': 'hsts_disabled',
                      'reason': 'HSTS is off; enabling it needs a reviewed TLS issuance and rollback policy'})
    if getattr(settings, 'SECURE_SSL_REDIRECT', False) and settings.SECURE_PROXY_SSL_HEADER is None:
        items.append({'id': 'proxy_scheme_untrusted',
                      'reason': 'HTTPS redirection is on with no trusted proxy header, which behind a TLS-terminating '
                                'proxy redirects every request forever; direct TLS needs no header'})
    development = sorted(set(settings.ALLOWED_HOSTS) & DEVELOPMENT_HOSTS)
    if development:
        items.append({'id': 'development_hosts',
                      'reason': 'ALLOWED_HOSTS includes development hosts: ' + ', '.join(development)})
    if getattr(settings, 'HEALTH_PROBES_ENABLED', False):
        items.append({'id': 'health_probes_reachable',
                      'reason': 'the health probes answer; restricting them is a proxy or network decision'})
    if getattr(settings, 'STAFF_LOGIN_THROTTLE_ENABLED', False):
        items.append({'id': 'synthetic_login_throttle',
                      'reason': 'the staff login limiter is a synthetic development control, not a production '
                                'abuse control'})
    if CLICKJACKING_MIDDLEWARE not in settings.MIDDLEWARE:
        items.append({'id': 'clickjacking_middleware_absent',
                      'reason': 'XFrameOptionsMiddleware is not installed, so framing is limited only by the '
                                'development CSP'})
    return items


def readiness_report():
    """Build the report; separate from `handle` so a test can call it without a command."""
    required = []
    for check_id, check in REQUIRED:
        passed, detail = check()
        required.append({'id': check_id, 'passed': bool(passed), 'detail': detail})
    review = review_items()
    return {
        'failed': [item['id'] for item in required if not item['passed']],
        'ready': all(item['passed'] for item in required),
        'required': required,
        'review': review,
        'scope': SCOPE,
    }


class Command(BaseCommand):
    help = 'Report whether this process looks deployable (read-only; not a certification).'

    def add_arguments(self, parser):
        parser.add_argument('--strict', action='store_true',
                            help='Also fail when any review item is present.')

    def handle(self, *args, **options):
        report = readiness_report()
        self.stdout.write(json.dumps(report, sort_keys=True))
        if not report['ready'] or (options['strict'] and report['review']):
            raise SystemExit(1)
