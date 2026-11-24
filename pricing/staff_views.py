"""Development-only, permission-gated price staging and preliminary review."""
import unicodedata
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Subquery
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from daroobank.account_checks import current_accounts
from daroobank.candidate_review_scan_views import scan_response
from daroobank.review_history import recent_reviews_with_reviewers
from daroobank.sample_downloads import synthetic_sample_response
from sources.services import related_claims
from ingestion.exceptions import StagingConflict
from ingestion.receipts import related_receipts, stage_price_with_receipt
from daroobank.forms import StaffAuthenticationForm

from .comparisons import price_revision_context, valid_candidate
from .forms import PriceReviewForm, PriceUploadForm
from .importer import ImportValidationError, match_fields_valid, stage_csv, suggest_product
from .models import PriceCandidate, PriceCandidateReview
from .review_inspection import classify_review
from .reviews import ReviewConflict, ensure_candidate_integrity, product_fingerprint, record_preliminary_review

STATUS_LABELS = {
    'suggested': 'پیشنهاد تطبیق', 'ambiguous': 'تطبیق مبهم یا بیش از سقف بررسی',
    'unmatched': 'بدون تطبیق', 'invalid': 'اطلاعات نامعتبر',
}
CATEGORY_LABELS = {
    'official_consumer': 'مصرف‌کننده اعلام‌شده', 'retail': 'خرده‌فروشی',
    'manufacturer': 'تولیدکننده', 'wholesale': 'عمده‌فروشی', 'unit': 'واحد',
}
UNIT_LABELS = {'package': 'بسته', 'tablet': 'قرص', 'capsule': 'کپسول', 'ampoule': 'آمپول', 'vial': 'ویال', 'ml': 'میلی‌لیتر'}
DECISION_LABELS = {'accept_suggestion': 'پذیرش اولیه پیشنهاد تطبیق', 'reject': 'رد نامزد', 'defer': 'نیاز به بررسی بیشتر'}


class StaffLoginView(LoginView):
    authentication_form = StaffAuthenticationForm
    template_name = 'staff/login.html'
    extra_context = {'page_title': 'ورود همکاران | داروبانک', 'description': 'ورود به بخش داخلی داروبانک.', 'noindex': True, 'private_staff': True}

    def get_default_redirect_url(self):
        # Django's safe explicit `next` is resolved before this default.
        if self.request.user.is_active and self.request.user.is_staff:
            return reverse('staff_workspace')
        return super().get_default_redirect_url()


class StaffLogoutView(LogoutView):
    next_page = 'home'


def _require_permission(user, extra=None):
    if (not user.is_active or not user.is_staff or not user.has_perm('pricing.view_pricecandidate')
            or (extra and not user.has_perm(extra))):
        raise PermissionDenied


def _display_source_fields(fields):
    """Do not render malformed JSON values or invalid Unicode from bypassed writes."""
    if not isinstance(fields, dict):
        return {}
    keys = ('irc', 'manufacturer', 'strength', 'dosage_form', 'package_description')
    return {key: value for key in keys if isinstance((value := fields.get(key)), str)
            and not any(unicodedata.category(c) in ('Cc', 'Cs') for c in value)}


def _current_suggestion(candidate):
    try:
        ensure_candidate_integrity(candidate)
    except ReviewConflict:
        return 'invalid', None
    fields = candidate.source_fields
    if not match_fields_valid(fields):
        return 'invalid', None
    return suggest_product(fields)


def _detail_response(request, candidate, *, form=None, status=200):
    current_status, current_product = _current_suggestion(candidate)
    reviews = recent_reviews_with_reviewers(candidate.reviews.all())
    candidate.display_stager = current_accounts([candidate.staged_by_id], using=candidate._state.db).get(candidate.staged_by_id)
    for review in reviews:
        review.technical_status, review.candidate_comparison = classify_review(
            review, candidate, current_status != 'invalid' and candidate.display_stager is not None)
    can_review = bool(current_status != 'invalid' and request.user.has_perm('pricing.review_pricecandidate')
                      and candidate.display_stager is not None and candidate.source_rights_attested
                      and candidate.staged_by_id != request.user.pk)
    if form is None and can_review:
        form = PriceReviewForm(initial={
            'expected_review': reviews[0].pk if reviews else 0,
            'expected_product': current_product.pk if current_product else 0,
            'expected_product_hash': product_fingerprint(current_product) if current_product else '',
        })
    return render(request, 'staff/price_detail.html', {
        'page_title': 'جزئیات نامزد قیمت | داروبانک', 'description': 'جزئیات داده قیمت برای بررسی داخلی.',
        'noindex': True, 'private_staff': True, 'candidate': candidate, 'source_fields': _display_source_fields(candidate.source_fields), 'current_product': current_product,
        'current_label': STATUS_LABELS[current_status], 'payload_invalid': current_status == 'invalid',
        'snapshot_label': STATUS_LABELS.get(candidate.match_status, STATUS_LABELS['invalid']),
        'category_label': CATEGORY_LABELS.get(candidate.price_category, 'نامشخص'),
        'unit_label': UNIT_LABELS.get(candidate.unit, 'نامشخص'), 'reviews': reviews,
        'review_form': form, 'can_review': can_review, 'comparison': price_revision_context(candidate),
        'source_claims': related_claims(request.user, candidate.source_url),
        'receipt_refs': related_receipts(request.user, candidate, 'price'),
    }, status=status)


