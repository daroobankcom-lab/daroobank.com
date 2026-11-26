"""State-derived session invalidation for the staff surface.

Django's session-auth hash covers the password field only. Deactivating an account,
clearing ``is_staff`` or removing a permission leaves an unexpired session in place,
and restoring the flag revives that session — the gap recorded in ADR 0191.

This module derives a keyed fingerprint of the authorization state a session was
established with and compares it against the *current* state of the account the session
names, on every staff request. Two properties matter:

* the comparison reads the database rather than relying on a signal having fired, so it
  also holds when the state was changed by ``QuerySet.update()``, a management shell or
  any other direct write;
* the session is destroyed the first time it is presented while the account differs from
  what it was bound to, so restoring the flag afterwards has nothing left to revive.

The guard is fail-closed and deliberately coarse: a **grant** ends a session exactly
as a revocation does. Telling them apart would require ordering permission sets, and
the property being bought here is that removed access stays removed until the account
authenticates again.

It is not a complete account-lifecycle design, and it does not claim to be:

* a request that has already passed the guard runs to completion (see ADR 0192 for
  the one write path that serializes against account-row changes);
* the guard fires only when a request arrives. An off/on transition that no request
  observes leaves the stored state byte-identical to the bound state, so a dormant
  session survives it; nothing in the database records that the transition happened.
  Removing access must therefore also revoke sessions explicitly — see the
  ``revoke_staff_sessions`` management command;
* removing a backend from ``AUTHENTICATION_BACKENDS`` is a settings change that no
  request-time comparison can observe;
* MFA factors, session stores other than the database one this project uses, and
  concurrent sessions on other workers are out of scope;
* the fingerprint costs a few extra queries per staff request. Public read paths are
  not touched, because the middleware only runs on staff paths.
"""
from django.contrib.auth import SESSION_KEY, get_user_model
from django.contrib.auth.signals import user_logged_in
from django.utils.crypto import constant_time_compare, salted_hmac

SESSION_FINGERPRINT_KEY = 'staff_auth_fingerprint'
_KEY_SALT = 'daroobank.staff.session.v1'


def authorization_fingerprint(user_pk):
    """Return a keyed digest of one account's current authorization state.

    ``None`` means there is no such account, which callers must treat as a mismatch:
    a deleted account must not keep a session alive.
    """
    if type(user_pk) is not int or user_pk < 1:
        return None
    current = get_user_model().objects.filter(pk=user_pk).first()
    if current is None:
        return None
    # `get_all_permissions` covers direct and group grants, so a change to a group's
    # permissions invalidates every member's session without enumerating groups here.
    payload = '|'.join((
        str(current.is_active),
        str(current.is_staff),
        str(current.is_superuser),
        current.get_session_auth_hash(),
        ','.join(sorted(current.get_all_permissions())),
    ))
    return salted_hmac(_KEY_SALT, payload, algorithm='sha256').hexdigest()


def session_matches_account(request):
    """Report whether this request's session still matches the account it names.

    The session is inspected directly, through the authentication key Django stores in
    it, rather than through ``request.user``. That distinction is the whole point: for a
    deactivated account ``ModelBackend.get_user`` already returns no user, so
    ``request.user`` is anonymous and a guard written against it would find nothing to
    compare — the session would survive the deactivated window and be revived by a
    later reactivation, which is exactly the gap in ADR 0191.

    A session that names an account but carries no fingerprint — one established before
    this guard existed, or by a login path that bypassed the ``user_logged_in`` signal —
    does not match, so it is ended rather than trusted. A session that names no account
    has nothing bound and is left alone.
    """
    session = getattr(request, 'session', None)
    if session is None:
        return True
    named = session.get(SESSION_KEY)
    if named is None:
        return True
    try:
        user_pk = int(named)
    except (TypeError, ValueError):
        return False
    current = authorization_fingerprint(user_pk)
    if current is None:
        return False
    stored = session.get(SESSION_FINGERPRINT_KEY)
    if not isinstance(stored, str):
        return False
    return constant_time_compare(stored, current)


def _bind_fingerprint(sender, request, user, **kwargs):
    """Record the account state a new session is being established against."""
    if request is None or not hasattr(request, 'session'):
        return
    fingerprint = authorization_fingerprint(user.pk)
    if fingerprint is not None:
        request.session[SESSION_FINGERPRINT_KEY] = fingerprint


# `daroobank` is not an installed app, so there is no AppConfig.ready() to hook. This
# module is imported by `daroobank.middleware`, which Django loads at startup.
user_logged_in.connect(_bind_fingerprint, dispatch_uid='daroobank.staff.session.bind')
