"""Internal source-rights assertions, never authorization or source access."""
import hashlib
import json
import re
import unicodedata
from datetime import date

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.db.transaction import TransactionManagementError
from django.utils import timezone

from catalog.normalization import normalize_search
from daroobank.account_checks import current_account_exists
from daroobank.write_conflict_boundary import write_conflict_boundary
from daroobank.validation import valid_private_source_url, valid_review_reason
from .models import SourceClaim, SourceClaimReview
from .claim_reads import bounded_claim_notes, materialize_claim_note

FIELDS = ('source_name', 'source_url', 'owner', 'evidence_url', 'evidence_note', 'claims_collection',
          'claims_storage', 'claims_publication', 'starts_on', 'expires_on')
VIEW = 'sources.view_sourceclaim'
ADD = 'sources.add_sourceclaim'
REVIEW = 'sources.review_sourceclaim'
SUMMARY_LIMIT = 5
MAX_PK = 9_223_372_036_854_775_807


class ClaimError(ValueError):
    pass


class ClaimConflict(ClaimError):
    """A selected transactional conflict while recording a claim."""


class ReviewConflict(ValueError):
    pass


def require_staff(user, *perms):
    if user is None or not user.is_authenticated or not user.is_active or not user.is_staff or any(not user.has_perm(p) for p in perms):
        raise PermissionDenied


def validate_url(value):
    if not valid_private_source_url(value):
        raise ClaimError('نشانی HTTPS معتبر و بدون اطلاعات محرمانه لازم است.')


def validate_data(data):
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        raise ClaimError('ساختار اطلاعات منبع معتبر نیست.')
    for key in ('source_name', 'owner', 'evidence_note'):
        value = data[key]
        limit = 1000 if key == 'evidence_note' else 200
        if (not isinstance(value, str) or value != value.strip() or len(value) > limit
                or any(unicodedata.category(c) in ('Cc', 'Cs') for c in value)
                or (key != 'evidence_note' and not normalize_search(value))):
            raise ClaimError('نام، مالک یا توضیح مدرک معتبر نیست.')
    validate_url(data['source_url'])
    validate_url(data['evidence_url'])
    flags = [data['claims_collection'], data['claims_storage'], data['claims_publication']]
    if any(type(flag) is not bool for flag in flags) or not any(flags):
        raise ClaimError('حداقل یک دامنه ادعاشده را انتخاب کنید.')
    for key in ('starts_on', 'expires_on'):
        value = data[key]
        if value is not None and type(value) is not date:
            raise ClaimError('تاریخ معتبر نیست.')
    if data['starts_on'] and data['expires_on'] and data['starts_on'] > data['expires_on']:
        raise ClaimError('تاریخ پایان نمی‌تواند قبل از تاریخ شروع باشد.')


def snapshot(data):
    return {key: (value.isoformat() if isinstance(value, date) else value) for key, value in data.items()}


