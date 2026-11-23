"""Dedicated throwaway DB for the opt-in browser run; never use for serving."""
from copy import deepcopy
from uuid import uuid4

from .settings import *  # noqa: F403

TEST_RUNNER = 'daroobank.isolated_test_runner.IsolatedTestRunner'
DATABASES = deepcopy(DATABASES)  # noqa: F405
DATABASES['default']['TEST'] = {'NAME': f'test_daroobank_browser_{uuid4().hex}'}  # noqa: F405
DAROOBANK_BROWSER_ISOLATED = True
