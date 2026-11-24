# ADR 0125: require a real integer in the public-detail service

Status: development input validation, 24 November 2026.

The direct Python `get_public_presentation` service now accepts only a built-in integer between 1 and PostgreSQL's signed-bigint maximum. It raises the existing generic `Http404` before a query for other types or values. Previously `True`, an integral float or `Decimal` could be coerced to an existing primary key; other types could raise `TypeError`. This is a compatibility change for direct callers and is not an authorization or confidentiality mechanism.

The HTTP path already uses Django's integer route converter; selected valid and out-of-range HTTP paths retain their behavior. Synthetic tests check direct malformed/coercible values, zero queries on rejection, and ordinary HTML/API behavior via the existing suite. This does not cover arbitrary custom URL configurations, every Python object, data verification or races after the fetch.
