"""Forms shared by the development-only staff portal."""
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError


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
