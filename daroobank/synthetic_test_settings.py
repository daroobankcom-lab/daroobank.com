"""Fresh, randomly named synthetic PostgreSQL test DB; never use for serving."""
from copy import deepcopy
from uuid import uuid4

from .settings import *  # noqa: F403

TEST_RUNNER = 'daroobank.isolated_test_runner.IsolatedTestRunner'
DATABASES = deepcopy(DATABASES)  # noqa: F405
DATABASES['default']['ENGINE'] = 'daroobank.isolated_postgresql'
DATABASES['default']['TEST'] = {'NAME': f'test_daroobank_synthetic_{uuid4().hex}'}
