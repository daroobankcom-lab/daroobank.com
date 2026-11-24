"""Stage authorized CSV data only. Never publish or change catalog data."""
import csv
import hashlib
import io
import json
import re
import unicodedata
from collections import OrderedDict
from datetime import date
from pathlib import Path

from daroobank.account_checks import current_account_exists
from daroobank.bounded_read import read_bounded_bytes
from daroobank.validation import has_control_or_surrogate, valid_private_source_url
from daroobank.write_conflict_boundary import write_conflict_boundary
from ingestion.exceptions import StagingConflict
from ingestion.locks import lock_source_stage
from catalog.models import ProductPresentation
from catalog.normalization import normalize_search
from .models import PriceCandidate

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MAX_RIAL = 9_223_372_036_854_775_807
MAX_MATCH_CANDIDATES = 100
MAX_CACHED_IRCS = 8
IDENTITY_FIELDS = ('irc', 'manufacturer', 'strength', 'dosage_form', 'package_description')
FIELDS = (
    'source_record_id', 'irc', 'manufacturer', 'strength', 'dosage_form',
    'package_description', 'amount', 'currency', 'category', 'unit',
    'effective_date', 'source_published_date',
)
LIMITS = {
    'source_record_id': 160, 'irc': 80, 'manufacturer': 200,
    'strength': 100, 'dosage_form': 100, 'package_description': 200,
    'amount': 50, 'currency': 5, 'category': 24, 'unit': 16,
    'effective_date': 10, 'source_published_date': 10,
}
OPTIONAL = {'effective_date', 'source_published_date'}
CATEGORIES = {'official_consumer', 'retail', 'manufacturer', 'wholesale', 'unit'}
UNITS = {'package', 'tablet', 'capsule', 'ampoule', 'vial', 'ml'}
AMOUNT_PATTERN = re.compile(r'^[0-9]+(?:\.[0-9]+)?$')
AMOUNT_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹', '01234567890123456789')
UNSAFE_AMOUNT_CATEGORIES = frozenset({'Cc', 'Cs', 'Cf', 'Mn', 'Me', 'Zl', 'Zp'})


def _unsafe_amount_characters(value):
    return any(unicodedata.category(char) in UNSAFE_AMOUNT_CATEGORIES for char in value)


class ImportValidationError(ValueError):
    """An actionable validation failure that never contains imported values."""


def validate_source(name, url):
    if not isinstance(name, str) or not isinstance(url, str):
        raise ImportValidationError('Source name and HTTPS URL are required and must be at most 200 characters.')
    if has_control_or_surrogate(name) or has_control_or_surrogate(url):
        raise ImportValidationError('Source name or URL contains unsupported characters.')
    name, url = name.strip(), url.strip()
    if (not name or len(name) > 200 or any(unicodedata.category(c) in ('Cc', 'Cs') for c in name)):
        raise ImportValidationError('Source name is invalid or oversized.')
    if not valid_private_source_url(url):
        raise ImportValidationError('Source URL must be valid HTTPS without credentials, query parameters, or a fragment.')
    return name, url


def amount_to_rial(amount, currency):
    """Convert bounded, explicitly declared currency exactly and without rounding."""
    if not isinstance(amount, str) or len(amount) > LIMITS['amount'] or _unsafe_amount_characters(amount):
        raise ImportValidationError('Amount must be a bounded plain decimal string.')
    normalized = unicodedata.normalize('NFKC', amount)
    if _unsafe_amount_characters(normalized):
        raise ImportValidationError('Amount must be a bounded plain decimal string.')
    # Search normalization intentionally removes marks and format characters;
    # financial amounts must reject them rather than silently change the input.
    number = normalized.translate(AMOUNT_DIGITS).replace('٫', '.').strip()
    if not AMOUNT_PATTERN.fullmatch(number):
        raise ImportValidationError('Amount must be a positive plain decimal without separators or exponent.')
    if not isinstance(currency, str) or currency not in {'RIAL', 'TOMAN'}:
        raise ImportValidationError('Currency must explicitly be RIAL or TOMAN.')
    integer, _, fraction = number.partition('.')
    # A toman is exactly ten rial. Move at most one fractional digit to the
    # integer part and reject any nonzero remainder, without decimal context or
    # rounding. Only convert the final bounded integer to avoid huge int inputs.
    if currency == 'TOMAN':
        integer += fraction[:1] or '0'
        fraction = fraction[1:]
    if fraction.strip('0'):
        raise ImportValidationError('Amount must convert exactly to a positive whole rial within range.')
    digits = integer.lstrip('0')
    upper = str(MAX_RIAL)
    if not digits or len(digits) > len(upper) or (len(digits) == len(upper) and digits > upper):
        raise ImportValidationError('Amount must convert exactly to a positive whole rial within range.')
    return int(digits)


def parse_date(value, field):
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError
        return parsed
    except ValueError as exc:
        raise ImportValidationError(f'{field} must be an ISO Gregorian date (YYYY-MM-DD) or blank.') from exc


