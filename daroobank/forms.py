"""Forms shared by the development-only staff portal."""
from django.contrib.auth.forms import AuthenticationForm


class StaffAuthenticationForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # A forced initial focus bypasses the page title and skip link for
        # keyboard and screen-reader users. Leave the browser's initial focus.
        self.fields['username'].widget.attrs.pop('autofocus', None)
