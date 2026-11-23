"""Current-account lookup only; not historical identity or authorization proof."""
from django.contrib.auth import get_user_model

MAX_ID = 9_223_372_036_854_775_807


def current_accounts(ids, *, using):
    valid = {pk for pk in ids if type(pk) is int and 1 <= pk <= MAX_ID}
    return get_user_model().objects.using(using).in_bulk(valid) if valid else {}


def current_account_ids(ids, *, using):
    """Return existing IDs only; deliberately do not fetch account attributes."""
    valid = {pk for pk in ids if type(pk) is int and 1 <= pk <= MAX_ID}
    if not valid:
        return set()
    return set(get_user_model().objects.using(using).filter(pk__in=valid).values_list('pk', flat=True))


def current_account_exists(pk, *, using):
    return (type(pk) is int and 1 <= pk <= MAX_ID
            and get_user_model().objects.using(using).filter(pk=pk).exists())
