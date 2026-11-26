"""Development-only registry of unverified source claims."""
from django.contrib.auth import HASH_SESSION_KEY
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from daroobank.account_checks import current_account_ids, current_accounts
from daroobank.review_history import recent_reviews_with_reviewers
from daroobank.scan_input import parse_scan_after
from daroobank.scan_responses import invalid_scan_response
from .claim_reads import bounded_claim_notes, materialize_claim_note
from .date_inspection import DATE_CATEGORIES, MAX_PK, inspect_dates
from .forms import SourceClaimForm, SourceReviewForm
from .models import SourceClaim, SourceClaimReview
from .review_inspection import (CATEGORIES as REVIEW_CATEGORIES, ReviewInspectionNotFound, classify_review,
                                inspect_reviews)
from .services import (ADD, FIELDS, REVIEW, VIEW, ClaimConflict, ClaimError, ReviewConflict,
                       date_label, record_claim, require_staff, review_claim)


def get_claim(pk):
    if not 1 <= pk <= 9_223_372_036_854_775_807:
        raise Http404('Claim not found')
    claim = get_object_or_404(bounded_claim_notes(SourceClaim.objects.all()), pk=pk)
    materialize_claim_note(claim)
    return claim


@login_required(login_url='staff_login')
@require_safe
def claims(request):
    require_staff(request.user, VIEW)
    status = request.GET.get('status', '')
    if status not in ('', 'pending', 'further_review', 'reject', 'defer'):
        return HttpResponseBadRequest('Invalid filter.')
    latest = SourceClaimReview.objects.filter(claim_id=OuterRef('pk')).order_by('-pk').values('decision')[:1]
    rows = SourceClaim.objects.annotate(latest_decision=Subquery(latest)).order_by('-pk')
    if status == 'pending':
        rows = rows.filter(latest_decision__isnull=True)
    elif status:
        rows = rows.filter(latest_decision=status)
    page = Paginator(bounded_claim_notes(rows), 20).get_page(request.GET.get('page', 1))
    # One local date for every row in this response, including across midnight.
    # This summary is only for the current page, not a database-wide count.
    today = timezone.localdate()
    date_counts = dict.fromkeys(('expired', 'future', 'within_dates', 'unknown', 'invalid'), 0)
    page_claims = list(page.object_list)
    recorders = (current_account_ids([claim.recorded_by_id for claim in page_claims], using=page_claims[0]._state.db)
                 if page_claims else set())
    for claim in page_claims:
        materialize_claim_note(claim)
        claim.recorder_missing = claim.recorded_by_id not in recorders
        claim.date_status = date_label(claim, today=today)
        date_counts[claim.date_status] += 1
    return render(request, 'staff/source_claims.html', {
        'page_title': 'ادعاهای منبع | داروبانک', 'description': 'ثبت داخلی ادعاهای منبع.',
        'noindex': True, 'private_staff': True, 'page': page, 'status': status,
        'date_summary_today': today, 'date_counts': date_counts,
        'can_add': request.user.has_perm(ADD), 'can_prices': request.user.has_perm('pricing.view_pricecandidate'),
        'can_products': request.user.has_perm('catalog.view_productcandidate'),
        'can_clinical': request.user.has_perm('clinical.view_clinicaldraft'),
    })


