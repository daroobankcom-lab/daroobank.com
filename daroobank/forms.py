"""Forms shared by the development-only staff portal."""
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .validation import has_control_or_surrogate, has_forbidden_multiline_control


class RawControlsMixin:
    """Check raw selected single-line input that field cleanup may have trimmed."""

    raw_control_fields = ()

    def clean(self):
        cleaned = super().clean()
        for name in self.raw_control_fields:
            field = self.fields[name]
            value = field.widget.value_from_datadict(self.data, self.files, self.add_prefix(name))
            if isinstance(value, str) and has_control_or_surrogate(value):
                self.add_error(name, 'این مقدار شامل نویسه کنترلی نامعتبر است.')
        return cleaned


class RawMultilineControlsMixin:
    """Inspect raw selected multiline values before whitespace cleanup can hide controls."""

    raw_multiline_control_fields = ()

    def clean(self):
        cleaned = super().clean()
        for name in self.raw_multiline_control_fields:
            field = self.fields[name]
            value = field.widget.value_from_datadict(self.data, self.files, self.add_prefix(name))
            if isinstance(value, str) and has_forbidden_multiline_control(value):
                self.add_error(name, 'این مقدار شامل نویسه کنترلی نامعتبر است.')
        return cleaned


class SourceUploadRawControlsMixin(RawControlsMixin):
    """Reject raw source controls before CharField/URLField trim can hide them."""

    raw_control_fields = ('source_name', 'source_url')


class StaffAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A forced initial focus bypasses the page title and skip link for
        # keyboard and screen-reader users. Leave the browser's initial focus.
        self.fields['username'].widget.attrs.pop('autofocus', None)

    def confirm_login_allowed(self, user):
        try:
            super().confirm_login_allowed(user)
        except ValidationError as exc:
            # A custom backend may authenticate inactive users. Reject them
            # generically and do not retain the denied identity in the form.
            self.user_cache = None
            raise self.get_invalid_login_error() from exc
        if not user.is_staff:
            # Use the same generic invalid-login error as a bad credential.
            # Individual staff routes must still enforce their permissions.
            self.user_cache = None
            raise self.get_invalid_login_error()
