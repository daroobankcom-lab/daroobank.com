"""Test runner guard for the optional disposable PostgreSQL exercises."""
from django.core.exceptions import ImproperlyConfigured
from django.test.runner import DiscoverRunner


class IsolatedTestRunner(DiscoverRunner):
    """Reject parsed reuse/parallel options, including argparse abbreviations."""

    def __init__(self, *args, keepdb=False, parallel=0, **kwargs):
        if keepdb or parallel:
            raise ImproperlyConfigured('Isolated exercises require a fresh, non-parallel database.')
        super().__init__(*args, keepdb=keepdb, parallel=parallel, **kwargs)
