"""Dedicated throwaway DB for the opt-in browser run; never use for serving."""
import sys
from uuid import uuid4

from django.core.exceptions import ImproperlyConfigured

from .settings import *  # noqa: F403

if '--keepdb' in sys.argv or '--parallel' in sys.argv or any(arg.startswith('--parallel=') for arg in sys.argv):
    raise ImproperlyConfigured('Browser tests require a fresh, non-parallel database.')

DATABASES['default']['TEST'] = {'NAME': f'test_daroobank_browser_{uuid4().hex}'}  # noqa: F405
DAROOBANK_BROWSER_ISOLATED = True
