"""Bounded internal candidate intake and preliminary triage; never publish."""
import csv
import hashlib
import io
import json
import re
import unicodedata

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.transaction import TransactionManagementError

from daroobank.account_checks import current_account_exists
from daroobank.actor_recheck import recheck_actor
from daroobank.bounded_read import read_bounded_bytes
from daroobank.candidate_content_bounds import bounded_candidates, materialize_candidate
from daroobank.write_conflict_boundary import write_conflict_boundary
from daroobank.validation import has_control_or_surrogate, valid_private_source_url, valid_review_reason
from ingestion.exceptions import StagingConflict
from ingestion.locks import lock_source_stage

from .models import ProductCandidate, ProductCandidateReview
from .normalization import normalize_search

MAX_FILE_BYTES = 1024 * 1024
MAX_ROWS = 1000
MAX_PK = 9_223_372_036_854_775_807
FIELDS = ('source_record_id', 'name_fa', 'name_en', 'manufacturer', 'strength', 'dosage_form', 'package_description', 'irc')
LIMITS = {'source_record_id': 160, 'name_fa': 200, 'name_en': 200, 'manufacturer': 200,
          'strength': 100, 'dosage_form': 100, 'package_description': 200, 'irc': 80}
OPTIONAL = {'name_en', 'irc'}


class IntakeError(ValueError):
    pass


class ReviewConflict(ValueError):
    pass


def require_staff(user, *permissions):
    if not user.is_authenticated or not user.is_active or not user.is_staff or any(not user.has_perm(p) for p in permissions):
        raise PermissionDenied


def valid_source(name, url):
    if (not isinstance(name, str) or not name.strip() or len(name) > 200 or name != name.strip()
            or any(unicodedata.category(c) in ('Cc', 'Cs') for c in name)
            or not isinstance(url, str) or len(url) > 200 or url != url.strip()):
        raise IntakeError('نام یا نشانی منبع معتبر نیست.')
    if not valid_private_source_url(url):
        raise IntakeError('نشانی منبع باید HTTPS معتبر و بدون اطلاعات محرمانه باشد.')


def valid_fields(row):
    if not isinstance(row, dict) or set(row) != set(FIELDS):
        raise IntakeError('ستون‌های فایل باید دقیقاً مطابق قالب مستند باشند.')
    for key in FIELDS:
        value = row[key]
        if (not isinstance(value, str) or value != value.strip() or len(value) > LIMITS[key]
                or any(unicodedata.category(c) in ('Cc', 'Cs') for c in value)
                or (key not in OPTIONAL and not normalize_search(value))):
            raise IntakeError(f'مقدار ستون {key} معتبر نیست.')
    if row['irc'] and (not normalize_search(row['irc']) or len(normalize_search(row['irc'])) > 80):
        raise IntakeError('کد IRC معتبر نیست.')


def parse_product_csv(file):
    try:
        data = read_bounded_bytes(file, limit=MAX_FILE_BYTES)
    except OSError as exc:
        raise IntakeError('خواندن فایل ممکن نیست.') from exc
    if len(data) > MAX_FILE_BYTES:
        raise IntakeError('حجم فایل بیش از یک مگابایت است.')
    try:
        text = data.decode('utf-8-sig')
        reader = csv.DictReader(io.StringIO(text, newline=''), strict=True)
        if not reader.fieldnames or len(reader.fieldnames) != len(FIELDS) or set(reader.fieldnames) != set(FIELDS):
            raise IntakeError('ستون‌های فایل باید دقیقاً مطابق قالب مستند باشند.')
        rows = []
        for line, row in enumerate(reader, 2):
            if len(rows) >= MAX_ROWS:
                raise IntakeError('فایل بیش از ۱۰۰۰ ردیف دارد.')
            if None in row or any(value is None for value in row.values()):
                raise IntakeError(f'تعداد ستون‌های ردیف {line} معتبر نیست.')
            # Do not erase controls at cell boundaries before field validation.
            for key in FIELDS:
                if has_control_or_surrogate(row[key]):
                    raise IntakeError(f'ردیف {line}: مقدار ستون {key} معتبر نیست.')
            row = {key: value.strip() for key, value in row.items()}
            try:
                valid_fields(row)
            except IntakeError as exc:
                raise IntakeError(f'ردیف {line}: {exc}') from exc
            rows.append(row)
        if not rows:
            raise IntakeError('فایل بدون ردیف داده است.')
        return rows
    except (UnicodeDecodeError, csv.Error) as exc:
        raise IntakeError('فایل باید CSV معتبر با کدگذاری UTF-8 باشد.') from exc


