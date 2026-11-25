"""Minimal synthetic staff-login protection state, not an audit log."""
from django.db import models


class StaffLoginWindow(models.Model):
    # HMAC of normalized REMOTE_ADDR, not a raw IP or account identifier.
    client_key = models.CharField(max_length=64, primary_key=True, editable=False)
    started_at = models.DateTimeField(db_index=True)
    attempts = models.PositiveSmallIntegerField()

    class Meta:
        default_permissions = ()
