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
    irc_normalized = models.CharField(max_length=80, blank=True, default='', db_index=True, editable=False)
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


class PrivateIdentityRecord(models.Model):
    """Synthetic, unverified assertion; ordinary writes cannot rewrite it."""
    source_name = models.CharField(max_length=200)
    source_url = models.URLField(max_length=200)
    payload_sha256 = models.CharField(max_length=64)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Identity assertions cannot be edited; record a new assertion.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Identity assertions cannot be deleted through this model.')


class IngredientDraft(PrivateIdentityRecord):
    name_fa = models.CharField(max_length=200)
    name_en = models.CharField(max_length=200, blank=True)

    class Meta:
        default_permissions = ()
        permissions = [('view_identityworkspace', 'Can view private catalog identity drafts'),
                       ('add_identityworkspace', 'Can add private catalog identity drafts'),
                       ('review_identityworkspace', 'Can record preliminary catalog identity reviews')]
        ordering = ['-pk']


class FormulationDraft(PrivateIdentityRecord):
    name = models.CharField(max_length=200)
    dosage_form = models.CharField(max_length=100)
    route = models.CharField(max_length=100)

    class Meta:
        default_permissions = ()
        ordering = ['-pk']


class FormulationComponent(models.Model):
    formulation = models.ForeignKey(FormulationDraft, on_delete=models.PROTECT, related_name='components')
    ingredient = models.ForeignKey(IngredientDraft, on_delete=models.PROTECT, related_name='formulation_components')
    ingredient_sha256 = models.CharField(max_length=64)
    ordinal = models.PositiveSmallIntegerField()
    numerator = models.DecimalField(max_digits=12, decimal_places=4)
    numerator_unit = models.CharField(max_length=50)
    denominator = models.DecimalField(max_digits=12, decimal_places=4)
    denominator_unit = models.CharField(max_length=50)

    class Meta:
        default_permissions = ()
        ordering = ['ordinal']
        constraints = [
            models.UniqueConstraint(fields=['formulation', 'ordinal'], name='identity_component_ordinal_unique'),
            models.UniqueConstraint(fields=['formulation', 'ingredient'], name='identity_component_ingredient_unique'),
            models.CheckConstraint(condition=models.Q(ordinal__gte=1, ordinal__lte=5), name='identity_component_ordinal_range'),
            models.CheckConstraint(condition=models.Q(numerator__gt=0, denominator__gt=0), name='identity_component_positive'),
        ]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Components cannot be edited; record a new formulation.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Components cannot be deleted through this model.')


class IdentityProductDraft(PrivateIdentityRecord):
    formulation = models.ForeignKey(FormulationDraft, on_delete=models.PROTECT, related_name='product_drafts')
    formulation_sha256 = models.CharField(max_length=64)
    name = models.CharField(max_length=200)
    brand = models.CharField(max_length=200, blank=True)
    manufacturer = models.CharField(max_length=200)

    class Meta:
        default_permissions = ()
        ordering = ['-pk']


class IdentityPackageDraft(PrivateIdentityRecord):
    product = models.ForeignKey(IdentityProductDraft, on_delete=models.PROTECT, related_name='package_drafts')
    product_sha256 = models.CharField(max_length=64)
    description = models.CharField(max_length=200)
    quantity = models.DecimalField(max_digits=12, decimal_places=4)
    quantity_unit = models.CharField(max_length=50)
    irc = models.CharField(max_length=80, blank=True)

    class Meta:
        default_permissions = ()
        ordering = ['-pk']
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gt=0), name='identity_package_quantity_positive')]


class IdentityPackageReview(models.Model):
    DECISIONS = [('further_review', 'Refer for further review'), ('reject', 'Reject'), ('defer', 'Defer')]
    package = models.ForeignKey(IdentityPackageDraft, on_delete=models.PROTECT, related_name='reviews')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    decision = models.CharField(max_length=20, choices=DECISIONS)
    reason = models.TextField(max_length=1000)
    graph_sha256 = models.CharField(max_length=64)
    graph_snapshot = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        ordering = ['-pk']
        constraints = [models.CheckConstraint(condition=models.Q(decision__in=['further_review', 'reject', 'defer']),
                                             name='identity_review_valid_decision')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Identity reviews cannot be edited.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Identity reviews cannot be deleted through this model.')


class IdentityPackageRevision(models.Model):
    """An asserted correction link, not a verified identity or approval."""
    parent = models.ForeignKey(IdentityPackageDraft, on_delete=models.PROTECT, related_name='revision_children')
    child = models.OneToOneField(IdentityPackageDraft, on_delete=models.PROTECT, related_name='revision_parent')
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    change_reason = models.TextField(max_length=1000)
    parent_graph_sha256 = models.CharField(max_length=64)
    child_graph_sha256 = models.CharField(max_length=64)
    payload_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        ordering = ['-pk']
        constraints = [models.CheckConstraint(condition=models.Q(parent_id__lt=models.F('child_id')),
                                               name='identity_revision_parent_before_child')]

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Identity revision links cannot be edited.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Identity revision links cannot be deleted through this model.')


class PrivateIdentityRevision(models.Model):
    """Immediate asserted correction link; ordinary instance mutation is guarded."""
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    change_reason = models.TextField(max_length=1000)
    parent_graph_sha256 = models.CharField(max_length=64)
    child_graph_sha256 = models.CharField(max_length=64)
    payload_sha256 = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError('Identity revision links cannot be edited.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Identity revision links cannot be deleted through this model.')


class IngredientRevision(PrivateIdentityRevision):
    parent = models.ForeignKey(IngredientDraft, on_delete=models.PROTECT, related_name='revision_children')
    child = models.OneToOneField(IngredientDraft, on_delete=models.PROTECT, related_name='revision_parent')

    class Meta:
        default_permissions = ()
        ordering = ['-pk']
        constraints = [models.CheckConstraint(condition=models.Q(parent_id__lt=models.F('child_id')),
                                               name='ingredient_revision_parent_before_child')]


class FormulationRevision(PrivateIdentityRevision):
    parent = models.ForeignKey(FormulationDraft, on_delete=models.PROTECT, related_name='revision_children')
    child = models.OneToOneField(FormulationDraft, on_delete=models.PROTECT, related_name='revision_parent')

    class Meta:
        default_permissions = ()
        ordering = ['-pk']
        constraints = [models.CheckConstraint(condition=models.Q(parent_id__lt=models.F('child_id')),
                                               name='form_revision_parent_before_child')]


class ProductRevision(PrivateIdentityRevision):
    parent = models.ForeignKey(IdentityProductDraft, on_delete=models.PROTECT, related_name='revision_children')
    child = models.OneToOneField(IdentityProductDraft, on_delete=models.PROTECT, related_name='revision_parent')

    class Meta:
        default_permissions = ()
        ordering = ['-pk']
        constraints = [models.CheckConstraint(condition=models.Q(parent_id__lt=models.F('child_id')),
                                               name='product_revision_parent_before_child')]
