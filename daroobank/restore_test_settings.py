"""Fresh synthetic PostgreSQL database for an opt-in restore drill; never serve with this."""
import sys
from copy import deepcopy
from uuid import uuid4

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

if '--keepdb' in sys.argv or '--parallel' in sys.argv or any(arg.startswith('--parallel=') for arg in sys.argv):
    raise ImproperlyConfigured('Restore drills require a fresh, non-parallel database.')

DATABASES = deepcopy(DATABASES)  # noqa: F405
DATABASES['default']['TEST'] = {'NAME': f'test_daroobank_restore_{uuid4().hex}'}
DAROOBANK_RESTORE_ISOLATED = True