def parse_csv(path):
    try:
        if hasattr(path, 'read'):
            data = read_bounded_bytes(path, limit=MAX_FILE_BYTES)
        else:
            with Path(path).open('rb') as f:
                data = read_bounded_bytes(f, limit=MAX_FILE_BYTES)
    except OSError as exc:
        raise ImportValidationError('Cannot read input file.') from exc
    if len(data) > MAX_FILE_BYTES:
        raise ImportValidationError('Input file exceeds the 2 MiB limit.')
    try:
        text = data.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ImportValidationError('Input must be UTF-8 CSV.') from exc
    try:
        reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
        if not reader.fieldnames or len(reader.fieldnames) != len(FIELDS) or set(reader.fieldnames) != set(FIELDS):
            raise ImportValidationError('CSV header must contain exactly the documented columns once each.')
        rows = []
        for line, row in enumerate(reader, start=2):
            if len(rows) >= MAX_ROWS:
                raise ImportValidationError('Input exceeds the 5000-row limit.')
            if None in row or any(value is None for value in row.values()):
                raise ImportValidationError(f'Row {line}: wrong number of fields.')
            # Controls must not be silently stripped from any raw CSV cell.
            for key in FIELDS:
                if has_control_or_surrogate(row[key]):
                    raise ImportValidationError(f'Row {line}: invalid or oversized {key}.')
            # Amounts additionally reject format/mark and line-separator characters.
            if _unsafe_amount_characters(row['amount']):
                raise ImportValidationError(f'Row {line}: invalid or oversized amount.')
            row = {key: value.strip() for key, value in row.items()}
            for key in FIELDS:
                if '\x00' in row[key] or len(row[key]) > LIMITS[key]:
                    raise ImportValidationError(f'Row {line}: invalid or oversized {key}.')
                if key not in OPTIONAL and not row[key]:
                    raise ImportValidationError(f'Row {line}: {key} is required.')
            try:
                currency = row['currency'].upper()
                category, unit = row['category'], row['unit']
                if category not in CATEGORIES or unit not in UNITS:
                    raise ImportValidationError('Unknown category or unit.')
                if category == 'unit' and unit == 'package':
                    raise ImportValidationError('Unit price cannot use package as its unit.')
                if (not match_fields_valid(row) or not normalize_search(row['source_record_id'])
                        or any(unicodedata.category(c) in ('Cc', 'Cs') for c in row['source_record_id'])):
                    raise ImportValidationError('Identifier and identity fields must be nonempty after normalization.')
                value = amount_to_rial(row['amount'], currency)
                effective = parse_date(row['effective_date'], 'effective_date')
                published = parse_date(row['source_published_date'], 'source_published_date')
            except ImportValidationError as exc:
                raise ImportValidationError(f'Row {line}: {exc}') from exc
            rows.append((row, currency, value, effective, published))
        if not rows:
            raise ImportValidationError('CSV contains no records.')
        return rows
    except csv.Error as exc:
        raise ImportValidationError('Invalid CSV format.') from exc


def match_fields_valid(row):
    if not isinstance(row, dict):
        return False
    for field in IDENTITY_FIELDS:
        value = row.get(field)
        if (not isinstance(value, str) or len(value) > LIMITS[field] or not normalize_search(value)
                or any(unicodedata.category(c) in ('Cc', 'Cs') for c in value)):
            return False
    return len(normalize_search(row['irc'])) <= 80


def _load_irc_index(irc, *, lock=False):
    """Index at most 100 candidates for one IRC; None means over the cap."""
    possibilities = ProductPresentation.objects.filter(irc_normalized=irc).order_by('pk')
    if lock:
        possibilities = possibilities.select_for_update()
    possibilities = list(possibilities[:MAX_MATCH_CANDIDATES + 1])
    # Too many records must not become a false unique suggestion or false negative.
    if len(possibilities) > MAX_MATCH_CANDIDATES:
        return None
    index = {}
    for product in possibilities:
        fields = {field: getattr(product, field) for field in IDENTITY_FIELDS}
        # A malformed value cannot be assigned safely to one identity. Treat the
        # entire indexed IRC group as uncertain rather than manufacture uniqueness.
        if any(not isinstance(value, str) for value in fields.values()):
            return None
        # A stale stored projection must not become a match.
        if normalize_search(fields['irc']) != irc:
            continue
        identity = tuple(normalize_search(fields[field]) for field in IDENTITY_FIELDS)
        name = product.name_fa
        safe_name = (isinstance(name, str) and bool(normalize_search(name))
                     and not any(unicodedata.category(c) in ('Cc', 'Cs') for c in name))
        # An unsafe presentation is still a potential match, not evidence of a
        # unique valid row. Poison only its normalized identity, when knowable.
        if not match_fields_valid(fields) or not safe_name or identity in index:
            index[identity] = None
        else:
            index[identity] = product
    return index


