"""Parse starting IDs for private, read-only scan forms."""

_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def parse_scan_after(raw, *, maximum):
    """Accept only 1–19 ASCII, Persian or Arabic-Indic digits within the bound.

    Length is checked before conversion. No signs, spacing, separators,
    exponent notation, compatibility characters or other digit sets are accepted.
    """
    if not isinstance(raw, str) or not 1 <= len(raw) <= 19:
        raise ValueError('Invalid starting ID')
    normalized = raw.translate(_DIGITS)
    if not normalized.isascii() or not normalized.isdecimal():
        raise ValueError('Invalid starting ID')
    value = int(normalized)
    if value > maximum:
        raise ValueError('Invalid starting ID')
    return value
