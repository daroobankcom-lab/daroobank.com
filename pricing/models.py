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
    suggested_product = models.ForeignKey(
        'catalog.ProductPresentation', on_delete=models.PROTECT,
        null=True, blank=True, related_name='price_suggestions',
    )
    match_status = models.CharField(max_length=12, choices=MATCH_CHOICES)

    class Meta:
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
