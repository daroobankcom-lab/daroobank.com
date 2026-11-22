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
    manifest_version = models.PositiveSmallIntegerField(null=True, blank=True)
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
            models.CheckConstraint(condition=Q(manifest_version__isnull=True) | Q(manifest_version=1),
                                   name='receipt_manifest_version_supported'),
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


class ImportReceiptItem(models.Model):
    """A normalized input-row outcome, not a raw file or independent evidence."""
    receipt = models.ForeignKey(ImportReceipt, on_delete=models.PROTECT, related_name='items')
    ordinal = models.PositiveIntegerField()
    source_record_id = models.CharField(max_length=160)
    payload_sha256 = models.CharField(max_length=64)
    was_created = models.BooleanField()
    product_candidate = models.ForeignKey('catalog.ProductCandidate', null=True, blank=True,
                                          on_delete=models.PROTECT, related_name='receipt_items')
    price_candidate = models.ForeignKey('pricing.PriceCandidate', null=True, blank=True,
                                        on_delete=models.PROTECT, related_name='receipt_items')
    match_status = models.CharField(max_length=12, blank=True, default='')

    class Meta:
        default_permissions = ()
        ordering = ['ordinal']
        constraints = [
            models.UniqueConstraint(fields=['receipt', 'ordinal'], name='receipt_item_unique_ordinal'),
            models.CheckConstraint(condition=Q(ordinal__gte=1, ordinal__lte=5000), name='receipt_item_bounded_ordinal'),
            models.CheckConstraint(condition=(
                Q(product_candidate__isnull=False, price_candidate__isnull=True, match_status='') |
                Q(product_candidate__isnull=True, price_candidate__isnull=False,
                  match_status__in=['suggested', 'ambiguous', 'unmatched'])
            ), name='receipt_item_single_domain'),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Import receipt items cannot be edited through this model.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Import receipt items cannot be deleted through this model.')
