"""Private development-only editorial triage; never publish."""
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import OuterRef, Subquery
from django.http import Http404, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST, require_safe

from sources.services import related_claims
from .forms import DraftForm, RevisionForm, ReviewForm
from .models import ClinicalDraft, ClinicalDraftReview
from .services import ADD, FIELDS, REVIEW, VIEW, DraftConflict, DraftError, create_draft, draft_data, require_staff, review_draft, valid_draft


def get_draft(pk):
    if not 1 <= pk <= 9_223_372_036_854_775_807:
        raise Http404('Draft not found')
    return get_object_or_404(ClinicalDraft.objects.select_related('author', 'parent'), pk=pk)


@login_required(login_url='staff_login')
@require_safe
def drafts(request):
    require_staff(request.user, VIEW)
    status, audience = request.GET.get('status', ''), request.GET.get('audience', '')
    if status not in ('', 'pending', 'further_review', 'reject', 'defer') or audience not in ('', 'patient', 'professional'):
        return HttpResponseBadRequest('Invalid filter.')
    latest = ClinicalDraftReview.objects.filter(draft_id=OuterRef('pk')).order_by('-pk').values('decision')[:1]
    rows = ClinicalDraft.objects.select_related('author', 'parent').annotate(latest_decision=Subquery(latest)).order_by('-pk')
    if status == 'pending': rows = rows.filter(latest_decision__isnull=True)
    elif status: rows = rows.filter(latest_decision=status)
    if audience: rows = rows.filter(audience=audience)
    page = Paginator(rows, 20).get_page(request.GET.get('page', 1))
    for item in page.object_list:
        item.is_valid = valid_draft(item)
    return render(request, 'staff/clinical_drafts.html', {
        'page_title': 'پیش‌نویس‌های علمی | داروبانک', 'description': 'صف داخلی گزاره‌های ساختگی.',
        'noindex': True, 'private_staff': True, 'page': page, 'status': status, 'audience': audience,
        'can_add': request.user.has_perm(ADD), 'can_products': request.user.has_perm('catalog.view_productcandidate'),
        'can_prices': request.user.has_perm('pricing.view_pricecandidate'), 'can_sources': request.user.has_perm('sources.view_sourceclaim'),
    })


@login_required(login_url='staff_login')
@require_http_methods(['GET', 'POST'])
def create(request):
    require_staff(request.user, VIEW, ADD)
    form = DraftForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        try:
            draft = create_draft(actor=request.user, data={key: form.cleaned_data[key] for key in FIELDS})
            return redirect('staff_clinical_detail', pk=draft.pk)
        except DraftError as exc:
            form.add_error(None, str(exc))
    return render(request, 'staff/clinical_form.html', {
        'page_title': 'ثبت پیش‌نویس | داروبانک', 'description': 'ثبت پیش‌نویس ساختگی.',
        'noindex': True, 'private_staff': True, 'form': form, 'parent': None,
    })


@login_required(login_url='staff_login')
@require_http_methods(['GET', 'POST'])
def revise(request, pk):
    require_staff(request.user, VIEW, ADD)
    parent = get_draft(pk)
    if not valid_draft(parent):
        return detail_response(request, parent, status=409)
    initial = {**draft_data(parent), 'expected_parent_hash': parent.payload_sha256}
    form = RevisionForm(request.POST or None, initial=initial)
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
    valid = valid_draft(draft)
    reviews = list(draft.reviews.select_related('reviewer').order_by('-pk')[:25])
    can_review = valid and request.user.has_perm(REVIEW) and draft.author_id != request.user.pk
    if can_review and form is None:
        form = ReviewForm(initial={'expected_review': reviews[0].pk if reviews else 0, 'expected_hash': draft.payload_sha256})
    children = list(draft.revisions.select_related('parent').order_by('-pk')[:11]) if valid else []
    for child in children[:10]: child.is_valid = valid_draft(child)
    return render(request, 'staff/clinical_detail.html', {
        'page_title': 'پیش‌نویس علمی | داروبانک', 'description': 'جزئیات داخلی پیش‌نویس.',
        'noindex': True, 'private_staff': True, 'draft': draft, 'valid': valid, 'reviews': reviews,
        'review_form': form, 'can_review': can_review, 'can_add': valid and request.user.has_perm(ADD),
        'children': children[:10], 'children_limited': len(children) > 10,
        'source_claims': related_claims(request.user, draft.reference_url) if valid else None,
    }, status=status)


@login_required(login_url='staff_login')
@require_safe
def detail(request, pk):
    require_staff(request.user, VIEW)
    return detail_response(request, get_draft(pk))


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
