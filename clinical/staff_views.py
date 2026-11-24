"""Private development-only editorial triage; never publish."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from daroobank.account_checks import current_account_exists, current_account_ids, current_accounts
from daroobank.scan_input import parse_scan_after
from daroobank.scan_responses import invalid_scan_response
from daroobank.review_history import recent_reviews_with_reviewers
from sources.services import related_claims
from .inspection import CATEGORIES, MAX_PK, inspect_drafts
from .lineage import InvalidLineageCursor, LineageNotFound, inspect_lineage
from .review_inspection import CATEGORIES as REVIEW_CATEGORIES, ReviewInspectionNotFound, classify_review, inspect_reviews
from .forms import DraftForm, ReferenceForm, RevisionForm, ReviewForm
from .evidence import ASSERTION_FIELDS, add_reference, evidence_state, reviewed_evidence
from .models import ClinicalDraft, ClinicalDraftReview
from .services import ADD, FIELDS, REVIEW, VIEW, DraftConflict, DraftError, create_draft, draft_data, require_staff, review_draft, valid_draft


def get_draft(pk):
    if not 1 <= pk <= 9_223_372_036_854_775_807:
        raise Http404('Draft not found')
    return get_object_or_404(ClinicalDraft.objects.select_related('parent'), pk=pk)


@login_required(login_url='staff_login')
@require_safe
def drafts(request):
    require_staff(request.user, VIEW)
    status, audience = request.GET.get('status', ''), request.GET.get('audience', '')
    if status not in ('', 'pending', 'further_review', 'reject', 'defer') or audience not in ('', 'patient', 'professional'):
        return HttpResponseBadRequest('Invalid filter.')
    latest = ClinicalDraftReview.objects.filter(draft_id=OuterRef('pk')).order_by('-pk').values('decision')[:1]
    rows = ClinicalDraft.objects.select_related('parent').annotate(latest_decision=Subquery(latest)).order_by('-pk')
    if status == 'pending': rows = rows.filter(latest_decision__isnull=True)
    elif status: rows = rows.filter(latest_decision=status)
    if audience: rows = rows.filter(audience=audience)
    page = Paginator(rows, 20).get_page(request.GET.get('page', 1))
    authors = current_account_ids([item.author_id for item in page.object_list], using=rows.db)
    for item in page.object_list:
        item.is_valid = item.author_id in authors and valid_draft(item)
    return render(request, 'staff/clinical_drafts.html', {
        'page_title': 'پیش‌نویس‌های علمی | داروبانک', 'description': 'صف داخلی گزاره‌های ساختگی.',
        'noindex': True, 'private_staff': True, 'page': page, 'status': status, 'audience': audience,
        'can_add': request.user.has_perm(ADD), 'can_products': request.user.has_perm('catalog.view_productcandidate'),
        'can_prices': request.user.has_perm('pricing.view_pricecandidate'), 'can_sources': request.user.has_perm('sources.view_sourceclaim'),
    })


@login_required(login_url='staff_login')
@require_safe
def inspection(request):
    require_staff(request.user, VIEW)
    category = request.GET.get('category', '')
    try:
        after = parse_scan_after(request.GET.get('after', '0'), maximum=MAX_PK)
    except ValueError:
        return invalid_scan_response(request, restart_route='staff_clinical_inspection')
    if category not in ('', *CATEGORIES):
        return invalid_scan_response(request, restart_route='staff_clinical_inspection')
    report = inspect_drafts(after=after, category=category)
    return render(request, 'staff/clinical_inspection.html', {
        'page_title': 'بازرسی فنی پیش‌نویس‌ها | داروبانک',
        'description': 'بازرسی محدود پیش‌نویس‌های ساختگی.',
        'noindex': True, 'private_staff': True, 'report': report,
    })


@login_required(login_url='staff_login')
@require_http_methods(['GET', 'POST'])
def create(request):
    require_staff(request.user, VIEW, ADD)
    form = DraftForm(request.POST if request.method == 'POST' else None)
    status = 200
    if request.method == 'POST' and form.is_valid():
        try:
            draft = create_draft(actor=request.user, data={key: form.cleaned_data[key] for key in FIELDS})
            return redirect('staff_clinical_detail', pk=draft.pk)
        except DraftError as exc:
            form.add_error(None, str(exc))
        except DraftConflict as exc:
            form.add_error(None, str(exc)); status = 409
    return render(request, 'staff/clinical_form.html', {
        'page_title': 'ثبت پیش‌نویس | داروبانک', 'description': 'ثبت پیش‌نویس ساختگی.',
        'noindex': True, 'private_staff': True, 'form': form, 'parent': None,
    }, status=status)


@login_required(login_url='staff_login')
@require_http_methods(['GET', 'POST'])
def revise(request, pk):
    require_staff(request.user, VIEW, ADD)
    parent = get_draft(pk)
    if not valid_draft(parent) or not current_account_exists(parent.author_id, using=parent._state.db):
        return detail_response(request, parent, status=409)
    initial = {**draft_data(parent), 'expected_parent_hash': parent.payload_sha256}
    form = RevisionForm(request.POST if request.method == 'POST' else None, initial=initial)
    status = 200
    if request.method == 'POST' and form.is_valid():
        try:
            draft = create_draft(actor=request.user, data={key: form.cleaned_data[key] for key in FIELDS},
                parent_id=parent.pk, expected_parent_hash=form.cleaned_data['expected_parent_hash'],
                change_reason=form.cleaned_data['change_reason'])
            return redirect('staff_clinical_detail', pk=draft.pk)
        except DraftError as exc:
            form.add_error(None, str(exc))
        except DraftConflict as exc:
            form.add_error(None, str(exc)); status = 409
    return render(request, 'staff/clinical_form.html', {
        'page_title': 'اصلاح پیش‌نویس | داروبانک', 'description': 'نسخه جدید از پیش‌نویس.',
        'noindex': True, 'private_staff': True, 'form': form, 'parent': parent,
    }, status=status)


def detail_response(request, draft, *, form=None, status=200):
    draft.display_author = current_accounts([draft.author_id], using=draft._state.db).get(draft.author_id)
    valid = draft.display_author is not None and valid_draft(draft)
    reviews = recent_reviews_with_reviewers(draft.reviews.all())
    evidence = evidence_state(draft) if valid else {'status': 'invalid'}
    contributor = evidence['status'] == 'available' and any(item.recorded_by_id == request.user.pk for item in evidence['items'])
    can_review = (valid and evidence['status'] == 'available' and request.user.has_perm(REVIEW)
                  and draft.author_id != request.user.pk and not contributor)
    if can_review and form is None:
        form = ReviewForm(initial={'expected_review': reviews[0].pk if reviews else 0, 'expected_hash': draft.payload_sha256,
                                   'expected_evidence_hash': evidence['fingerprint']})
    for review in reviews:
        if review.content_oversized:
            review.technical_status, review.draft_comparison = 'oversized', 'unknown'
        elif review.display_reviewer is None:
            review.technical_status, review.draft_comparison = 'missing_reviewer', 'unknown'
        elif valid:
            review.technical_status, review.draft_comparison = classify_review(review, draft, True)
        else:
            review.technical_status, review.draft_comparison = 'unavailable', 'unknown'
        # Expose historical assertions only after the complete supported record
        # and reviewer/contributor separation pass the bounded technical check.
        review.evidence_history = {'status': 'unavailable'}
        if review.technical_status == 'consistent':
            review.evidence_history = reviewed_evidence(review)
            if evidence['status'] != 'available':
                review.evidence_status = 'unknown'
            elif review.evidence_history['fingerprint'] == evidence['fingerprint']:
                review.evidence_status = 'same'
            else:
                review.evidence_status = 'different'
        elif review.technical_status == 'legacy':
            review.evidence_status = 'legacy'
        elif review.technical_status == 'invalid_evidence':
            review.evidence_status = 'invalid'
        else:
            review.evidence_status = 'unknown'
    children = list(draft.revisions.select_related('parent').order_by('-pk')[:11]) if valid else []
    for child in children[:10]: child.is_valid = valid_draft(child)
    return render(request, 'staff/clinical_detail.html', {
        'page_title': 'پیش‌نویس علمی | داروبانک', 'description': 'جزئیات داخلی پیش‌نویس.',
        'noindex': True, 'private_staff': True, 'draft': draft, 'valid': valid, 'reviews': reviews,
        'review_form': form, 'can_review': can_review, 'can_add': valid and request.user.has_perm(ADD),
        'evidence': evidence, 'reviewer_is_contributor': contributor,
        'children': children[:10], 'children_limited': len(children) > 10,
        'source_claims': related_claims(request.user, draft.reference_url) if valid else None,
    }, status=status)


@login_required(login_url='staff_login')
@require_safe
def detail(request, pk):
    require_staff(request.user, VIEW)
    return detail_response(request, get_draft(pk))


@login_required(login_url='staff_login')
@require_safe
def lineage(request, pk):
    try:
        report = inspect_lineage(actor=request.user, anchor_id=pk, cursor=request.GET.get('cursor', ''))
    except LineageNotFound:
        raise Http404('Draft not found')
    except InvalidLineageCursor:
        return render(request, 'staff/clinical_lineage_error.html', {
            'page_title': 'ادامه بازرسی نامعتبر | داروبانک', 'description': 'درخواست بازرسی معتبر نیست.',
            'noindex': True, 'private_staff': True, 'anchor_id': pk,
        }, status=400)
    return render(request, 'staff/clinical_lineage.html', {
        'page_title': 'بازرسی نسخه‌های پیشین | داروبانک', 'description': 'مسیر نسخه‌های پیشین ساختگی.',
        'noindex': True, 'private_staff': True, 'report': report,
    })


@login_required(login_url='staff_login')
@require_safe
def review_inspection(request, pk):
    require_staff(request.user, VIEW)
    category = request.GET.get('category', '')
    try:
        after = parse_scan_after(request.GET.get('after', '0'), maximum=MAX_PK)
    except ValueError:
        after = None
    if after is None or category not in ('', *REVIEW_CATEGORIES):
        # Only render a restart link after confirming the anchor exists and is accessible.
        if not 1 <= pk <= MAX_PK or not ClinicalDraft.objects.filter(pk=pk).exists():
            raise Http404('Draft not found')
        return render(request, 'staff/clinical_review_inspection_error.html', {
            'page_title': 'ورودی بازرسی نامعتبر | داروبانک', 'description': 'ورودی نامعتبر.',
            'noindex': True, 'private_staff': True, 'draft_id': pk,
        }, status=400)
    try:
        report = inspect_reviews(actor=request.user, draft_id=pk, after=after, category=category)
    except ReviewInspectionNotFound:
        raise Http404('Draft not found')
    return render(request, 'staff/clinical_review_inspection.html', {
        'page_title': 'بازرسی بازبینی‌های پیش‌نویس | داروبانک', 'description': 'بازرسی محدود بازبینی‌های ساختگی.',
        'noindex': True, 'private_staff': True, 'report': report,
    })


@login_required(login_url='staff_login')
@require_POST
def review(request, pk):
    require_staff(request.user, VIEW, REVIEW)
    draft = get_draft(pk)
    form = ReviewForm(request.POST)
    if not form.is_valid():
        return detail_response(request, draft, form=form, status=400)
    try:
        review_draft(actor=request.user, draft_id=pk, **form.cleaned_data)
    except DraftConflict as exc:
        form.add_error(None, str(exc))
        draft = get_draft(pk)
        return detail_response(request, draft, form=form, status=409)
    except ClinicalDraft.DoesNotExist:
        return HttpResponseBadRequest('Draft no longer exists.')
    return redirect('staff_clinical_detail', pk=pk)


@login_required(login_url='staff_login')
@require_http_methods(['GET', 'POST'])
def reference_create(request, pk):
    require_staff(request.user, VIEW, ADD)
    draft = get_draft(pk)
    if not valid_draft(draft) or not current_account_exists(draft.author_id, using=draft._state.db):
        return detail_response(request, draft, status=409)
    state = evidence_state(draft)
    if state['status'] != 'available':
        return detail_response(request, draft, status=409)
    form = ReferenceForm(request.POST if request.method == 'POST' else None, initial={'expected_draft_hash': draft.payload_sha256,
                                                        'expected_evidence_hash': state['fingerprint']})
    status = 200
    if request.method == 'POST' and form.is_valid():
        try:
            add_reference(actor=request.user, draft_id=draft.pk,
                data={key: form.cleaned_data[key] for key in ASSERTION_FIELDS},
                expected_draft_hash=form.cleaned_data['expected_draft_hash'],
                expected_evidence_hash=form.cleaned_data['expected_evidence_hash'])
            return redirect('staff_clinical_detail', pk=draft.pk)
        except DraftError as exc:
            form.add_error(None, str(exc))
        except DraftConflict as exc:
            form.add_error(None, str(exc)); status = 409
    return render(request, 'staff/clinical_reference_form.html', {
        'page_title': 'ارجاع تکمیلی | داروبانک', 'description': 'ثبت ارجاع ساختگی برای نسخه داخلی.',
        'noindex': True, 'private_staff': True, 'form': form, 'draft': draft,
    }, status=status)
