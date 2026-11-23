"""Internal draft triage only: no verification, clinical approval or publication."""
import hashlib
import json
import re
import unicodedata
from datetime import date

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.transaction import TransactionManagementError

from catalog.normalization import normalize_search
from daroobank.account_checks import current_account_exists
from daroobank.write_conflict_boundary import write_conflict_boundary
from daroobank.validation import valid_private_source_url, valid_review_reason
from .models import ClinicalDraft, ClinicalDraftReview

VIEW = 'clinical.view_clinicaldraft'
ADD = 'clinical.add_clinicaldraft'
REVIEW = 'clinical.review_clinicaldraft'
REFERENCE_FIELDS = ('reference_title', 'reference_url', 'reference_location', 'reference_author',
                    'reference_version', 'reference_published_on', 'reference_accessed_on')
FIELDS = ('subject', 'audience', 'title', 'statement') + REFERENCE_FIELDS
LIMITS = {'subject': 200, 'title': 200, 'statement': 4000, 'reference_title': 300, 'reference_location': 300,
          'reference_author': 200, 'reference_version': 200}
OPTIONAL = {'reference_author', 'reference_version'}
HASH = re.compile(r'^[0-9a-f]{64}$')
MAX_PK = 9_223_372_036_854_775_807


class DraftError(ValueError):
    pass


class DraftConflict(ValueError):
    pass


def require_staff(user, *perms):
    if not user or not user.is_authenticated or not user.is_active or not user.is_staff or any(not user.has_perm(p) for p in perms):
        raise PermissionDenied


def _validate_text(field, value):
    if (not isinstance(value, str) or value != value.strip() or len(value) > LIMITS[field]
            or any(unicodedata.category(c) == 'Cs' or (unicodedata.category(c) == 'Cc' and
                   (field != 'statement' or c not in '\n\r\t')) for c in value)
            or (field not in OPTIONAL and not normalize_search(value))):
        raise DraftError('متن یا مشخصات ارجاع معتبر نیست.')


def validate_reference_data(data):
    if not isinstance(data, dict) or set(data) != set(REFERENCE_FIELDS):
        raise DraftError('ساختار ارجاع معتبر نیست.')
    for field in ('reference_title', 'reference_location', 'reference_author', 'reference_version'):
        _validate_text(field, data[field])
    if not valid_private_source_url(data['reference_url']):
        raise DraftError('نشانی ارجاع باید HTTPS معتبر و بدون اطلاعات محرمانه باشد.')
    for field in ('reference_published_on', 'reference_accessed_on'):
        if data[field] is not None and type(data[field]) is not date:
            raise DraftError('تاریخ ارجاع معتبر نیست.')


def validate_data(data):
    if not isinstance(data, dict) or set(data) != set(FIELDS):
        raise DraftError('ساختار پیش‌نویس معتبر نیست.')
    if not isinstance(data['audience'], str) or data['audience'] not in dict(ClinicalDraft.AUDIENCES):
        raise DraftError('مخاطب معتبر نیست.')
    for field in ('subject', 'title', 'statement'):
        _validate_text(field, data[field])
    validate_reference_data({key: data[key] for key in REFERENCE_FIELDS})


def draft_data(draft):
    return {key: getattr(draft, key) for key in FIELDS}


def snapshot(data, parent_id, parent_hash, change_reason):
    values = {key: value.isoformat() if isinstance(value, date) else value for key, value in data.items()}
    return {**values, 'parent_id': parent_id, 'parent_payload_sha256': parent_hash, 'change_reason': change_reason}