def fingerprint(source_name, source_url, fields):
    payload = json.dumps({'source_name': source_name, 'source_url': source_url, 'fields': fields},
                         sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _find_or_create_candidate(**kwargs):
    # Existing rows only need an ID before the authoritative locked read.
    return ProductCandidate.objects.only('pk').get_or_create(**kwargs)


def stage_products(file, source_name, source_url, *, actor, commit=False, rights_attested=False, on_staged=None,
                   session_auth_hash=None):
    # Internal row callback runs inside the transaction; it must not cause external side effects.
    require_staff(actor, 'catalog.view_productcandidate', 'catalog.add_productcandidate')
    if type(commit) is not bool:
        raise IntakeError('حالت ثبت باید مقدار بولی صریح باشد.')
    if on_staged is not None and (not commit or not callable(on_staged)):
        raise IntakeError('ثبت جزئیات ردیف فقط در حالت ثبت مرحله‌ای ممکن است.')
    if commit and rights_attested is not True:
        raise IntakeError('برای ثبت باید مجوز ذخیره داخلی را اظهار کنید.')
    valid_source(source_name, source_url)
    rows = parse_product_csv(file)
    counts = {'rows': len(rows), 'created': 0, 'duplicates': 0}
    with write_conflict_boundary(StagingConflict):
        if commit:
            lock_source_stage('product', source_url)
            # Re-verify the stager before any row is written. The read is
            # deliberately unlocked to keep one lock order across services, so it is
            # a point-in-time check and a later credential change still races.
            # Preview mode writes nothing and is not rechecked here. ADR 0195.
            recheck_actor(actor, ('catalog.view_productcandidate', 'catalog.add_productcandidate'),
                          session_auth_hash=session_auth_hash)
            for row in rows:
                digest = fingerprint(source_name, source_url, row)
                candidate, created = _find_or_create_candidate(
                    source_url=source_url, source_record_id=row['source_record_id'],
                    payload_sha256=digest,
                    defaults={'source_name': source_name, 'source_fields': row, 'staged_by': actor,
                              'source_rights_attested': True, 'irc_normalized': normalize_search(row['irc'])},
                )
                if not created:
                    try:
                        candidate = bounded_candidates(ProductCandidate.objects.using(candidate._state.db)
                            .select_for_update()).get(pk=candidate.pk)
                    except ProductCandidate.DoesNotExist as exc:
                        raise StagingConflict('رکورد تکراری در دسترس نیست یا تغییر کرده است؛ ثبت متوقف شد.') from exc
                    materialize_candidate(candidate)
                    if (candidate.content_oversized or candidate.source_name != source_name or candidate.source_url != source_url
                            or candidate.source_record_id != row['source_record_id'] or candidate.source_fields != row
                            or candidate.payload_sha256 != digest or candidate.irc_normalized != normalize_search(row['irc'])
                            or candidate.source_rights_attested is not True
                            or not current_account_exists(candidate.staged_by_id, using=candidate._state.db)):
                        raise StagingConflict('رکورد تکراری در دسترس نیست یا تغییر کرده است؛ ثبت متوقف شد.')
                counts['created' if created else 'duplicates'] += 1
                if on_staged is not None:
                    on_staged(candidate.pk, row['source_record_id'], digest, created, None)
    return counts


def _lock_latest_review(candidate):
    """Lock the latest existing review ID; absent and future rows remain unlocked."""
    using = candidate._state.db
    if not transaction.get_connection(using).in_atomic_block:
        raise TransactionManagementError('Latest-review locking requires an atomic writer transaction.')
    return (ProductCandidateReview.objects.using(using).filter(candidate_id=candidate.pk)
            .order_by('-pk').select_for_update().only('pk').first())


def review_product(*, candidate_id, actor, decision, reason, expected_review, expected_hash,
                   session_auth_hash=None):
    if actor is None:
        raise PermissionDenied
    require_staff(actor, 'catalog.view_productcandidate', 'catalog.review_productcandidate')
    if (type(candidate_id) is not int or not 1 <= candidate_id <= MAX_PK
            or not isinstance(decision, str) or decision not in dict(ProductCandidateReview.DECISIONS)
            or not valid_review_reason(reason) or type(expected_review) is not int or not 0 <= expected_review <= MAX_PK
            or not isinstance(expected_hash, str) or not re.fullmatch(r'[0-9a-f]{64}', expected_hash)):
        raise ReviewConflict('اطلاعات بازبینی معتبر نیست.')
    with write_conflict_boundary(ReviewConflict):
        candidate = bounded_candidates(ProductCandidate.objects.select_for_update()).get(pk=candidate_id)
        # Re-verify the reviewer after taking the candidate lock. The read is
        # deliberately unlocked to keep one lock order across services, so it is a
        # point-in-time check and a later credential change still races. ADR 0195.
        recheck_actor(actor, ('catalog.view_productcandidate', 'catalog.review_productcandidate'),
                      session_auth_hash=session_auth_hash)
        materialize_candidate(candidate)
        if candidate.staged_by_id == actor.pk:
            raise PermissionDenied
        if (not candidate.staged_by_id or not candidate.source_rights_attested
                or not current_account_exists(candidate.staged_by_id, using=candidate._state.db)):
            raise ReviewConflict('اظهار مجوز یا ثبت‌کننده در دسترس نیست.')
        if candidate.content_oversized:
            raise ReviewConflict('داده نامزد بیش از حد بررسی است؛ بازبینی متوقف شد.')
        try:
            valid_source(candidate.source_name, candidate.source_url)
            valid_fields(candidate.source_fields)
            digest = fingerprint(candidate.source_name, candidate.source_url, candidate.source_fields)
        except IntakeError as exc:
            raise ReviewConflict('داده ثبت‌شده معتبر نیست.') from exc
        if (candidate.source_record_id != candidate.source_fields['source_record_id']
                or candidate.irc_normalized != normalize_search(candidate.source_fields['irc'])
                or candidate.payload_sha256 != digest or expected_hash != digest):
            raise ReviewConflict('اطلاعات رکورد تغییر کرده است؛ صفحه را تازه کنید.')
        latest = _lock_latest_review(candidate)
        if (latest.pk if latest else 0) != expected_review:
            raise ReviewConflict('بازبینی جدیدی ثبت شده است؛ صفحه را تازه کنید.')
        snapshot = {'source_name': candidate.source_name, 'source_url': candidate.source_url,
                    'source_fields': candidate.source_fields, 'staged_by_id': candidate.staged_by_id,
                    'source_rights_attested': candidate.source_rights_attested}
        return ProductCandidateReview.objects.create(candidate=candidate, reviewer=actor, decision=decision,
            reason=reason.strip(), candidate_payload_sha256=digest, review_snapshot=snapshot)
