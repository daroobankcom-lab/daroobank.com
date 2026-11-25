"""Forms shared by the development-only staff portal."""
from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from .validation import has_control_or_surrogate, has_forbidden_multiline_control


class ExplicitCheckboxInput(forms.CheckboxInput):
    """Pass raw values to validation rather than treating any nonempty text as true."""

    def value_from_datadict(self, data, files, name):
        if hasattr(data, 'getlist'):
            values = data.getlist(name)
            if not values:
                return None
            if len(values) != 1:
                return values  # Rejected rather than silently choosing one value.
            return values[0]
        return data.get(name)


class ExplicitBooleanField(forms.BooleanField):
    """Accept common explicit checkbox tokens only; omission means unchecked."""

    widget = ExplicitCheckboxInput

    def to_python(self, value):
        if value is None or value is False:
            return False
        if value is True:
            return True
        if isinstance(value, str):
            if value.lower() in ('on', 'true', '1'):
                return True
            if value.lower() in ('', 'off', 'false', '0'):
                return False
        raise ValidationError('مقدار انتخاب معتبر نیست.', code='invalid')

    def bound_data(self, data, initial):
        try:
            # Render the validated boolean state, not a truthy raw string. This
            # also prevents malformed input being echoed as the HTML value.
            return self.to_python(initial if self.disabled else data)
        except ValidationError:
            return False

    def has_changed(self, initial, data):
        try:
            return super().has_changed(initial, data)
        except ValidationError:
            # Invalid input must not crash formsets or change detection.
            return True


def _duplicate_field(form, name):
    """Only selected single-value fields use this check, not multi-selects."""
    return (not form.fields[name].disabled and hasattr(form.data, 'getlist')
            and len(form.data.getlist(form.add_prefix(name))) > 1)


def _check_raw_field(form, name, invalid_control):
    # Like Django's own field cleaning, disabled fields use the server's
    # initial value; arbitrary request data must not alter or invalidate it.
    if form.fields[name].disabled:
        return
    if _duplicate_field(form, name):
        form.add_error(name, 'این مقدار بیش از یک بار ارسال شده است.')
        return
    field = form.fields[name]
    value = field.widget.value_from_datadict(form.data, form.files, form.add_prefix(name))
    if isinstance(value, str) and invalid_control(value):
        form.add_error(name, 'این مقدار شامل نویسه کنترلی نامعتبر است.')


class RawControlsMixin:
    """Check selected single-line input before cleanup hides controls or duplicates."""

    raw_control_fields = ()

    def has_changed(self):
        # A duplicated value on an otherwise-empty optional formset row must
        # not be skipped merely because its last value is blank.
        return super().has_changed() or any(_duplicate_field(self, name) for name in self.raw_control_fields)

    def clean(self):
        cleaned = super().clean()
        for name in self.raw_control_fields:
            _check_raw_field(self, name, has_control_or_surrogate)
        return cleaned


class RawMultilineControlsMixin:
    """Inspect selected multiline input before cleanup hides controls or duplicates."""

    raw_multiline_control_fields = ()

    def has_changed(self):
        return super().has_changed() or any(_duplicate_field(self, name) for name in self.raw_multiline_control_fields)

    def clean(self):
        cleaned = super().clean()
        for name in self.raw_multiline_control_fields:
            _check_raw_field(self, name, has_forbidden_multiline_control)
        return cleaned


class SourceUploadRawControlsMixin(RawControlsMixin):
    """Check selected upload metadata and the single-file contract."""

    raw_control_fields = ('source_name', 'source_url', 'action')

    def clean(self):
        cleaned = super().clean()
        if (not self.fields['csv_file'].disabled and hasattr(self.files, 'getlist')
                and len(self.files.getlist(self.add_prefix('csv_file'))) > 1):
            self.add_error('csv_file', 'بیش از یک فایل ارسال شده است.')
        return cleaned


class StaffAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A forced initial focus bypasses the page title and skip link for
        # keyboard and screen-reader users. Leave the browser's initial focus.
        self.fields['username'].widget.attrs.pop('autofocus', None)

    def clean(self):
        # AuthenticationForm would otherwise silently use the last POST value.
        # Reject ambiguous credentials before invoking any authentication backend
        # and preserve the same non-enumerating error as other login failures.
        if any(_duplicate_field(self, name) for name in ('username', 'password')):
            self.user_cache = None
            raise self.get_invalid_login_error()
        return super().clean()

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
