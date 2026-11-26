"""Re-verify a write actor against the database; a partial mitigation, not revocation.

Guarded write services authorize against the actor object a caller supplies, which
can be stale by the time the transaction runs. This helper reloads that account and
repeats the status, permission and (optionally) session password-hash checks.

It is **not** durable revocation:

* an unlocked recheck is a point-in-time read, so a change committed afterwards
  still races the write;
* ``lock=True`` takes a PostgreSQL ``FOR NO KEY UPDATE`` account-row lock, which
  orders the write against account status updates but cannot cancel a writer that
  already holds the lock, and must only be used by services that lock the account
  row before their target row to keep one lock order;
* the hash covers the password field only, so logout, session deletion or
  rotation, group and permission changes, alternate authentication backends and
  MFA factors are out of scope.
"""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.utils.crypto import constant_time_compare

MAX_PK = 9_223_372_036_854_775_807


def recheck_actor(actor, perms=(), *, session_auth_hash=None, lock=False):
    """Return a freshly loaded account, denying a stale, revoked or absent actor.

    ``perms`` are permission codenames the actor must currently hold. A supplied
    ``session_auth_hash`` must match the account's current session authentication
    hash; an omitted hash authenticates nothing and keeps direct service callers
    working. ``lock=True`` requires an atomic block.
    """
    if actor is None or type(actor.pk) is not int or not 1 <= actor.pk <= MAX_PK:
        raise PermissionDenied
    accounts = get_user_model().objects
    if lock:
        # NO KEY UPDATE still allows foreign-key key-share locks. Callers must lock
        # the account row before their target row so all services share one order.
        accounts = accounts.select_for_update(no_key=True)
    current = accounts.filter(pk=actor.pk).first()
    if (current is None or not current.is_authenticated or not current.is_active or not current.is_staff
            or any(not current.has_perm(perm) for perm in perms)):
        raise PermissionDenied
    if session_auth_hash is not None and not (isinstance(session_auth_hash, str)
                                              and constant_time_compare(session_auth_hash,
                                                                        current.get_session_auth_hash())):
        raise PermissionDenied
    return current
