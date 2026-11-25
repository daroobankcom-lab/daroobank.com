"""Selected bounded revision-link text reads; not a DB-work limit."""
from django.db.models.functions import Substr

# Existing revision validators accept at most 1,000 characters. One extra
# character preserves rejection of oversize text rather than validating a prefix.
MAX_REASON_PREFIX = 1001


def bounded_revision_reasons(queryset):
    return queryset.defer('change_reason').annotate(_reason_prefix=Substr('change_reason', 1, MAX_REASON_PREFIX))


def materialize_revision_reason(link):
    # Avoid deferred-field fetching after the bounded SELECT.
    link.change_reason = link._reason_prefix