def fingerprint(data, parent_id, parent_hash, change_reason):
    payload = json.dumps(snapshot(data, parent_id, parent_hash, change_reason), ensure_ascii=False,
                         sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def valid_payload(draft):
    try:
        data = draft_data(draft)
        validate_data(data)
        if draft.parent_id is None:
            if draft.parent_payload_sha256 != '' or draft.change_reason != '':
                return False
        elif (not draft.pk or not 1 <= draft.parent_id < draft.pk or not HASH.fullmatch(draft.parent_payload_sha256)
              or not valid_review_reason(draft.change_reason)):
            return False
        return bool(HASH.fullmatch(draft.payload_sha256)) and fingerprint(data, draft.parent_id,
            draft.parent_payload_sha256, draft.change_reason) == draft.payload_sha256
    except (DraftError, TypeError, ValueError, AttributeError, OverflowError):
        return False


def valid_draft(draft):
    """Check this version and immediate parent, not full lineage or authenticity."""
    if not valid_payload(draft):
        return False
    if not draft.parent_id:
        return True
    try:
        parent = draft.parent
        return (valid_payload(parent) and parent.payload_sha256 == draft.parent_payload_sha256
                and parent.subject == draft.subject and parent.audience == draft.audience)
    except (ClinicalDraft.DoesNotExist, AttributeError):
        return False


def _valid_draft_for_update(draft):
    """Re-read and lock only the immediate parent of a locked draft, then validate.

    Call only inside the writer's transaction after locking the draft. A joined
    parent read before obtaining the row lock would be a potentially stale copy.
    Check only current existence of the subject's author, without locking it.
    """
    if not transaction.get_connection(draft._state.db).in_atomic_block:
        raise TransactionManagementError('Immediate-parent locking requires an atomic writer transaction.')
    if not valid_payload(draft):
        return False
    if draft.parent_id:
        try:
            parent = ClinicalDraft.objects.using(draft._state.db).select_for_update().get(pk=draft.parent_id)
        except ClinicalDraft.DoesNotExist:
            return False
        draft.parent = parent
    return valid_draft(draft) and current_account_exists(draft.author_id, using=draft._state.db)


def create_draft(*, actor, data, parent_id=None, expected_parent_hash='', change_reason=''):
    require_staff(actor, VIEW, ADD)
    validate_data(data)
    if parent_id is None:
        if expected_parent_hash != '' or change_reason != '':
            raise DraftError('نسخه اولیه نباید والد یا دلیل اصلاح داشته باشد.')
    elif (type(parent_id) is not int or not 1 <= parent_id <= 9_223_372_036_854_775_807
          or not isinstance(expected_parent_hash, str) or not HASH.fullmatch(expected_parent_hash)
          or not valid_review_reason(change_reason)):
        raise DraftError('اطلاعات نسخه پیشین یا دلیل اصلاح معتبر نیست.')
    with write_conflict_boundary(DraftConflict):
        parent = None
        if parent_id is not None:
            try:
                parent = ClinicalDraft.objects.select_for_update(of=('self',)).get(pk=parent_id)
            except ClinicalDraft.DoesNotExist as exc:
                raise DraftConflict('نسخه پیشین در دسترس نیست.') from exc
            if not _valid_draft_for_update(parent) or parent.payload_sha256 != expected_parent_hash:
                raise DraftConflict('نسخه پیشین تغییر کرده یا ناسازگار است؛ عملیات متوقف شد.')
            if data['subject'] != parent.subject or data['audience'] != parent.audience:
                raise DraftError('برای موضوع یا مخاطب متفاوت پیش‌نویس جدید بسازید.')
        digest = fingerprint(data, parent_id, expected_parent_hash, change_reason)
        return ClinicalDraft.objects.create(**data, author=actor, parent=parent, parent_payload_sha256=expected_parent_hash,
                                            change_reason=change_reason, payload_sha256=digest)


def _lock_latest_review(draft):
    """Lock the latest existing review ID; absent and future rows remain unlocked."""
    using = draft._state.db
    if not transaction.get_connection(using).in_atomic_block:
        raise TransactionManagementError('Latest-review locking requires an atomic writer transaction.')
    return (ClinicalDraftReview.objects.using(using).filter(draft_id=draft.pk)
            .order_by('-pk').select_for_update().only('pk').first())


def review_draft(*, actor, draft_id, decision, reason, expected_review, expected_hash, expected_evidence_hash=None):
    require_staff(actor, VIEW, REVIEW)
    if (type(draft_id) is not int or not 1 <= draft_id <= MAX_PK
            or not isinstance(decision, str) or decision not in dict(ClinicalDraftReview.DECISIONS)
            or not valid_review_reason(reason) or type(expected_review) is not int or not 0 <= expected_review <= MAX_PK
            or not isinstance(expected_hash, str) or not HASH.fullmatch(expected_hash)
            or (expected_evidence_hash is not None and (not isinstance(expected_evidence_hash, str)
                or not HASH.fullmatch(expected_evidence_hash)))):
        raise DraftConflict('اطلاعات بازبینی معتبر نیست.')
    with write_conflict_boundary(DraftConflict):
        draft = ClinicalDraft.objects.select_for_update(of=('self',)).get(pk=draft_id)
        if draft.author_id == actor.pk:
            raise PermissionDenied
        if not _valid_draft_for_update(draft) or draft.payload_sha256 != expected_hash:
            raise DraftConflict('پیش‌نویس یا نسخه پیشین تغییر کرده یا ناسازگار است.')
        from .evidence import evidence_state
        evidence = evidence_state(draft, lock=True)
        if evidence['status'] != 'available':
            raise DraftConflict('ارجاع‌های تکمیلی ناسازگارند یا از سقف مجاز بیشترند.')
        if any(item.recorded_by_id == actor.pk for item in evidence['items']):
            raise PermissionDenied
        if ((expected_evidence_hash is None and evidence['items'])
                or (expected_evidence_hash is not None and expected_evidence_hash != evidence['fingerprint'])):
            raise DraftConflict('ارجاع‌های تکمیلی تغییر کرده‌اند؛ صفحه را تازه کنید.')
        latest = _lock_latest_review(draft)
        if (latest.pk if latest else 0) != expected_review:
            raise DraftConflict('بازبینی جدیدی ثبت شده؛ صفحه را تازه کنید.')
        return ClinicalDraftReview.objects.create(draft=draft, reviewer=actor, decision=decision, reason=reason.strip(),
            draft_payload_sha256=draft.payload_sha256,
            review_snapshot={**snapshot(draft_data(draft), draft.parent_id, draft.parent_payload_sha256, draft.change_reason),
                             'author_id': draft.author_id, 'evidence_version': 1,
                             'evidence_fingerprint': evidence['fingerprint'],
                             'evidence_snapshot': evidence['snapshot']})
