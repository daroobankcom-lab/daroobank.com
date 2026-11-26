"""Minimal synthetic request-protection state: opt-in windows, not an audit log."""
from django.db import models


class StaffLoginWindow(models.Model):
    # HMAC of normalized REMOTE_ADDR, not a raw IP or account identifier.
    client_key = models.CharField(max_length=64, primary_key=True, editable=False)
    started_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField()

    class Meta:
        default_permissions = ()


class PublicReadWindow(models.Model):
    # HMAC of normalized REMOTE_ADDR under the public-read scope, so this window
    # cannot be joined with the login window on a shared key. Not an access log:
    # it holds no path, no route, no actor and no count of what was read.
    client_key = models.CharField(max_length=64, primary_key=True, editable=False)
    started_at = models.DateTimeField(db_index=True)
    reads = models.PositiveIntegerField()

    class Meta:
        default_permissions = ()