@login_required(login_url='staff_login')
@require_safe
def date_inspection(request):
    require_staff(request.user, VIEW)
    category = request.GET.get('category', '')
    try:
        after = parse_scan_after(request.GET.get('after', '0'), maximum=MAX_PK)
    except ValueError:
        return invalid_scan_response(request, restart_route='staff_source_date_inspection')
    if category not in ('', *DATE_CATEGORIES):
        return invalid_scan_response(request, restart_route='staff_source_date_inspection')
    report = inspect_dates(after=after, category=category)
    return render(request, 'staff/source_date_inspection.html', {
        'page_title': 'پیمایش تاریخ ادعاها | داروبانک', 'description': 'بازرسی محدود تاریخ‌های اعلام‌شده.',
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
        # Do not offer an anchor-specific restart for a nonexistent claim.
        get_claim(pk)
        return render(request, 'staff/source_review_inspection_error.html', {
            'page_title': 'ورودی بازرسی نامعتبر | داروبانک', 'description': 'ورودی نامعتبر.',
            'noindex': True, 'private_staff': True, 'claim_id': pk,
        }, status=400)
    try:
        report = inspect_reviews(actor=request.user, claim_id=pk, after=after, category=category)
    except ReviewInspectionNotFound:
        raise Http404('Claim not found')
    return render(request, 'staff/source_review_inspection.html', {
        'page_title': 'بازرسی بازبینی ادعا | داروبانک', 'description': 'بازرسی محدود بازبینی‌های ساختگی.',
        'noindex': True, 'private_staff': True, 'report': report,
    })


@login_required(login_url='staff_login')
@require_http_methods(['GET', 'POST'])
def create(request):
    require_staff(request.user, VIEW, ADD)
    form = SourceClaimForm(request.POST if request.method == 'POST' else None)
    status = 200
    if request.method == 'POST' and form.is_valid():
        try:
            claim, _created = record_claim(actor=request.user, data={key: form.cleaned_data[key] for key in FIELDS},
                                           session_auth_hash=request.session.get(HASH_SESSION_KEY))
            return redirect('staff_source_detail', pk=claim.pk)
        except ClaimConflict as exc:
            form.add_error(None, str(exc))
            status = 409
        except ClaimError as exc:
            form.add_error(None, str(exc))
    return render(request, 'staff/source_create.html', {
        'page_title': 'ثبت ادعای منبع | داروبانک', 'description': 'ثبت ادعای حقوق منبع.',
        'noindex': True, 'private_staff': True, 'form': form,
    }, status=status)


def detail_response(request, claim, *, form=None, status=200):
    reviews = recent_reviews_with_reviewers(claim.reviews.all())
    claim.display_recorder = current_accounts([claim.recorded_by_id], using=claim._state.db).get(claim.recorded_by_id)
    current_status = date_label(claim)
    for item in reviews:
        if item.content_oversized:
            item.technical_status, item.claim_comparison = 'oversized', 'unknown'
            continue
        item.technical_status, item.claim_comparison = classify_review(item, claim, current_status != 'invalid')
        if current_status == 'invalid':
            item.technical_status = 'unavailable'
            item.claim_comparison = 'unknown'
        elif item.display_reviewer is None:
            item.technical_status = 'missing_reviewer'
            item.claim_comparison = 'unknown'
    can_review = (request.user.has_perm(REVIEW) and claim.display_recorder is not None
                  and claim.recorded_by_id != request.user.pk and current_status != 'invalid')
    if can_review and form is None:
        form = SourceReviewForm(initial={'expected_review': reviews[0].pk if reviews else 0, 'expected_hash': claim.payload_sha256})
    return render(request, 'staff/source_detail.html', {
        'page_title': 'ادعای منبع | داروبانک', 'description': 'مشخصات ادعای منبع.',
        'noindex': True, 'private_staff': True, 'claim': claim, 'date_status': current_status,
        'reviews': reviews, 'can_review': can_review, 'review_form': form,
    }, status=status)


@login_required(login_url='staff_login')
@require_safe
def detail(request, pk):
    require_staff(request.user, VIEW)
    return detail_response(request, get_claim(pk))


@login_required(login_url='staff_login')
@require_POST
def review(request, pk):
    require_staff(request.user, VIEW, REVIEW)
    claim = get_claim(pk)
    form = SourceReviewForm(request.POST)
    if not form.is_valid():
        return detail_response(request, claim, form=form, status=400)
    try:
        review_claim(actor=request.user, claim_id=pk, session_auth_hash=request.session.get(HASH_SESSION_KEY),
                     **form.cleaned_data)
    except ReviewConflict as exc:
        form.add_error(None, str(exc))
        claim = get_claim(pk)
        return detail_response(request, claim, form=form, status=409)
    except SourceClaim.DoesNotExist:
        return HttpResponseBadRequest('Claim no longer exists.')
    return redirect('staff_source_detail', pk=pk)
