"""Common age check for bounded, uncompressed timestamp-signed cursors."""
import time

from django.core import signing


def loads_nonfuture(token, *, salt, max_age):
    """Verify the signature and expiry, then reject timestamps after this host's clock.

    Callers must enforce their own input type, length and no-compression rules
    before using this helper. Clocks that move backwards or disagree across
    hosts can invalidate otherwise legitimate cursors.
    """
    data = signing.loads(token, salt=salt, max_age=max_age)
    timestamp = signing.b62_decode(token.rsplit(':', 2)[-2])
    if timestamp > time.time():
        raise signing.BadSignature('Cursor timestamp is in the future')
    return data
