from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import models
from .normalization import normalize_search

class ProductPresentation(models.Model):
    """A limited, source-backed package record, not a drug monograph or price."""
    name_fa = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200, blank=True)
    manufacturer = models.CharField(max_length=200)
    strength = models.CharField(max_length=100)
    dosage_form = models.CharField(max_length=100)
    package_description = models.CharField(max_length=200)
    irc = models.CharField(max_length=80, blank=True)
    irc_normalized = models.CharField(max_length=80, blank=True, default='', db_index=True, editable=False)
    source_name = models.CharField(max_length=200)
    source_url = models.URLField(validators=[URLValidator(schemes=['https'])])
    verified_at = models.DateTimeField(null=True, blank=True)
    published = models.BooleanField(default=False)
    search_text = models.TextField(editable=False, default='')

    def clean(self):
        super().clean()
        if self.published and not self.verified_at:
            raise ValidationError({'verified_at': 'Published products need a verification date.'})

    def save(self, *args, **kwargs):
        fields = ('name_fa', 'name_en', 'manufacturer', 'strength', 'dosage_form', 'package_description', 'irc')
        update_fields = kwargs.get('update_fields')
        values = {field: getattr(self, field) for field in fields}
        if update_fields is not None:
            update_fields = set(update_fields)
            if not update_fields:
                return super().save(*args, **kwargs)
            if self.pk:
                stored = type(self).objects.using(kwargs.get('using') or self._state.db).get(pk=self.pk)
                values = {field: values[field] if field in update_fields else getattr(stored, field) for field in fields}
            kwargs['update_fields'] = update_fields | {'search_text', 'irc_normalized'}
        self.irc_normalized = normalize_search(values['irc'])
        self.search_text = normalize_search(' '.join(values[field] for field in fields))
        self.full_clean()
        return super().save(*args, **kwargs)


class ProductCandidate(models.Model):
    """Private source assertions; never a public product or clinical approval."""
    source_name = models.CharField(max_length=200)
    source_url = models.URLField(max_length=200)
    source_record_id = models.CharField(max_length=160)
    source_fields = models.JSONField()
    payload_sha256 = models.CharField(max_length=64)
    staged_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='staged_product_candidates')
    source_rights_attested = models.BooleanField(default=False)
    collected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        permissions = [('review_productcandidate', 'Can record preliminary product candidate reviews')]
        constraints = [models.UniqueConstraint(
            fields=['source_url', 'source_record_id', 'payload_sha256'], name='unique_product_source_revision',
        )]


class ProductCandidateReview(models.Model):
    FURTHER_REVIEW = 'further_review'
    REJECT = 'reject'
    DEFER = 'defer'
    DECISIONS = [(FURTHER_REVIEW, 'Suitable for further review'), (REJECT, 'Reject'), (DEFER, 'Defer')]
    candidate = models.ForeignKey(ProductCandidate, on_delete=models.PROTECT, related_name='reviews')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='product_candidate_reviews')
    decision = models.CharField(max_length=20, choices=DECISIONS)
    reason = models.TextField(max_length=1000)
    candidate_payload_sha256 = models.CharField(max_length=64)
    review_snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']
        constraints = [models.CheckConstraint(
            condition=models.Q(decision__in=['further_review', 'reject', 'defer']),
            name='product_review_valid_decision',
        )]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Review records cannot be edited; add a new review instead.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Review records cannot be deleted through this model.')
