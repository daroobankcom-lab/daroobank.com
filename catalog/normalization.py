"""Normalize only for lookup; display values are retained unchanged."""
import re
import unicodedata

_TRANSLATION = str.maketrans('يىك٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', 'ییک01234567890123456789')

def normalize_search(value):
    text = unicodedata.normalize('NFKC', value or '').translate(_TRANSLATION).casefold()
    text = text.replace('\u200c', ' ').replace('\u200d', ' ')
    text = ''.join(ch for ch in text if unicodedata.category(ch) not in ('Mn', 'Me', 'Cf'))
    return re.sub(r'\s+', ' ', text).strip()
