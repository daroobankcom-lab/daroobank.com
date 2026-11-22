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
        self.search_text = normalize_search(' '.join((self.name_fa, self.name_en, self.manufacturer, self.strength, self.dosage_form, self.package_description, self.irc)))
        self.full_clean()
        # Keep the normalized projection synchronized even for partial saves.
        if kwargs.get('update_fields') is not None:
            kwargs['update_fields'] = set(kwargs['update_fields']) | {'search_text'}
        return super().save(*args, **kwargs)
