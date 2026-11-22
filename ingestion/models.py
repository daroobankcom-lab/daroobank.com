from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class ImportReceipt(models.Model):
    """Summary of a completed staff CSV stage; not a source/run audit."""
    PRODUCT = 'product'
    PRICE = 'price'
    KIND_CHOICES = [(PRODUCT, 'Product'), (PRICE, 'Price')]

    kind = models.CharField(max_length=8, choices=KIND_CHOICES)
    source_name = models.CharField(max_length=200)
    source_url = models.URLField(max_length=200)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='import_receipts')
    created_at = models.DateTimeField(auto_now_add=True)
    rows = models.PositiveIntegerField()
    created = models.PositiveIntegerField()
    duplicates = models.PositiveIntegerField()
    suggested = models.PositiveIntegerField(null=True, blank=True)
    ambiguous = models.PositiveIntegerField(null=True, blank=True)
    unmatched = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        default_permissions = ()  # Views use candidate-domain permissions, not a broad receipt permission.
        ordering = ['-pk']
        constraints = [
            models.CheckConstraint(condition=Q(rows__gt=0) & Q(rows=F('created') + F('duplicates')),
                                   name='receipt_total_consistent'),
            models.CheckConstraint(condition=(
                (Q(kind='product', rows__lte=1000) & Q(suggested__isnull=True, ambiguous__isnull=True, unmatched__isnull=True)) |
                (Q(kind='price', rows__lte=5000) & Q(suggested__isnull=False, ambiguous__isnull=False, unmatched__isnull=False)
                 & Q(rows=F('suggested') + F('ambiguous') + F('unmatched')))
            ), name='receipt_kind_and_matches_consistent'),
        ]
        indexes = [models.Index(fields=['kind', '-id'], name='receipt_kind_id_idx')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Import receipts cannot be edited through this model.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Import receipts cannot be deleted through this model.')
