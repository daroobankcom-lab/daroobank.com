"""Common age check for bounded, uncompressed timestamp-signed cursors."""
import time

from django.core import signing


def loads_nonfuture(token, *, salt, max_age):
    """Verify the signature and expiry, then reject timestamps after this host's clock.

    Callers must enforce their own input type, length and no-compression rules
    before using this helper. Clocks that move backwards or disagree across
    hosts can invalidate otherwise legitimate cursors.
    """
    try:
        data = signing.loads(token, salt=salt, max_age=max_age)
        timestamp = signing.b62_decode(token.rsplit(':', 2)[-2])
    except (IndexError, OverflowError) as exc:
        # A correctly signed empty or excessively large timestamp can make
        # Django's base62/age calculation raise rather than BadSignature.
        raise signing.BadSignature('Invalid cursor timestamp') from exc
    if timestamp > time.time():
        raise signing.BadSignature('Cursor timestamp is in the future')
    return data
