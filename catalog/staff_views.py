"""Development-only staff product intake, never public publishing."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.http import Http404, HttpResponseBadRequest
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from sources.services import related_claims
from ingestion.receipts import related_receipts, stage_product_with_receipt

from .comparisons import product_comparison_context
from .intake import IntakeError, ReviewConflict, require_staff, review_product, stage_products
from .models import ProductCandidate, ProductCandidateReview
from .staff_forms import ProductReviewForm, ProductUploadForm

VIEW = 'catalog.view_productcandidate'
ADD = 'catalog.add_productcandidate'
REVIEW = 'catalog.review_productcandidate'


@login_required(login_url='staff_login')
@require_safe
def candidates(request):
    require_staff(request.user, VIEW)
    status = request.GET.get('status', '')
    if status not in ('', 'pending', 'further_review', 'reject', 'defer'):
        return HttpResponseBadRequest('Invalid filter.')
    latest = ProductCandidateReview.objects.filter(candidate_id=OuterRef('pk')).order_by('-pk').values('decision')[:1]
    rows = ProductCandidate.objects.select_related('staged_by').annotate(latest_decision=Subquery(latest)).order_by('-pk')
    if status == 'pending':
        rows = rows.filter(latest_decision__isnull=True)
    elif status:
        rows = rows.filter(latest_decision=status)
    page = Paginator(rows, 20).get_page(request.GET.get('page', 1))
    return render(request, 'staff/products.html', {
        'page_title': 'نامزدهای فرآورده | داروبانک', 'description': 'صف داخلی نامزدهای فرآورده.',
        'noindex': True, 'private_staff': True, 'page': page, 'status': status,
        'can_import': request.user.has_perm(ADD), 'can_prices': request.user.has_perm('pricing.view_pricecandidate'),
        'can_sources': request.user.has_perm('sources.view_sourceclaim'),
        'can_clinical': request.user.has_perm('clinical.view_clinicaldraft'),
        'can_quality': request.user.has_perm('catalog.view_productpresentation'),
    })


@login_required(login_url='staff_login')
@require_http_methods(['GET', 'POST'])
def upload(request):
    require_staff(request.user, VIEW, ADD)
    form = ProductUploadForm(request.POST or None, request.FILES or None)
    result = None
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            if data['action'] == 'stage':
                result, receipt = stage_product_with_receipt(data['csv_file'], data['source_name'], data['source_url'],
                                                            actor=request.user, rights_attested=data['rights_attested'])
                result['receipt_id'] = receipt.pk
            else:
                result = stage_products(data['csv_file'], data['source_name'], data['source_url'], actor=request.user)
            result['mode'] = data['action']
        except IntakeError as exc:
            form.add_error(None, 'فایل معتبر نیست؛ هیچ داده‌ای ثبت نشد. ' + str(exc))
    return render(request, 'staff/product_upload.html', {
        'page_title': 'ورود فرآورده | داروبانک', 'description': 'ورود مرحله‌ای مشخصات فرآورده.',
        'noindex': True, 'private_staff': True, 'form': form, 'result': result,
    })


def get_candidate(pk):
    if not 1 <= pk <= 9_223_372_036_854_775_807:
        raise Http404('Candidate not found')
    return get_object_or_404(ProductCandidate.objects.select_related('staged_by'), pk=pk)


def detail_response(request, candidate, *, form=None, status=200):
    reviews = list(candidate.reviews.select_related('reviewer').order_by('-pk')[:25])
    can_review = (request.user.has_perm(REVIEW) and candidate.staged_by_id != request.user.pk
                  and bool(candidate.staged_by_id) and candidate.source_rights_attested)
    if form is None and can_review:
        form = ProductReviewForm(initial={'expected_review': reviews[0].pk if reviews else 0,
                                          'expected_hash': candidate.payload_sha256})
    return render(request, 'staff/product_detail.html', {
        'page_title': 'نامزد فرآورده | داروبانک', 'description': 'جزئیات داخلی نامزد فرآورده.',
        'noindex': True, 'private_staff': True, 'candidate': candidate, 'reviews': reviews,
        'can_review': can_review, 'review_form': form, 'comparison': product_comparison_context(candidate),
        'source_claims': related_claims(request.user, candidate.source_url),
        'receipt_refs': related_receipts(request.user, candidate, 'product'),
    }, status=status)


@login_required(login_url='staff_login')
@require_safe
def detail(request, pk):
    require_staff(request.user, VIEW)
    candidate = get_candidate(pk)
    return detail_response(request, candidate)


@login_required(login_url='staff_login')
@require_POST
def review(request, pk):
    require_staff(request.user, VIEW, REVIEW)
    candidate = get_candidate(pk)
    form = ProductReviewForm(request.POST)
    if not form.is_valid():
        return detail_response(request, candidate, form=form, status=400)
    try:
        review_product(candidate_id=pk, actor=request.user, **form.cleaned_data)
    except ReviewConflict as exc:
        form.add_error(None, str(exc))
        candidate.refresh_from_db()
        return detail_response(request, candidate, form=form, status=409)
    except ProductCandidate.DoesNotExist:
        return HttpResponseBadRequest('Candidate no longer exists.')
    return redirect('staff_product_detail', pk=pk)
