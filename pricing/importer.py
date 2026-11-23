"""Stage authorized CSV data only. Never publish or change catalog data."""
import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

from django.db import transaction

from daroobank.validation import valid_private_source_url
from ingestion.locks import lock_source_stage
from catalog.models import ProductPresentation
from catalog.normalization import normalize_search
from .models import PriceCandidate

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000
MAX_RIAL = 9_223_372_036_854_775_807
MAX_MATCH_CANDIDATES = 100
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


class ImportValidationError(ValueError):
    """An actionable validation failure that never contains imported values."""


def validate_source(name, url):
    if not isinstance(name, str) or not isinstance(url, str):
        raise ImportValidationError('Source name and HTTPS URL are required and must be at most 200 characters.')
    name, url = name.strip(), url.strip()
    if (not name or len(name) > 200 or any(unicodedata.category(c) in ('Cc', 'Cs') for c in name)):
        raise ImportValidationError('Source name is invalid or oversized.')
    if not valid_private_source_url(url):
        raise ImportValidationError('Source URL must be valid HTTPS without credentials, query parameters, or a fragment.')
    return name, url


def amount_to_rial(amount, currency):
    """Convert explicitly declared currency with exact arithmetic and no rounding."""
    number = normalize_search(amount).replace('٫', '.')
    if not AMOUNT_PATTERN.fullmatch(number):
        raise ImportValidationError('Amount must be a positive plain decimal without separators or exponent.')
    if currency not in {'RIAL', 'TOMAN'}:
        raise ImportValidationError('Currency must explicitly be RIAL or TOMAN.')
    try:
        with localcontext() as context:
            context.prec = 80  # Longer than the maximum input; do not silently round.
            value = Decimal(number) * (10 if currency == 'TOMAN' else 1)
            if value <= 0 or value > MAX_RIAL or value != value.to_integral_value():
                raise ImportValidationError('Amount must convert exactly to a positive whole rial within range.')
            return int(value)
    except InvalidOperation as exc:
        raise ImportValidationError('Amount is not a valid decimal.') from exc


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
            data = path.read(MAX_FILE_BYTES + 1)
        else:
            with Path(path).open('rb') as f:
                data = f.read(MAX_FILE_BYTES + 1)
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


def suggest_product(row, *, lock=False):
    """Suggest only a unique exact presentation, conservatively bounded."""
    if not match_fields_valid(row):
        return PriceCandidate.MATCH_UNMATCHED, None
    possibilities = ProductPresentation.objects.filter(irc_normalized=normalize_search(row['irc'])).order_by('pk')
    if lock:
        possibilities = possibilities.select_for_update()
    # Too many records must not become a false unique suggestion or false negative.
    possibilities = list(possibilities[:MAX_MATCH_CANDIDATES + 1])
    if len(possibilities) > MAX_MATCH_CANDIDATES:
        return PriceCandidate.MATCH_AMBIGUOUS, None
    fields = IDENTITY_FIELDS[1:]
    normalized = {field: normalize_search(row[field]) for field in IDENTITY_FIELDS}
    matches = [p for p in possibilities if normalize_search(p.irc) == normalized['irc'] and all(
        normalize_search(getattr(p, field)) == normalized[field] for field in fields
    )]
    if len(matches) == 1:
        return PriceCandidate.MATCH_SUGGESTED, matches[0]
    if len(matches) > 1:
        return PriceCandidate.MATCH_AMBIGUOUS, None
    return PriceCandidate.MATCH_UNMATCHED, None


def stage_csv(path, source_name, source_url, *, commit=False, rights_attested=False, staged_by=None, on_staged=None):
    # Internal row callback runs inside the transaction; it must not cause external side effects.
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
    # Only validated rows reach this point. suggest_product uses precisely these
    # normalized identity fields; retain one observation per key for this call.
    # The catalog can change during the call, so these remain advisory, not a snapshot.
    suggestions = {}
    with transaction.atomic():
        if commit:
            lock_source_stage('price', source_url)
        for row, currency, amount, effective, published in rows:
            identity = tuple(normalize_search(row[field]) for field in IDENTITY_FIELDS)
            if identity not in suggestions:
                status, product = suggest_product(row)
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
            counts['created' if created else 'duplicates'] += 1
            if on_staged is not None:
                on_staged(candidate.pk, row['source_record_id'], digest, created, match_status)
    return counts
