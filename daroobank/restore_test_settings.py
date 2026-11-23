"""Fresh synthetic PostgreSQL database for an opt-in restore drill; never serve with this."""
from copy import deepcopy
from uuid import uuid4

from .settings import *  # noqa: F403

TEST_RUNNER = 'daroobank.isolated_test_runner.IsolatedTestRunner'
DATABASES = deepcopy(DATABASES)  # noqa: F405
DATABASES['default']['TEST'] = {'NAME': f'test_daroobank_restore_{uuid4().hex}'}
DAROOBANK_RESTORE_ISOLATED = True