def fingerprint(data):
    encoded = json.dumps(snapshot(data), sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def claim_data(claim):
    return {field: getattr(claim, field) for field in FIELDS}


def valid_claim(claim):
    if getattr(claim, 'note_oversized', False):
        return False
    try:
        data = claim_data(claim)
        validate_data(data)
        return bool(re.fullmatch(r'[0-9a-f]{64}', claim.payload_sha256)) and fingerprint(data) == claim.payload_sha256
    except (ClaimError, UnicodeError, TypeError):
        return False


def record_claim(*, actor, data):
    require_staff(actor, VIEW, ADD)
    validate_data(data)
    digest = fingerprint(data)
    with write_conflict_boundary(ClaimConflict):
        claim, created = SourceClaim.objects.get_or_create(source_url=data['source_url'], payload_sha256=digest,
                                                             defaults={**data, 'recorded_by': actor})
        if not created:
            # Re-read under the same row lock used by review, rather than trusting
            # a pre-lock replay object or only its stored digest.
            try:
                claim = SourceClaim.objects.using(claim._state.db).select_for_update().get(pk=claim.pk)
            except SourceClaim.DoesNotExist as exc:
                raise ClaimConflict('ادعای قبلی در دسترس نیست یا تغییر کرده است؛ ثبت متوقف شد.') from exc
            if (not valid_claim(claim) or claim_data(claim) != data
                    or not current_account_exists(claim.recorded_by_id, using=claim._state.db)):
                raise ClaimConflict('ادعای قبلی در دسترس نیست یا تغییر کرده است؛ ثبت متوقف شد.')
        return claim, created


def _lock_latest_review(claim):
    """Lock the latest existing review ID; absent and future rows remain unlocked."""
    using = claim._state.db
    if not transaction.get_connection(using).in_atomic_block:
        raise TransactionManagementError('Latest-review locking requires an atomic writer transaction.')
    return (SourceClaimReview.objects.using(using).filter(claim_id=claim.pk)
            .order_by('-pk').select_for_update().only('pk').first())


def review_claim(*, actor, claim_id, decision, reason, expected_review, expected_hash):
    require_staff(actor, VIEW, REVIEW)
    if (type(claim_id) is not int or not 1 <= claim_id <= MAX_PK
            or not isinstance(decision, str) or decision not in dict(SourceClaimReview.DECISIONS)
            or not valid_review_reason(reason) or type(expected_review) is not int or not 0 <= expected_review <= MAX_PK
            or not isinstance(expected_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_hash)):
        raise ReviewConflict('اطلاعات بازبینی معتبر نیست.')
    with write_conflict_boundary(ReviewConflict):
        claim = SourceClaim.objects.select_for_update().get(pk=claim_id)
        if claim.recorded_by_id == actor.pk:
            raise PermissionDenied
        if (not valid_claim(claim) or claim.payload_sha256 != expected_hash
                or not current_account_exists(claim.recorded_by_id, using=claim._state.db)):
            raise ReviewConflict('اطلاعات منبع یا ثبت‌کننده در دسترس نیست یا تغییر کرده است؛ بازبینی متوقف شد.')
        latest = _lock_latest_review(claim)
        if (latest.pk if latest else 0) != expected_review:
            raise ReviewConflict('بازبینی جدیدی ثبت شده است؛ صفحه را تازه کنید.')
        return SourceClaimReview.objects.create(
            claim=claim, reviewer=actor, decision=decision, reason=reason.strip(),
            claim_payload_sha256=claim.payload_sha256,
            review_snapshot={**snapshot(claim_data(claim)), 'recorded_by_id': claim.recorded_by_id},
        )


def date_label(claim, today=None):
    """Dates describe the claim, not authorization or verified validity."""
    today = today or timezone.localdate()
    if not valid_claim(claim):
        return 'invalid'
    if claim.expires_on and claim.expires_on < today:
        return 'expired'
    if claim.starts_on and claim.starts_on > today:
        return 'future'
    if claim.starts_on is None or claim.expires_on is None:
        return 'unknown'
    return 'within_dates'


def related_claims(user, source_url):
    """Return capped visible hints, never a permissions decision."""
    if not user.is_authenticated or not user.is_active or not user.is_staff or not user.has_perm(VIEW):
        return {'can_view': False}
    try:
        validate_url(source_url)
    except ClaimError:
        return {'can_view': True, 'invalid_url': True, 'items': [], 'limited': False}
    latest = SourceClaimReview.objects.filter(claim_id=OuterRef('pk')).order_by('-pk').values('decision')[:1]
    rows = list(bounded_claim_notes(SourceClaim.objects.filter(source_url=source_url)
                .annotate(latest_decision=Subquery(latest)).order_by('-pk'))[:SUMMARY_LIMIT + 1])
    items = []
    for claim in rows[:SUMMARY_LIMIT]:
        materialize_claim_note(claim)
        items.append({'claim': claim, 'date_label': date_label(claim)})
    return {'can_view': True, 'invalid_url': False, 'limited': len(rows) > SUMMARY_LIMIT, 'items': items}
