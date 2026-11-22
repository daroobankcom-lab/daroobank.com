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
