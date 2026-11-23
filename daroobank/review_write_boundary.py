"""Translate selected PostgreSQL review-writer conflicts after rollback."""
from contextlib import contextmanager

from django.db import DatabaseError, transaction


@contextmanager
def review_write_boundary(conflict_type):
    """Do not retry; failures at a surrounding transaction's commit are outside scope."""
    try:
        with transaction.atomic():
            yield
    except DatabaseError as exc:
        driver_error = exc.__cause__
        sqlstate = getattr(driver_error, 'sqlstate', None) or getattr(driver_error, 'pgcode', None)
        if sqlstate in {'55P03', '40P01', '40001'}:
            raise conflict_type('ثبت به دلیل تداخل هم‌زمان انجام نشد؛ دوباره تلاش کنید.') from exc
        raise
