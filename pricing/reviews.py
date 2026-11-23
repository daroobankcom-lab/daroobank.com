"""Record preliminary review events, never public price approvals."""
import hashlib
import hmac
import io
import csv
import json
import re

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.transaction import TransactionManagementError

from daroobank.account_checks import current_account_exists
from daroobank.validation import valid_review_reason

from .importer import FIELDS, LIMITS, ImportValidationError, parse_csv, suggest_product, validate_source
from .models import PriceCandidate, PriceCandidateReview


MAX_PK = 9_223_372_036_854_775_807


class ReviewConflict(ValueError):
    pass


def product_snapshot(product):
    return {
        'id': product.pk, 'name_fa': product.name_fa, 'irc': product.irc,
        'manufacturer': product.manufacturer, 'strength': product.strength,
        'dosage_form': product.dosage_form, 'package_description': product.package_description,
    }


def product_fingerprint(product):
    encoded = json.dumps(product_snapshot(product), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def ensure_candidate_integrity(candidate):
    """Check staged fields and derived values without treating the source as verified."""
    fields = candidate.source_fields
    if not isinstance(fields, dict) or set(fields) != set(FIELDS):
        raise ReviewConflict('ساختار داده منبع معتبر نیست؛ بررسی متوقف شد.')
    if any(not isinstance(fields[key], str) or len(fields[key]) > LIMITS[key] for key in FIELDS):
        raise ReviewConflict('فیلدهای داده منبع معتبر نیست؛ بررسی متوقف شد.')
    try:
        if validate_source(candidate.source_name, candidate.source_url) != (candidate.source_name, candidate.source_url):
            raise ValueError
        buffer = io.StringIO(newline='')
        writer = csv.DictWriter(buffer, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerow(fields)
        parsed, currency, amount, effective, published = parse_csv(io.BytesIO(buffer.getvalue().encode('utf-8')))[0]
    except (ImportValidationError, ValueError) as exc:
        raise ReviewConflict('داده ذخیره‌شده قابل اعتبارسنجی نیست؛ بررسی متوقف شد.') from exc
    payload = json.dumps({'source_name': candidate.source_name, 'fields': fields}, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    digest = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    consistent = (
        parsed == fields and candidate.source_record_id == fields['source_record_id']
        and candidate.original_amount == fields['amount'] and candidate.original_currency == currency
        and candidate.amount_rial == amount and candidate.price_category == fields['category']
        and candidate.unit == fields['unit'] and candidate.effective_date == effective
        and candidate.source_published_date == published and candidate.payload_sha256 == digest
    )
    if not re.fullmatch(r'[0-9a-f]{64}', candidate.payload_sha256):
        raise ReviewConflict('شناسه محتوای منبع معتبر نیست؛ بررسی متوقف شد.')
    if not consistent:
        raise ReviewConflict('اطلاعات منبع یا مقدار ذخیره‌شده تغییر کرده است؛ بررسی متوقف شد.')


def _lock_latest_review(candidate):
    """Lock the latest existing review ID; absent and future rows remain unlocked."""
    using = candidate._state.db
    if not transaction.get_connection(using).in_atomic_block:
        raise TransactionManagementError('Latest-review locking requires an atomic writer transaction.')
    return (PriceCandidateReview.objects.using(using).filter(candidate_id=candidate.pk)
            .order_by('-pk').select_for_update().only('pk').first())


def record_preliminary_review(*, candidate_id, actor, decision, reason, expected_review, expected_product, expected_product_hash):
    if not actor or not actor.is_authenticated or not actor.is_active or not actor.is_staff or not actor.has_perm('pricing.view_pricecandidate') or not actor.has_perm('pricing.review_pricecandidate'):
        raise PermissionDenied
    if (type(candidate_id) is not int or not 1 <= candidate_id <= MAX_PK
            or not isinstance(decision, str) or decision not in dict(PriceCandidateReview.DECISIONS)
            or not valid_review_reason(reason) or type(expected_review) is not int or not 0 <= expected_review <= MAX_PK
            or type(expected_product) is not int or not 0 <= expected_product <= MAX_PK
            or not isinstance(expected_product_hash, str)):
        raise ReviewConflict('نتیجه یا توضیح بررسی معتبر نیست.')
    if decision == PriceCandidateReview.ACCEPT_SUGGESTION and not re.fullmatch(r'[0-9a-f]{64}', expected_product_hash):
        raise ReviewConflict('شناسه تطبیق معتبر نیست.')
    with transaction.atomic():
        candidate = PriceCandidate.objects.select_for_update().get(pk=candidate_id)
        if not candidate.staged_by_id or not candidate.source_rights_attested:
            raise ReviewConflict('این رکورد فاقد ثبت‌کننده یا اظهار مجوز است و در این مسیر قابل بررسی نیست.')
        if candidate.staged_by_id == actor.pk:
            raise PermissionDenied
        if not current_account_exists(candidate.staged_by_id, using=candidate._state.db):
            raise ReviewConflict('حساب ثبت‌کننده در دسترس نیست؛ بررسی متوقف شد.')
        ensure_candidate_integrity(candidate)
        latest = _lock_latest_review(candidate)
        if (latest.pk if latest else 0) != expected_review:
            raise ReviewConflict('این رکورد هم‌زمان تغییر کرده است؛ صفحه را تازه کنید.')
        product = None
        fingerprint = ''
        if decision == PriceCandidateReview.ACCEPT_SUGGESTION:
            # Locks existing rows, not absent matching rows or future inserts.
            current, product = suggest_product(candidate.source_fields, lock=True)
            if current != PriceCandidate.MATCH_SUGGESTED or product is None:
                raise ReviewConflict('پیشنهاد تطبیق فعلی یکتا نیست؛ پذیرش اولیه ممکن نیست.')
            fingerprint = product_fingerprint(product)
            if product.pk != expected_product or not hmac.compare_digest(fingerprint, expected_product_hash):
                raise ReviewConflict('مشخصات فرآورده تغییر کرده است؛ صفحه را تازه کنید.')
        snapshot = {
            'source_name': candidate.source_name, 'source_url': candidate.source_url,
            'source_record_id': candidate.source_record_id, 'source_fields': candidate.source_fields,
            'amount_rial': candidate.amount_rial, 'source_rights_attested': candidate.source_rights_attested,
            'staged_by_id': candidate.staged_by_id,
            'product': product_snapshot(product) if product else None,
        }
        return PriceCandidateReview.objects.create(
            candidate=candidate, reviewer=actor, decision=decision, reason=reason.strip(),
            reviewed_product=product, candidate_payload_sha256=candidate.payload_sha256,
            product_identity_sha256=fingerprint, review_snapshot=snapshot,
        )
