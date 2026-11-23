from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class PriceCandidate(models.Model):
    """A staged source assertion, never an approved or publicly visible price."""
    MATCH_SUGGESTED = 'suggested'
    MATCH_AMBIGUOUS = 'ambiguous'
    MATCH_UNMATCHED = 'unmatched'
    MATCH_CHOICES = [
        (MATCH_SUGGESTED, 'Suggested for review'),
        (MATCH_AMBIGUOUS, 'Ambiguous'),
        (MATCH_UNMATCHED, 'Unmatched'),
    ]

    source_name = models.CharField(max_length=200)
    source_url = models.URLField(max_length=200)
    source_record_id = models.CharField(max_length=160)
    payload_sha256 = models.CharField(max_length=64)
    # Retain only the validated, structured CSV fields, not arbitrary raw files.
    source_fields = models.JSONField()
    original_amount = models.CharField(max_length=50)
    original_currency = models.CharField(max_length=5)
    amount_rial = models.PositiveBigIntegerField()
    price_category = models.CharField(max_length=24)
    unit = models.CharField(max_length=16)
    effective_date = models.DateField(null=True, blank=True)
    source_published_date = models.DateField(null=True, blank=True)
    collected_at = models.DateTimeField(auto_now_add=True)
    staged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='staged_price_candidates',
    )
    source_rights_attested = models.BooleanField(default=False)
    suggested_product = models.ForeignKey(
        'catalog.ProductPresentation', on_delete=models.PROTECT,
        null=True, blank=True, related_name='price_suggestions',
    )
    match_status = models.CharField(max_length=12, choices=MATCH_CHOICES)

    class Meta:
        permissions = [('review_pricecandidate', 'Can record preliminary price candidate reviews')]
        constraints = [
            models.UniqueConstraint(
                fields=['source_url', 'source_record_id', 'payload_sha256'],
                name='unique_price_candidate_source_revision',
            ),
            models.CheckConstraint(condition=models.Q(amount_rial__gt=0), name='candidate_positive_rial'),
            models.CheckConstraint(
                condition=(models.Q(match_status='suggested', suggested_product__isnull=False)
                           | models.Q(match_status__in=['ambiguous', 'unmatched'], suggested_product__isnull=True)),
                name='candidate_suggestion_consistent',
            ),
        ]
        indexes = [models.Index(fields=['source_url', 'source_record_id'])]


class PriceCandidateReview(models.Model):
    """Preliminary identity triage only; not a price approval or publication."""
    ACCEPT_SUGGESTION = 'accept_suggestion'
    REJECT = 'reject'
    DEFER = 'defer'
    DECISIONS = [
        (ACCEPT_SUGGESTION, 'Accept preliminary suggestion'),
        (REJECT, 'Reject candidate'),
        (DEFER, 'Request further investigation'),
    ]
    candidate = models.ForeignKey(PriceCandidate, on_delete=models.PROTECT, related_name='reviews')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='price_reviews')
    decision = models.CharField(max_length=24, choices=DECISIONS)
    reason = models.TextField(max_length=1000)
    reviewed_product = models.ForeignKey(
        'catalog.ProductPresentation', on_delete=models.PROTECT,
        null=True, blank=True, related_name='preliminary_price_reviews',
    )
    candidate_payload_sha256 = models.CharField(max_length=64)
    product_identity_sha256 = models.CharField(max_length=64, blank=True)
    review_snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(decision='accept_suggestion', reviewed_product__isnull=False)
                           | models.Q(decision__in=['reject', 'defer'], reviewed_product__isnull=True)),
                name='review_product_matches_decision',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Review records cannot be edited; add a new review instead.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Review records cannot be deleted through this model.')
