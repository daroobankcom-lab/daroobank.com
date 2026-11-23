from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class ClinicalDraft(models.Model):
    """An unverified private statement and asserted reference, never public content."""
    PATIENT = 'patient'
    PROFESSIONAL = 'professional'
    AUDIENCES = [(PATIENT, 'Patient'), (PROFESSIONAL, 'Professional')]
    subject = models.CharField(max_length=200)
    audience = models.CharField(max_length=20, choices=AUDIENCES)
    title = models.CharField(max_length=200)
    statement = models.TextField(max_length=4000)
    reference_title = models.CharField(max_length=300)
    reference_url = models.URLField(max_length=200)
    reference_location = models.CharField(max_length=300)
    reference_author = models.CharField(max_length=200, blank=True)
    reference_version = models.CharField(max_length=200, blank=True)
    reference_published_on = models.DateField(null=True, blank=True)
    reference_accessed_on = models.DateField(null=True, blank=True)
    parent = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='revisions')
    parent_payload_sha256 = models.CharField(max_length=64, blank=True, default='')
    change_reason = models.TextField(max_length=1000, blank=True)
    payload_sha256 = models.CharField(max_length=64)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='clinical_drafts')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']
        permissions = [('review_clinicaldraft', 'Can record preliminary clinical draft reviews')]
        constraints = [
            models.CheckConstraint(condition=Q(audience__in=['patient', 'professional']), name='clinical_draft_valid_audience'),
            models.CheckConstraint(condition=(Q(parent__isnull=True, parent_payload_sha256='', change_reason='') |
                                             (Q(parent__isnull=False) & ~Q(parent_payload_sha256='') & ~Q(change_reason=''))),
                                   name='clinical_parent_fields_consistent'),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Draft versions cannot be edited; create a revision.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Draft versions cannot be deleted through this model.')


class ClinicalDraftReview(models.Model):
    FURTHER_REVIEW = 'further_review'
    REJECT = 'reject'
    DEFER = 'defer'
    DECISIONS = [(FURTHER_REVIEW, 'Refer for further review'), (REJECT, 'Reject'), (DEFER, 'Defer')]
    draft = models.ForeignKey(ClinicalDraft, on_delete=models.PROTECT, related_name='reviews')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='clinical_draft_reviews')
    decision = models.CharField(max_length=20, choices=DECISIONS)
    reason = models.TextField(max_length=1000)
    draft_payload_sha256 = models.CharField(max_length=64)
    review_snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-pk']
        constraints = [models.CheckConstraint(condition=Q(decision__in=['further_review', 'reject', 'defer']),
                                               name='clinical_review_valid_decision')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Reviews cannot be edited; record a new review.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Reviews cannot be deleted through this model.')


class ClinicalReferenceAssertion(models.Model):
    """Supplementary asserted citation for a single draft version; never verified."""
    RELATIONS = [('supports', 'Claimed support'), ('contradicts', 'Claimed contradiction'),
                 ('context', 'Context'), ('unclear', 'Unclear relationship')]
    draft = models.ForeignKey(ClinicalDraft, on_delete=models.PROTECT, related_name='additional_references')
    draft_payload_sha256 = models.CharField(max_length=64)
    reference_title = models.CharField(max_length=300)
    reference_url = models.URLField(max_length=200)
    reference_location = models.CharField(max_length=300)
    reference_author = models.CharField(max_length=200, blank=True)
    reference_version = models.CharField(max_length=200, blank=True)
    reference_published_on = models.DateField(null=True, blank=True)
    reference_accessed_on = models.DateField(null=True, blank=True)
    relation = models.CharField(max_length=20, choices=RELATIONS)
    payload_sha256 = models.CharField(max_length=64)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='clinical_reference_assertions')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()  # clinical draft add/view permissions govern the workflow
        ordering = ['pk']
        constraints = [
            models.UniqueConstraint(fields=['draft', 'payload_sha256'], name='unique_clinical_reference_assertion'),
            models.CheckConstraint(condition=Q(relation__in=['supports', 'contradicts', 'context', 'unclear']),
                                   name='clinical_reference_valid_relation'),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Reference assertions cannot be edited; record a new assertion.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Reference assertions cannot be deleted through this model.')