def _match_index(identity, index):
    if index is None:
        return PriceCandidate.MATCH_AMBIGUOUS, None
    if identity not in index:
        return PriceCandidate.MATCH_UNMATCHED, None
    product = index[identity]
    return ((PriceCandidate.MATCH_SUGGESTED, product) if product is not None
            else (PriceCandidate.MATCH_AMBIGUOUS, None))


def suggest_product(row, *, lock=False):
    """Suggest only a unique exact presentation, conservatively bounded."""
    if not match_fields_valid(row):
        return PriceCandidate.MATCH_UNMATCHED, None
    identity = tuple(normalize_search(row[field]) for field in IDENTITY_FIELDS)
    return _match_index(identity, _load_irc_index(identity[0], lock=lock))


def stage_csv(path, source_name, source_url, *, commit=False, rights_attested=False, staged_by=None, on_staged=None):
    # Internal row callback runs inside the transaction; it must not cause external side effects.
    if type(commit) is not bool:
        raise ImportValidationError('Commit mode must be an explicit boolean.')
    if on_staged is not None and (not commit or not callable(on_staged)):
        raise ImportValidationError('Row outcomes require staged commit mode.')
    if commit and rights_attested is not True:
        raise ImportValidationError('Staging requires an explicit source-rights attestation.')
    if staged_by is not None and (not staged_by.is_authenticated or not staged_by.is_active or not staged_by.is_staff
                                  or not staged_by.has_perm('pricing.view_pricecandidate')
                                  or not staged_by.has_perm('pricing.add_pricecandidate')):
        raise ImportValidationError('The staging account lacks the required staff permissions.')
    source_name, source_url = validate_source(source_name, source_url)
    # Validate the whole file before any write; malformed input cannot partially stage.
    rows = parse_csv(path)
    counts = {'rows': len(rows), 'suggested': 0, 'ambiguous': 0, 'unmatched': 0, 'created': 0, 'duplicates': 0}
    # Only validated rows reach this point. Both caches are per invocation and
    # advisory: changing catalog data is not observed consistently during a call.
    suggestions = {}
    irc_indexes = OrderedDict()
    with write_conflict_boundary(StagingConflict):
        if commit:
            lock_source_stage('price', source_url)
        for row, currency, amount, effective, published in rows:
            identity = tuple(normalize_search(row[field]) for field in IDENTITY_FIELDS)
            if identity not in suggestions:
                irc = identity[0]
                if irc not in irc_indexes:
                    if len(irc_indexes) == MAX_CACHED_IRCS:
                        irc_indexes.popitem(last=False)
                    irc_indexes[irc] = _load_irc_index(irc)
                else:
                    irc_indexes.move_to_end(irc)
                status, product = _match_index(identity, irc_indexes[irc])
                suggestions[identity] = (status, product.pk if product else None)
            match_status, product_id = suggestions[identity]
            counts[match_status] += 1
            if not commit:
                continue
            payload = json.dumps({'source_name': source_name, 'fields': row}, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
            digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
            candidate, created = PriceCandidate.objects.get_or_create(
                source_url=source_url, source_record_id=row['source_record_id'], payload_sha256=digest,
                defaults={
                    'source_name': source_name, 'source_fields': row,
                    'source_rights_attested': rights_attested, 'staged_by': staged_by,
                    'original_amount': row['amount'], 'original_currency': currency,
                    'amount_rial': amount, 'price_category': row['category'], 'unit': row['unit'],
                    'effective_date': effective, 'source_published_date': published,
                    'suggested_product_id': product_id, 'match_status': match_status,
                },
            )
            if not created:
                try:
                    candidate = PriceCandidate.objects.using(candidate._state.db).select_for_update().get(pk=candidate.pk)
                except PriceCandidate.DoesNotExist as exc:
                    raise StagingConflict('رکورد تکراری در دسترس نیست یا تغییر کرده است؛ ثبت متوقف شد.') from exc
                if (candidate.source_name != source_name or candidate.source_url != source_url
                        or candidate.source_record_id != row['source_record_id'] or candidate.source_fields != row
                        or candidate.payload_sha256 != digest or candidate.original_amount != row['amount']
                        or candidate.original_currency != currency or candidate.amount_rial != amount
                        or candidate.price_category != row['category'] or candidate.unit != row['unit']
                        or candidate.effective_date != effective or candidate.source_published_date != published
                        or candidate.source_rights_attested is not True
                        or (candidate.staged_by_id is not None
                            and not current_account_exists(candidate.staged_by_id, using=candidate._state.db))):
                    raise StagingConflict('رکورد تکراری در دسترس نیست یا تغییر کرده است؛ ثبت متوقف شد.')
            counts['created' if created else 'duplicates'] += 1
            if on_staged is not None:
                on_staged(candidate.pk, row['source_record_id'], digest, created, match_status)
    return counts
