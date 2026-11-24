"""Small shared validators for private intake; not evidence or URL fetching."""
import unicodedata
from urllib.parse import urlsplit

from django.core.exceptions import ValidationError
from django.core.validators import URLValidator


def has_control_or_surrogate(value):
    """Check a string before trimming can hide controls at its boundaries."""
    return any(unicodedata.category(char) in ('Cc', 'Cs') for char in value)


def valid_private_source_url(value):
    if (not isinstance(value, str) or not value or len(value) > 200 or value != value.strip()
            or '?' in value or '#' in value
            or any(unicodedata.category(char) in ('Cc', 'Cs') for char in value)):
        return False
    try:
        URLValidator(schemes=['https'])(value)
        parsed = urlsplit(value)
        return parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment
    except (ValidationError, ValueError, UnicodeError):
        return False


def valid_review_reason(value):
    return (isinstance(value, str) and 12 <= len(value.strip()) <= 1000
            and not any(unicodedata.category(c) == 'Cs' or (unicodedata.category(c) == 'Cc' and c not in '\n\r\t')
                        for c in value))
