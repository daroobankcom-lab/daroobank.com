from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class SourceClaim(models.Model):
    """A recorded assertion and evidence reference, not permission to use a source."""
    source_name = models.CharField(max_length=200)
    source_url = models.URLField(max_length=200)
    owner = models.CharField(max_length=200)
    evidence_url = models.URLField(max_length=200)
    evidence_note = models.TextField(max_length=1000, blank=True)
    claims_collection = models.BooleanField(default=False)
    claims_storage = models.BooleanField(default=False)
    claims_publication = models.BooleanField(default=False)
    starts_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField(null=True, blank=True)
    payload_sha256 = models.CharField(max_length=64)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='source_claims')
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        permissions = [('review_sourceclaim', 'Can record preliminary source claim reviews')]
        constraints = [
            models.UniqueConstraint(fields=['source_url', 'payload_sha256'], name='unique_source_claim_revision'),
            models.CheckConstraint(condition=(models.Q(claims_collection=True) | models.Q(claims_storage=True) |
                                              models.Q(claims_publication=True)), name='source_claim_scope_present'),
            models.CheckConstraint(condition=(models.Q(starts_on__isnull=True) | models.Q(expires_on__isnull=True) |
                                              models.Q(starts_on__lte=models.F('expires_on'))), name='source_claim_date_order'),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Source claims cannot be edited; record a new claim instead.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Source claims cannot be deleted through this model.')


class SourceClaimReview(models.Model):
    FURTHER_REVIEW = 'further_review'
    REJECT = 'reject'
    DEFER = 'defer'
    DECISIONS = [(FURTHER_REVIEW, 'Refer for further review'), (REJECT, 'Reject'), (DEFER, 'Defer')]
    claim = models.ForeignKey(SourceClaim, on_delete=models.PROTECT, related_name='reviews')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='source_claim_reviews')
    decision = models.CharField(max_length=20, choices=DECISIONS)
    reason = models.TextField(max_length=1000)
    claim_payload_sha256 = models.CharField(max_length=64)
    review_snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']
        constraints = [models.CheckConstraint(condition=models.Q(decision__in=['further_review', 'reject', 'defer']),
                                               name='source_review_valid_decision')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Source reviews cannot be edited; record a new review instead.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Source reviews cannot be deleted through this model.')