@login_required(login_url='staff_login')
@require_safe
def price_candidates(request):
    _require_permission(request.user)
    status = request.GET.get('status', '')
    review_status = request.GET.get('review', '')
    if (status and status not in dict(PriceCandidate.MATCH_CHOICES)) or review_status not in ('', 'pending', 'accept_suggestion', 'reject', 'defer'):
        return HttpResponseBadRequest('Invalid filter.')
    stats = {item['match_status']: item['count'] for item in PriceCandidate.objects.values('match_status').annotate(count=Count('id'))}
    latest = PriceCandidateReview.objects.filter(candidate_id=OuterRef('pk')).order_by('-pk').values('decision')[:1]
    rows = PriceCandidate.objects.annotate(latest_decision=Subquery(latest)).order_by('-collected_at', '-pk')
    if status:
        rows = rows.filter(match_status=status)
    if review_status == 'pending':
        rows = rows.filter(latest_decision__isnull=True)
    elif review_status:
        rows = rows.filter(latest_decision=review_status)
    page = Paginator(rows, 20).get_page(request.GET.get('page', 1))
    for item in page.object_list:
        item.display_consistent = valid_candidate(item)
        item.display_fields = _display_source_fields(item.source_fields) if item.display_consistent else {}
    return render(request, 'staff/prices.html', {
        'page_title': 'نامزدهای قیمت | داروبانک', 'description': 'بخش داخلی بررسی داده‌های قیمت.',
        'noindex': True, 'private_staff': True, 'page': page, 'status': status, 'review_status': review_status, 'stats': stats,
        'total': sum(stats.values()), 'can_import': request.user.has_perm('pricing.add_pricecandidate'),
        'can_products': request.user.has_perm('catalog.view_productcandidate'),
        'can_sources': request.user.has_perm('sources.view_sourceclaim'),
        'can_clinical': request.user.has_perm('clinical.view_clinicaldraft'),
    })


@login_required(login_url='staff_login')
@require_safe
def sample_download(request):
    _require_permission(request.user, 'pricing.add_pricecandidate')
    return synthetic_sample_response('price')


@login_required(login_url='staff_login')
@require_http_methods(['GET', 'POST'])
def price_upload(request):
    _require_permission(request.user, 'pricing.add_pricecandidate')
    form = PriceUploadForm(request.POST if request.method == 'POST' else None,
                           request.FILES if request.method == 'POST' else None)
    result = None
    status = 200
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            if data['action'] == 'stage':
                result, receipt = stage_price_with_receipt(data['csv_file'], data['source_name'], data['source_url'],
                                                          actor=request.user, rights_attested=data['rights_attested'])
                result['receipt_id'] = receipt.pk
            else:
                result = stage_csv(data['csv_file'], data['source_name'], data['source_url'], staged_by=request.user)
            result['mode'] = data['action']
        except ImportValidationError as exc:
            form.add_error(None, 'فایل معتبر نیست؛ هیچ داده‌ای ثبت نشد. ' + str(exc))
        except StagingConflict:
            form.add_error(None, 'ثبت به دلیل تداخل هم‌زمان یا ناسازگاری رکورد قبلی متوقف شد؛ وضعیت داده را بررسی و برای تلاش دوباره فایل را دوباره انتخاب کنید.')
            status = 409
    return render(request, 'staff/upload.html', {
        'page_title': 'ورود فایل قیمت | داروبانک', 'description': 'ورود مرحله‌ای فایل قیمت.',
        'noindex': True, 'private_staff': True, 'form': form, 'result': result,
    }, status=status)


def _get_candidate(pk):
    if not 1 <= pk <= 9_223_372_036_854_775_807:
        raise Http404('Candidate not found')
    return get_object_or_404(PriceCandidate, pk=pk)


@login_required(login_url='staff_login')
@require_safe
def review_inspection(request, pk):
    return scan_response(request, pk, 'price')


@login_required(login_url='staff_login')
@require_safe
def price_candidate_detail(request, pk):
    _require_permission(request.user)
    candidate = _get_candidate(pk)
    return _detail_response(request, candidate)


@login_required(login_url='staff_login')
@require_POST
def price_review(request, pk):
    _require_permission(request.user, 'pricing.review_pricecandidate')
    candidate = _get_candidate(pk)
    form = PriceReviewForm(request.POST)
    if not form.is_valid():
        return _detail_response(request, candidate, form=form, status=400)
    try:
        record_preliminary_review(candidate_id=pk, actor=request.user, **form.cleaned_data)
    except ReviewConflict as exc:
        form.add_error(None, str(exc))
        candidate.refresh_from_db()
        return _detail_response(request, candidate, form=form, status=409)
    except PriceCandidate.DoesNotExist:
        return HttpResponseBadRequest('Candidate no longer exists.')
    return redirect('staff_price_detail', pk=pk)
